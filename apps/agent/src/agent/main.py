import argparse
import hashlib
import json
import logging
import os
import os.path
import shutil
import socket
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("agent")

EXCLUDED_DEVICE_PREFIXES = ("loop", "dm-", "zd", "sr")
SYSTEM_MOUNTPOINTS = {"/", "/boot", "/boot/efi"}
SYSTEM_FS_MARKERS = {"LVM2_member", "zfs_member"}


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AgentSettings:
    api_base_url: str = os.getenv("AGENT_API_BASE_URL", "http://localhost:8000/api/v1")
    hostname: str = os.getenv("AGENT_HOSTNAME", socket.gethostname())
    agent_version: str = os.getenv("AGENT_VERSION", "0.1.0")
    timeout_seconds: float = float(os.getenv("AGENT_TIMEOUT_SECONDS", "10"))
    include_non_usb_candidates: bool = parse_bool(
        os.getenv("AGENT_INCLUDE_NON_USB_CANDIDATES"),
        default=False,
    )
    pbs_api_url: str = os.getenv("PBS_API_URL", "")
    pbs_auth_id: str = os.getenv("PBS_TOKEN_ID", "")
    pbs_auth_secret: str = os.getenv("PBS_TOKEN_SECRET", "")
    pbs_verify_ssl: bool = parse_bool(os.getenv("PBS_VERIFY_SSL"), default=False)
    pbs_fingerprint: str | None = os.getenv("PBS_FINGERPRINT") or None
    export_timeout_seconds: float = float(os.getenv("AGENT_EXPORT_TIMEOUT_SECONDS", "7200"))


def post_heartbeat(settings: AgentSettings) -> None:
    payload = {
        "hostname": settings.hostname,
        "agent_version": settings.agent_version,
        "observed_at": current_timestamp(),
    }
    post_json(settings, "/agent/heartbeat", payload)
    logger.info("Heartbeat sent for host %s", settings.hostname)


def post_real_disk_report(settings: AgentSettings) -> None:
    disks = discover_real_disks(settings)
    payload = {
        "hostname": settings.hostname,
        "observed_at": current_timestamp(),
        "disks": disks,
    }
    post_json(settings, "/agent/disks/report", payload)
    logger.info("Real disk report sent for host %s with %s disks", settings.hostname, len(disks))


def post_mock_disk_report(settings: AgentSettings) -> None:
    payload = {
        "hostname": settings.hostname,
        "observed_at": current_timestamp(),
        "disks": mock_disks(),
    }
    post_json(settings, "/agent/disks/report", payload)
    logger.info("Mock disk report sent for host %s", settings.hostname)


def sync_state(settings: AgentSettings) -> None:
    post_heartbeat(settings)
    post_real_disk_report(settings)


def prepare_external_datastore(mount_path: str, target_path: str, mode: str) -> None:
    mount = Path(mount_path).resolve()
    target = Path(target_path).resolve()
    _validate_external_target(mount, target, mode)

    if not mount.is_dir():
        raise FileNotFoundError(f"Mount path does not exist: {mount_path}")

    target.mkdir(parents=True, exist_ok=True)
    _ensure_directory_permissions(target)

    payload = {
        "ok": True,
        "mount_path": str(mount),
        "target_path": str(target),
        "command_summary": f"mkdir -p {target} && chmod 750 {target}",
        "execution_cwd": str(Path.cwd()),
        "stdout_log": f"Prepared target directory {target}",
        "stderr_log": None,
        "message": "Target directory is ready for external datastore export.",
        "return_code": 0,
    }
    print(json.dumps(payload))
    logger.info("Prepared external datastore target %s", target)


def run_external_export(target_path: str, datastore_name: str, mode: str, settings: AgentSettings) -> None:
    target = Path(target_path).resolve()
    if not target.is_dir():
        raise FileNotFoundError(f"Target path does not exist: {target_path}")

    manager = shutil.which("proxmox-backup-manager")
    if manager is None:
        raise RuntimeError(
            "Missing required host dependency: `proxmox-backup-manager` was not found in PATH."
        )

    if not settings.pbs_api_url:
        raise RuntimeError("PBS_API_URL must be configured on the host agent for external export.")
    if not settings.pbs_auth_id or not settings.pbs_auth_secret:
        raise RuntimeError("PBS_TOKEN_ID and PBS_TOKEN_SECRET must be configured on the host agent.")

    api = parse_pbs_api_url(settings.pbs_api_url)
    datastores_result = run_subprocess(
        [manager, "datastore", "list", "--output-format", "json"],
        timeout_seconds=settings.export_timeout_seconds,
    )
    if datastores_result.returncode != 0:
        raise RuntimeError(format_command_failure("Unable to inspect PBS datastores.", datastores_result))

    datastores = parse_json_output(datastores_result.stdout, "datastore list")
    datastore_names = {item.get("name") for item in datastores if isinstance(item, dict)}
    if datastore_name not in datastore_names:
        raise RuntimeError(f"Invalid source datastore `{datastore_name}` on this PBS host.")

    existing_target_store = find_datastore_by_path(datastores, target)
    created_datastore = existing_target_store is None
    target_store_name = existing_target_store or build_resource_name("pbo-export-store", str(target))
    remote_name = build_resource_name("pbo-export-remote", f"{api['host']}:{datastore_name}:{target}")
    sync_job_name = build_resource_name("pbo-export-sync", f"{datastore_name}:{target}")

    command_summaries: list[str] = []
    stdout_logs: list[str] = []
    stderr_logs: list[str] = []
    cleanup_errors: list[str] = []
    sync_completed = False
    created_temp_datastore = False
    created_remote = False
    created_sync_job = False

    try:
        if created_datastore:
            create_store_result = run_subprocess(
                [
                    manager,
                    "datastore",
                    "create",
                    target_store_name,
                    str(target),
                    "--reuse-datastore",
                    "true",
                ],
                timeout_seconds=settings.export_timeout_seconds,
            )
            record_command_result(create_store_result, command_summaries, stdout_logs, stderr_logs)
            if create_store_result.returncode != 0:
                raise RuntimeError(
                    format_command_failure(
                        f"Failed to create target datastore `{target_store_name}`.",
                        create_store_result,
                    )
                )
            created_temp_datastore = True

        remote_create = [
            manager,
            "remote",
            "create",
            remote_name,
            "--host",
            str(api["host"]),
            "--port",
            str(api["port"]),
            "--auth-id",
            settings.pbs_auth_id,
            "--password",
            settings.pbs_auth_secret,
        ]
        if settings.pbs_fingerprint:
            remote_create.extend(["--fingerprint", settings.pbs_fingerprint])

        remote_result = run_subprocess(remote_create, timeout_seconds=settings.export_timeout_seconds)
        record_command_result(remote_result, command_summaries, stdout_logs, stderr_logs)
        if remote_result.returncode != 0:
            raise RuntimeError(
                format_command_failure(f"Failed to create temporary PBS remote `{remote_name}`.", remote_result)
            )
        created_remote = True

        sync_create = [
            manager,
            "sync-job",
            "create",
            sync_job_name,
            "--remote",
            remote_name,
            "--remote-store",
            datastore_name,
            "--store",
            target_store_name,
            "--remove-vanished",
            "false",
            "--owner",
            settings.pbs_auth_id.split("!", 1)[0],
        ]
        sync_create_result = run_subprocess(sync_create, timeout_seconds=settings.export_timeout_seconds)
        record_command_result(sync_create_result, command_summaries, stdout_logs, stderr_logs)
        if sync_create_result.returncode != 0:
            raise RuntimeError(
                format_command_failure(
                    f"Failed to create temporary sync job `{sync_job_name}`.",
                    sync_create_result,
                )
            )
        created_sync_job = True

        sync_run_result = run_subprocess(
            [manager, "sync-job", "run", sync_job_name],
            timeout_seconds=settings.export_timeout_seconds,
        )
        record_command_result(sync_run_result, command_summaries, stdout_logs, stderr_logs)
        if sync_run_result.returncode != 0:
            raise RuntimeError(
                format_command_failure(
                    f"PBS sync execution failed for datastore `{datastore_name}`.",
                    sync_run_result,
                )
            )
        sync_completed = True
    finally:
        if created_sync_job:
            cleanup_errors.extend(
                cleanup_resource([manager, "sync-job", "remove", sync_job_name], settings.export_timeout_seconds)
            )
        if created_remote:
            cleanup_errors.extend(
                cleanup_resource([manager, "remote", "remove", remote_name], settings.export_timeout_seconds)
            )
        if created_temp_datastore:
            cleanup_errors.extend(
                cleanup_resource([manager, "datastore", "remove", target_store_name], settings.export_timeout_seconds)
            )

    if cleanup_errors:
        stderr_logs.append("\n".join(cleanup_errors))

    message = (
        f"External PBS export completed into `{target}` from datastore `{datastore_name}`."
        if sync_completed
        else f"External PBS export failed for datastore `{datastore_name}`."
    )
    if cleanup_errors and sync_completed:
        message = f"{message} Cleanup reported warnings."

    payload = {
        "ok": sync_completed,
        "target_path": str(target),
        "datastore_name": datastore_name,
        "mode": mode,
        "command_summary": "\n".join(command_summaries),
        "execution_cwd": str(Path.cwd()),
        "stdout_log": "\n\n".join(chunk for chunk in stdout_logs if chunk) or None,
        "stderr_log": "\n\n".join(chunk for chunk in stderr_logs if chunk) or None,
        "message": message,
        "return_code": 0 if sync_completed else 1,
    }
    print(json.dumps(payload))
    logger.info("External export finished for datastore %s into %s", datastore_name, target)


def inspect_disk(identifier: str, mount_base_path: str | None = None) -> None:
    disk, _ = resolve_disk(identifier)
    serial = disk_serial_number(disk, load_udev_properties(device_name(disk))) or device_name(disk)
    filesystem_node = find_filesystem_node(disk)
    blkid_info = get_blkid_info(filesystem_node["path"]) if filesystem_node else {}
    filesystem_type = None
    if filesystem_node is not None:
        filesystem_type = blkid_info.get("TYPE") or filesystem_node.get("fstype")
    candidate_mount_path = str(default_mount_base_path(mount_base_path) / serial)
    payload = {
        "success": True,
        "disk": summarize_node(disk),
        "filesystem_info": {
            "device_path": filesystem_node["path"] if filesystem_node else None,
            "filesystem_type": filesystem_type,
            "uuid": blkid_info.get("UUID"),
            "mount_path": filesystem_node["mountpoint"] if filesystem_node else None,
        },
        "partition_info": [summarize_node(node) for node in list_partition_nodes(disk)],
        "candidate_mount_path": candidate_mount_path,
        "message": "Disk inspection completed.",
    }
    print(json.dumps(payload))
    logger.info("Inspected disk %s", identifier)


def prepare_disk(
    identifier: str,
    mode: str,
    mount_base_path: str | None,
    confirm_destructive: bool,
) -> None:
    disk, _ = resolve_disk(identifier)
    serial = disk_serial_number(disk, load_udev_properties(device_name(disk))) or device_name(disk)
    mount_path = default_mount_base_path(mount_base_path) / serial

    if mode == "preserve_existing_data":
        filesystem_node = find_filesystem_node(disk)
        if filesystem_node is None:
            raise RuntimeError("Preserve mode requires an existing filesystem.")

        filesystem_type = get_blkid_info(filesystem_node["path"]).get("TYPE") or filesystem_node["fstype"]
        if not filesystem_type:
            raise RuntimeError("Unable to determine filesystem type for preserve mode.")

        ensure_mountpoint(mount_path)
        ensure_fstab_entry(filesystem_node["path"], str(mount_path), filesystem_type)
        mount_target(filesystem_node["path"], str(mount_path))
        payload = {
            "success": True,
            "mount_path": str(mount_path),
            "filesystem_type": filesystem_type,
            "message": "Existing filesystem mounted under an application-managed path.",
        }
        print(json.dumps(payload))
        logger.info("Prepared disk %s in preserve mode at %s", identifier, mount_path)
        return

    if mode == "dedicated_backup":
        if not confirm_destructive:
            raise RuntimeError("Dedicated backup mode requires destructive confirmation.")

        target_node = find_format_target(disk)
        run_command(["mkfs.ext4", "-F", target_node["path"]])
        filesystem_type = "ext4"
        ensure_mountpoint(mount_path)
        ensure_fstab_entry(target_node["path"], str(mount_path), filesystem_type)
        mount_target(target_node["path"], str(mount_path))
        payload = {
            "success": True,
            "mount_path": str(mount_path),
            "filesystem_type": filesystem_type,
            "message": "Disk formatted as ext4 and mounted under an application-managed path.",
        }
        print(json.dumps(payload))
        logger.info("Prepared disk %s in dedicated mode at %s", identifier, mount_path)
        return

    raise RuntimeError(f"Unsupported preparation mode: {mode}")


def discover_real_disks(settings: AgentSettings) -> list[dict[str, Any]]:
    mount_lookup = load_mount_lookup()
    lsblk_output = run_command(
        [
            "lsblk",
            "-J",
            "-b",
            "-o",
            "NAME,KNAME,PATH,TYPE,MODEL,SERIAL,SIZE,RM,ROTA,TRAN,MOUNTPOINT,FSTYPE,HOTPLUG,PKNAME",
        ]
    )
    payload = json.loads(lsblk_output)
    devices = payload.get("blockdevices", [])

    discovered: list[dict[str, Any]] = []
    for device in devices:
        if not is_candidate_disk(device):
            continue

        udev_props = load_udev_properties(device_name(device))
        serial_number = disk_serial_number(device, udev_props)
        if not serial_number:
            continue

        reason = get_exclusion_reason(device, udev_props)
        if reason is not None:
            logger.debug("Skipping %s: %s", device_name(device), reason)
            continue

        candidate = classify_candidate(device, udev_props, settings)
        if candidate is None:
            logger.debug("Skipping %s: not clearly external/removable", device_name(device))
            continue

        candidate_type, detection_reason = candidate
        disk_report = build_disk_report(
            device=normalize_lsblk_node(device),
            udev_props=udev_props,
            serial_number=serial_number,
            candidate_type=candidate_type,
            detection_reason=detection_reason,
            mount_lookup=mount_lookup,
        )
        if disk_report:
            discovered.append(disk_report)

    return deduplicate_disk_reports(discovered)


def is_candidate_disk(device: dict[str, Any]) -> bool:
    name = device_name(device)
    if device.get("type") != "disk":
        return False

    return not any(name.startswith(prefix) for prefix in EXCLUDED_DEVICE_PREFIXES)


def get_exclusion_reason(device: dict[str, Any], udev_props: dict[str, str]) -> str | None:
    partitions = flatten_partitions(device.get("children", []))
    filesystem_markers = {
        part.get("fstype")
        for part in [device, *partitions]
        if isinstance(part.get("fstype"), str)
    }
    mountpoints = {
        part.get("mountpoint")
        for part in [device, *partitions]
        if isinstance(part.get("mountpoint"), str) and part.get("mountpoint")
    }
    all_device_names = {device_name(device), *(device_name(part) for part in partitions)}

    if mountpoints & SYSTEM_MOUNTPOINTS:
        return "backs system mount"

    if filesystem_markers & SYSTEM_FS_MARKERS:
        return "belongs to lvm/zfs system storage"

    if any("rpool" in (udev_props.get(key, "").lower()) for key in udev_props):
        return "belongs to zfs root pool"

    if any("pve" in (mount or "").lower() for mount in mountpoints):
        return "used by proxmox storage mount"

    if any(name.startswith("zd") or name.startswith("dm-") for name in all_device_names):
        return "backs virtual or mapped storage"

    return None


def classify_candidate(
    device: dict[str, Any],
    udev_props: dict[str, str],
    settings: AgentSettings,
) -> tuple[str, str] | None:
    transport = (device.get("tran") or "").lower()
    removable = str(device.get("rm", "0")) == "1"
    hotplug = str(device.get("hotplug", "0")) == "1"
    udev_bus = udev_props.get("ID_BUS", "").lower()
    devpath = udev_props.get("DEVPATH", "").lower()
    usb_indicators = any(
        [
            transport == "usb",
            udev_bus == "usb",
            "usb" in devpath,
            "ID_USB_DRIVER" in udev_props,
            "ID_USB_MODEL" in udev_props,
        ]
    )

    if usb_indicators:
        return ("usb", "usb-connected disk")

    if removable or hotplug:
        return ("removable", "removable disk")

    if settings.include_non_usb_candidates:
        return ("standalone", "standalone non-system disk (advanced mode)")

    return None


def deduplicate_disk_reports(disks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduplicated: dict[str, dict[str, Any]] = {}
    for disk in disks:
        key = str(disk.get("serial_number") or disk.get("display_name"))
        existing = deduplicated.get(key)
        if existing is None or disk_priority(disk) > disk_priority(existing):
            deduplicated[key] = disk

    return list(deduplicated.values())


def disk_priority(disk: dict[str, Any]) -> int:
    candidate_type = str(disk.get("candidate_type") or "unknown")
    type_priority = {
        "usb": 4,
        "removable": 3,
        "standalone": 2,
        "unknown": 1,
    }.get(candidate_type, 0)
    mount_bonus = 1 if disk.get("mount_path") else 0
    return type_priority * 10 + mount_bonus


def resolve_disk(identifier: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    all_nodes = list_all_block_nodes()
    normalized = identifier.strip()
    for node in all_nodes:
        if node["type"] != "disk":
            continue

        if any(
            [
                node["path"] == normalized,
                node["name"] == normalized,
                node["kname"] == normalized,
                node["serial"] == normalized,
            ]
        ):
            return node, all_nodes

    raise FileNotFoundError(f"Unable to resolve disk from identifier: {identifier}")


def list_all_block_nodes() -> list[dict[str, Any]]:
    mount_lookup = load_mount_lookup()
    output = run_command(
        [
            "lsblk",
            "-J",
            "-o",
            "NAME,KNAME,PATH,TYPE,MODEL,SERIAL,SIZE,RM,TRAN,MOUNTPOINT,FSTYPE,PKNAME",
        ]
    )
    payload = json.loads(output)
    nodes: list[dict[str, Any]] = []
    for device in payload.get("blockdevices", []):
        normalized = normalize_lsblk_node(device, mount_lookup)
        nodes.append(normalized)
        nodes.extend(list_partition_nodes(normalized))
    return nodes


def normalize_lsblk_node(
    device: dict[str, Any],
    mount_lookup: dict[str, str] | None = None,
) -> dict[str, Any]:
    path = str(device.get("path") or f"/dev/{device.get('kname') or device.get('name') or ''}")
    return {
        "name": str(device.get("name") or ""),
        "kname": str(device.get("kname") or device.get("name") or ""),
        "path": path,
        "type": str(device.get("type") or ""),
        "model": first_value(device.get("model")),
        "serial": first_value(device.get("serial")),
        "size": device.get("size"),
        "rm": device.get("rm"),
        "tran": device.get("tran"),
        "mountpoint": first_value(device.get("mountpoint"), recover_mount_path(path, mount_lookup or {})),
        "fstype": device.get("fstype"),
        "pkname": device.get("pkname"),
        "children": [normalize_lsblk_node(child, mount_lookup) for child in device.get("children", [])],
    }


def list_partition_nodes(disk: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for child in disk.get("children", []):
        nodes.append(child)
        nodes.extend(list_partition_nodes(child))
    return nodes


def summarize_node(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": node["path"],
        "name": node["name"],
        "type": node["type"],
        "serial": node.get("serial"),
        "model": node.get("model"),
        "filesystem_type": node.get("fstype"),
        "mount_path": node.get("mountpoint"),
    }


def find_filesystem_node(disk: dict[str, Any]) -> dict[str, Any] | None:
    for node in list_partition_nodes(disk):
        if node.get("fstype"):
            return node

    if disk.get("fstype"):
        return disk

    return None


def find_format_target(disk: dict[str, Any]) -> dict[str, Any]:
    partitions = list_partition_nodes(disk)
    if partitions:
        return partitions[0]

    return disk


def get_blkid_info(path: str) -> dict[str, str]:
    try:
        output = run_command(["blkid", "-o", "export", path])
    except subprocess.CalledProcessError:
        return {}

    properties: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key] = value
    return properties


def default_mount_base_path(mount_base_path: str | None) -> Path:
    return Path(mount_base_path or "/mnt/pbo")


def ensure_mountpoint(path: Path) -> None:
    run_command(["mkdir", "-p", str(path)])


def ensure_fstab_entry(device_path: str, mount_path: str, filesystem_type: str) -> None:
    blkid_info = get_blkid_info(device_path)
    source = f"UUID={blkid_info['UUID']}" if "UUID" in blkid_info else device_path
    entry = f"{source} {mount_path} {filesystem_type} defaults,nofail 0 2"
    fstab_path = Path("/etc/fstab")
    current = fstab_path.read_text(encoding="utf-8") if fstab_path.exists() else ""
    if entry in current:
        return

    with fstab_path.open("a", encoding="utf-8") as handle:
        handle.write(entry + "\n")


def mount_target(device_path: str, mount_path: str) -> None:
    try:
        run_command(["mountpoint", "-q", mount_path])
        return
    except subprocess.CalledProcessError:
        pass

    run_command(["mount", device_path, mount_path])


def build_disk_report(
    device: dict[str, Any],
    udev_props: dict[str, str],
    serial_number: str,
    candidate_type: str,
    detection_reason: str,
    mount_lookup: dict[str, str],
) -> dict[str, Any] | None:
    partition_info = derive_partition_info(device, mount_lookup)
    model_name = first_value(device.get("model"), udev_props.get("ID_MODEL"))
    display_name = first_value(model_name, serial_number, device_name(device))
    capacity_gb = bytes_to_gb(device.get("size"))

    return {
        "serial_number": serial_number,
        "display_name": display_name,
        "model_name": model_name,
        "capacity_gb": capacity_gb,
        "filesystem_type": partition_info["filesystem_type"],
        "mount_path": partition_info["mount_path"],
        "detection_reason": detection_reason,
        "candidate_type": candidate_type,
        "trusted": False,
        "connected": True,
    }


def derive_partition_info(device: dict[str, Any], mount_lookup: dict[str, str]) -> dict[str, str | None]:
    partitions = flatten_partitions(device.get("children", []))
    for partition in partitions:
        filesystem_type = partition.get("fstype")
        mount_path = first_value(partition.get("mountpoint"), recover_mount_path(partition.get("path"), mount_lookup))
        if filesystem_type or mount_path:
            return {
                "filesystem_type": filesystem_type,
                "mount_path": mount_path,
            }

    return {
        "filesystem_type": device.get("fstype"),
        "mount_path": first_value(device.get("mountpoint"), recover_mount_path(device.get("path"), mount_lookup)),
    }


def flatten_partitions(children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for child in children:
        flattened.append(child)
        flattened.extend(flatten_partitions(child.get("children", [])))
    return flattened


def load_udev_properties(name: str) -> dict[str, str]:
    if not name:
        return {}

    try:
        output = run_command(["udevadm", "info", "--query=property", "--name", f"/dev/{name}"])
    except (FileNotFoundError, subprocess.CalledProcessError):
        return {}

    properties: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        properties[key] = value

    return properties


def load_mount_lookup() -> dict[str, str]:
    lookup: dict[str, str] = {}
    mounts_path = Path("/proc/mounts")
    if not mounts_path.exists():
        return lookup

    for line in mounts_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        source = _decode_mount_field(parts[0])
        mount_path = _decode_mount_field(parts[1])
        for candidate in _mount_lookup_keys(source):
            lookup[candidate] = mount_path
    return lookup


def recover_mount_path(device_path: Any, mount_lookup: dict[str, str]) -> str | None:
    if not isinstance(device_path, str) or not device_path:
        return None

    for candidate in _mount_lookup_keys(device_path):
        mount_path = mount_lookup.get(candidate)
        if mount_path:
            return mount_path
    return None


def _mount_lookup_keys(device_path: str) -> list[str]:
    candidates = [device_path]
    try:
        resolved = os.path.realpath(device_path)
    except OSError:
        resolved = device_path
    if resolved not in candidates:
        candidates.append(resolved)
    return candidates


def _decode_mount_field(value: str) -> str:
    return value.replace("\\040", " ").replace("\\011", "\t").replace("\\012", "\n").replace("\\134", "\\")


@dataclass(frozen=True)
class SubprocessResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


def parse_pbs_api_url(api_url: str) -> dict[str, Any]:
    parsed = urlparse(api_url)
    if not parsed.scheme or not parsed.hostname:
        raise RuntimeError(f"Invalid PBS_API_URL: {api_url}")

    if parsed.scheme != "https":
        raise RuntimeError("PBS_API_URL must use https for proxmox-backup-manager remote sync.")

    port = parsed.port or 8007
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": port,
    }


def _validate_external_target(mount: Path, target: Path, mode: str) -> None:
    try:
        target.relative_to(mount)
    except ValueError as exc:
        raise RuntimeError(
            f"Target path `{target}` must remain inside trusted mount path `{mount}`."
        ) from exc

    if mode == "coexistence" and target == mount:
        raise RuntimeError("Coexistence mode must not export at the raw disk root.")


def _ensure_directory_permissions(path: Path) -> None:
    current_mode = stat.S_IMODE(path.stat().st_mode)
    desired_mode = current_mode | stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
    desired_mode |= stat.S_IRGRP | stat.S_IXGRP
    if desired_mode != current_mode:
        path.chmod(desired_mode)


def parse_json_output(raw_output: str, context: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw_output or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Unable to parse JSON from `{context}` output: {exc}") from exc

    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected JSON payload from `{context}` output.")

    return [item for item in payload if isinstance(item, dict)]


def build_resource_name(prefix: str, seed: str) -> str:
    suffix = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{suffix}"


def find_datastore_by_path(datastores: list[dict[str, Any]], target: Path) -> str | None:
    target_str = str(target)
    for item in datastores:
        if str(item.get("path") or "") == target_str:
            name = item.get("name")
            if isinstance(name, str) and name:
                return name
    return None


def run_subprocess(command: list[str], timeout_seconds: float) -> SubprocessResult:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        missing = command[0] if command else "<unknown>"
        raise RuntimeError(f"Required command `{missing}` was not found in PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.strip() if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr.strip() if isinstance(exc.stderr, str) else ""
        details = [f"Command timed out after {timeout_seconds} seconds: {redact_command(command)}"]
        if stderr:
            details.append(f"stderr: {stderr[:500]}")
        if stdout:
            details.append(f"stdout: {stdout[:500]}")
        raise RuntimeError(" ".join(details)) from exc

    return SubprocessResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )


def record_command_result(
    result: SubprocessResult,
    command_summaries: list[str],
    stdout_logs: list[str],
    stderr_logs: list[str],
) -> None:
    command_summaries.append(redact_command(result.command))
    if result.stdout:
        stdout_logs.append(result.stdout)
    if result.stderr:
        stderr_logs.append(result.stderr)


def format_command_failure(prefix: str, result: SubprocessResult) -> str:
    details = [prefix, f"Command: {redact_command(result.command)}", f"exit={result.returncode}"]
    if result.stderr:
        details.append(f"stderr: {result.stderr[:500]}")
    if result.stdout:
        details.append(f"stdout: {result.stdout[:500]}")
    return " ".join(details)


def cleanup_resource(command: list[str], timeout_seconds: float) -> list[str]:
    result = run_subprocess(command, timeout_seconds)
    if result.returncode == 0:
        return []
    return [format_command_failure("Cleanup command failed.", result)]


def redact_command(command: list[str]) -> str:
    redacted: list[str] = []
    secret_flags = {"--password"}
    skip_next = False
    for index, part in enumerate(command):
        if skip_next:
            redacted.append("***")
            skip_next = False
            continue
        redacted.append(part)
        if part in secret_flags and index + 1 < len(command):
            skip_next = True
    return " ".join(redacted)


def run_command(command: list[str]) -> str:
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def mock_disks() -> list[dict[str, Any]]:
    return [
        {
            "serial_number": "AGENT-DISK-001",
            "display_name": "USB Backup Alpha",
            "model_name": "Samsung T7 Shield",
            "capacity_gb": 2000,
            "filesystem_type": "ext4",
            "mount_path": "/mnt/usb-backup-alpha",
            "detection_reason": "mock development candidate",
            "candidate_type": "usb",
            "trusted": False,
            "connected": True,
        },
        {
            "serial_number": "AGENT-DISK-002",
            "display_name": "Standalone Backup Beta",
            "model_name": "WD Red Plus",
            "capacity_gb": 4000,
            "filesystem_type": "xfs",
            "mount_path": "/mnt/backup-beta",
            "detection_reason": "mock standalone candidate",
            "candidate_type": "standalone",
            "trusted": False,
            "connected": True,
        },
    ]


def post_json(settings: AgentSettings, path: str, payload: dict[str, Any]) -> None:
    base_url = settings.api_base_url.rstrip("/")
    with httpx.Client(timeout=settings.timeout_seconds) as client:
        response = client.post(f"{base_url}{path}", json=payload)
        response.raise_for_status()


def current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def device_name(device: dict[str, Any]) -> str:
    return str(device.get("kname") or device.get("name") or "")


def disk_serial_number(device: dict[str, Any], udev_props: dict[str, str]) -> str | None:
    return first_value(
        device.get("serial"),
        udev_props.get("ID_SERIAL_SHORT"),
        udev_props.get("ID_SERIAL"),
    )


def first_value(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return stripped
    return None


def bytes_to_gb(raw_size: Any) -> int:
    try:
        size_bytes = int(raw_size)
    except (TypeError, ValueError):
        return 0

    if size_bytes <= 0:
        return 0

    return max(1, round(size_bytes / (1024**3)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal Proxmox host agent scaffold")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("heartbeat", help="Send a heartbeat to the backend")
    subparsers.add_parser("sync-state", help="Send heartbeat, then send a real disk report")
    subparsers.add_parser("report-disks", help="Discover backup candidate disks and send a disk report")
    subparsers.add_parser("report-mock-disks", help="Send a mock disk report for development")
    inspect_parser = subparsers.add_parser(
        "inspect-disk",
        help="Inspect a disk by serial or path and suggest an application mount path",
    )
    inspect_parser.add_argument("--disk", required=True)
    inspect_parser.add_argument("--mount-base-path")
    prepare_disk_parser = subparsers.add_parser(
        "prepare-disk",
        help="Prepare and mount a disk in preserve or dedicated mode",
    )
    prepare_disk_parser.add_argument("--disk", required=True)
    prepare_disk_parser.add_argument(
        "--mode",
        required=True,
        choices=["preserve_existing_data", "dedicated_backup"],
    )
    prepare_disk_parser.add_argument("--mount-base-path")
    prepare_disk_parser.add_argument("--confirm-destructive", action="store_true")
    prepare_parser = subparsers.add_parser(
        "prepare-external-datastore",
        help="Validate mount path and create the target export directory",
    )
    prepare_parser.add_argument("--mount-path", required=True)
    prepare_parser.add_argument("--target-path", required=True)
    prepare_parser.add_argument(
        "--mode",
        required=True,
        choices=["dedicated", "coexistence"],
    )
    export_parser = subparsers.add_parser(
        "run-external-export",
        help="Run a PBS-native-like external export boundary",
    )
    export_parser.add_argument("--target-path", required=True)
    export_parser.add_argument("--datastore-name", required=True)
    export_parser.add_argument(
        "--mode",
        required=True,
        choices=["dedicated", "coexistence"],
    )

    return parser


def emit_command_failure(command_name: str, exc: Exception) -> None:
    payload = {
        "ok": False,
        "message": str(exc),
        "command_summary": command_name,
        "execution_cwd": str(Path.cwd()),
        "stdout_log": None,
        "stderr_log": str(exc),
        "return_code": _infer_error_return_code(exc),
    }
    print(json.dumps(payload))
    logger.exception("Agent command %s failed", command_name)
    raise SystemExit(1) from exc


def _infer_error_return_code(exc: Exception) -> int:
    if isinstance(exc, subprocess.CalledProcessError):
        return exc.returncode
    return 1


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = AgentSettings()

    if args.command == "heartbeat":
        post_heartbeat(settings)
        return

    if args.command == "sync-state":
        sync_state(settings)
        return

    if args.command == "report-disks":
        post_real_disk_report(settings)
        return

    if args.command == "report-mock-disks":
        post_mock_disk_report(settings)
        return

    if args.command == "inspect-disk":
        inspect_disk(args.disk, args.mount_base_path)
        return

    if args.command == "prepare-disk":
        prepare_disk(args.disk, args.mode, args.mount_base_path, args.confirm_destructive)
        return

    if args.command == "prepare-external-datastore":
        try:
            prepare_external_datastore(args.mount_path, args.target_path, args.mode)
        except Exception as exc:
            emit_command_failure(args.command, exc)
        return

    if args.command == "run-external-export":
        try:
            run_external_export(args.target_path, args.datastore_name, args.mode, settings)
        except Exception as exc:
            emit_command_failure(args.command, exc)
        return

    parser.error("Unknown command")


if __name__ == "__main__":
    main()
