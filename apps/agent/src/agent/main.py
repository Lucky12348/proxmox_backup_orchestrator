import argparse
import binascii
import hashlib
import json
import logging
import os
import os.path
import shutil
import socket
import stat
import string
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
import uvicorn


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("agent")

EXCLUDED_DEVICE_PREFIXES = ("loop", "dm-", "zd", "sr")
SYSTEM_MOUNTPOINTS = {"/", "/boot", "/boot/efi"}
SYSTEM_FS_MARKERS = {"LVM2_member", "zfs_member"}
AGENT_PROTOCOL_VERSION = "2026-05-31"
AGENT_CAPABILITIES = {
    "version-endpoint",
    "inspect-disk-alias-resolution",
    "external-export-objects-status",
    "external-export-objects-cleanup",
    "dedicated-pbs-eject",
    "filesystem-usage",
    "qemu-usb-attach",
    "qemu-usb-detach",
}


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
    # Note: the agent talks to PBS via `proxmox-backup-manager` (trust is
    # established with `pbs_fingerprint` below), not a direct HTTPS client, so
    # there is no `verify=`-style TLS toggle to wire PBS_VERIFY_SSL into here.
    # apps/api/app/core/config.py has its own PBS_VERIFY_SSL-backed setting for
    # the API's own PBS REST client (apps/api/app/services/pbs_client.py).
    pbs_fingerprint: str | None = os.getenv("PBS_FINGERPRINT") or None
    export_timeout_seconds: float = float(os.getenv("AGENT_EXPORT_TIMEOUT_SECONDS", "7200"))
    datastore_create_timeout_seconds: float = float(
        os.getenv("AGENT_DATASTORE_CREATE_TIMEOUT_SECONDS", "14400")
    )
    loop_datastore_size_gb: int = int(os.getenv("AGENT_LOOP_DATASTORE_SIZE_GB", "500"))
    server_host: str = os.getenv("AGENT_SERVER_HOST", "0.0.0.0")
    server_port: int = int(os.getenv("AGENT_SERVER_PORT", "8081"))
    server_token: str = os.getenv("AGENT_SERVER_TOKEN", "")
    repo_path: str = os.getenv("AGENT_REPO_PATH", os.getcwd())
    maintenance_timeout_seconds: float = float(os.getenv("AGENT_MAINTENANCE_TIMEOUT_SECONDS", "120"))


class ExternalExportProgress:
    def __init__(
        self,
        settings: AgentSettings,
        run_id: int | None,
        callback_url: str | None = None,
        callback_token: str | None = None,
    ) -> None:
        self.settings = settings
        self.run_id = run_id
        self.callback_url = callback_url
        # Do not fall back to `settings.server_token`: that is this agent's own
        # inbound-API secret, and leaking it to an externally-supplied callback_url
        # would let a caller exfiltrate the master token. The API always supplies
        # its own callback_token explicitly for real progress callbacks.
        self.callback_token = callback_token

    def post(
        self,
        step: str,
        message: str,
        *,
        stdout_line: str | None = None,
        stderr_line: str | None = None,
        command: str | None = None,
    ) -> None:
        if self.run_id is None:
            return
        payload = {
            "step": step,
            "message": message,
            "stdout_line": stdout_line,
            "stderr_line": stderr_line,
            "command": command,
        }
        try:
            post_progress_callback(
                self.settings,
                self.callback_url,
                f"/external-backups/runs/{self.run_id}/log",
                {key: value for key, value in payload.items() if value is not None},
                token=self.callback_token,
            )
        except Exception as exc:
            logger.warning("Unable to post external export progress callback: %s", exc)

    @property
    def enabled(self) -> bool:
        return self.run_id is not None


def post_heartbeat(settings: AgentSettings) -> None:
    payload = {
        "hostname": settings.hostname,
        "agent_version": settings.agent_version,
        "observed_at": current_timestamp(),
    }
    post_json(settings, "/agent/heartbeat", payload, token=settings.server_token)
    logger.info("Heartbeat sent for host %s", settings.hostname)


def post_real_disk_report(settings: AgentSettings) -> None:
    disks = discover_real_disks(settings)
    payload = {
        "hostname": settings.hostname,
        "observed_at": current_timestamp(),
        "disks": disks,
    }
    post_json(settings, "/agent/disks/report", payload, token=settings.server_token)
    logger.info("Real disk report sent for host %s with %s disks", settings.hostname, len(disks))


def post_mock_disk_report(settings: AgentSettings) -> None:
    payload = {
        "hostname": settings.hostname,
        "observed_at": current_timestamp(),
        "disks": mock_disks(),
    }
    post_json(settings, "/agent/disks/report", payload, token=settings.server_token)
    logger.info("Mock disk report sent for host %s", settings.hostname)


def version_payload(settings: AgentSettings, routes: list[str] | None = None) -> dict[str, Any]:
    return {
        "ok": True,
        "component": "agent",
        "agent_version": settings.agent_version,
        "package_version": settings.agent_version,
        "git_sha": _git_sha(settings.repo_path),
        "started_at": None,
        "installed_path": str(Path(__file__).resolve()),
        "python_executable": sys_executable(),
        "protocol_version": AGENT_PROTOCOL_VERSION,
        "capabilities": sorted(AGENT_CAPABILITIES),
        "routes": sorted(routes or []),
        "message": "Agent version inspected.",
    }


def sync_state(settings: AgentSettings) -> None:
    post_heartbeat(settings)
    post_real_disk_report(settings)


def prepare_external_datastore_result(
    mount_path: str,
    target_path: str,
    mode: str,
    settings: AgentSettings | None = None,
    callback_run_id: int | None = None,
    callback_url: str | None = None,
    callback_token: str | None = None,
) -> dict[str, Any]:
    settings = settings or AgentSettings()
    progress = ExternalExportProgress(settings, callback_run_id, callback_url, callback_token)
    mount = Path(mount_path).resolve()
    requested_target = Path(target_path).resolve()
    _validate_external_target(mount, requested_target, mode)

    if not mount.is_dir():
        raise FileNotFoundError(f"Mount path does not exist: {mount_path}")

    filesystem_type = filesystem_type_for_path(mount)
    command_summaries: list[str] = []
    stdout_logs: list[str] = []
    stderr_logs: list[str] = []

    if mode == "coexistence" and _requires_loop_backed_datastore(filesystem_type):
        progress.post(
            "prepare_external_datastore",
            f"Preparing coexistence mode loop-backed ext4 datastore on filesystem `{filesystem_type or 'unknown'}`.",
        )
        serial = _extract_serial_from_external_target(mount, requested_target)
        image_dir = mount / "proxmox-backup-orchestrator" / serial / "images"
        image_path = image_dir / "pbs-export.ext4"
        loop_mount_path = mount / "proxmox-backup-orchestrator" / serial / "loop-pbs-datastore"

        image_dir.mkdir(parents=True, exist_ok=True)
        loop_mount_path.mkdir(parents=True, exist_ok=True)
        image_created = False
        image_needs_format = not image_path.exists() or image_path.stat().st_size == 0
        if image_needs_format:
            image_created = True
            progress.post(
                "loop_image",
                f"Creating loop-backed ext4 image `{image_path}` sized {settings.loop_datastore_size_gb} GiB.",
                command=redact_command(["truncate", "-s", f"{settings.loop_datastore_size_gb}G", str(image_path)]),
            )
            _run_logged_command(
                ["truncate", "-s", f"{settings.loop_datastore_size_gb}G", str(image_path)],
                command_summaries,
                stdout_logs,
                stderr_logs,
                f"Failed to create loop-backed datastore image `{image_path}`.",
                progress=progress,
                step="loop_image",
            )
            progress.post("loop_image", f"Loop-backed image `{image_path}` created.")
            progress.post("loop_image_format", f"Formatting loop-backed image `{image_path}` as ext4.")
            _run_logged_command(
                ["mkfs.ext4", "-F", str(image_path)],
                command_summaries,
                stdout_logs,
                stderr_logs,
                f"Failed to format new loop-backed datastore image `{image_path}` as ext4.",
                progress=progress,
                step="loop_image_format",
            )
            progress.post("loop_image_format", f"Loop-backed image `{image_path}` formatted.")
        else:
            progress.post("loop_image", f"Reusing existing loop-backed ext4 image `{image_path}`.")

        progress.post("loop_mount", f"Mounting or reusing loop-backed datastore mount `{loop_mount_path}`.")
        loop_mounted = _ensure_loop_image_mounted(
            image_path,
            loop_mount_path,
            command_summaries,
            stdout_logs,
            stderr_logs,
            progress=progress,
        )
        _run_logged_command(
            ["chown", "backup:backup", str(loop_mount_path)],
            command_summaries,
            stdout_logs,
            stderr_logs,
            f"Failed to chown loop-backed datastore mount `{loop_mount_path}`.",
        )
        _run_logged_command(
            ["chmod", "750", str(loop_mount_path)],
            command_summaries,
            stdout_logs,
            stderr_logs,
            f"Failed to chmod loop-backed datastore mount `{loop_mount_path}`.",
        )
        actual_target = loop_mount_path
        stdout_logs.append(
            f"Prepared loop-backed ext4 datastore at {actual_target} for requested target {requested_target}"
        )
        progress.post(
            "prepare_external_datastore",
            f"Loop-backed ext4 datastore target is ready at `{actual_target}`.",
        )
        logger.info("Prepared loop-backed external datastore target %s via image %s", actual_target, image_path)

        return {
            "ok": True,
            "success": True,
            "mount_path": str(mount),
            "target_path": str(actual_target),
            "requested_target_path": str(requested_target),
            "actual_target_path": str(actual_target),
            "loop_image_path": str(image_path),
            "loop_mount_path": str(loop_mount_path),
            "filesystem_type": filesystem_type,
            "loop_backed": True,
            "image_created": image_created,
            "loop_mounted": loop_mounted,
            "command_summary": "\n".join(command_summaries),
            "execution_cwd": str(Path.cwd()),
            "stdout_log": "\n\n".join(chunk for chunk in stdout_logs if chunk) or None,
            "stderr_log": "\n\n".join(chunk for chunk in stderr_logs if chunk) or None,
            "message": "Loop-backed ext4 datastore target is ready for external datastore export.",
            "return_code": 0,
        }

    progress.post("prepare_external_datastore", f"Preparing dedicated datastore target `{requested_target}`.")
    requested_target.mkdir(parents=True, exist_ok=True)
    _ensure_directory_permissions(requested_target)
    progress.post("prepare_external_datastore", f"Dedicated datastore target is ready at `{requested_target}`.")

    payload = {
        "ok": True,
        "success": True,
        "mount_path": str(mount),
        "target_path": str(requested_target),
        "requested_target_path": str(requested_target),
        "actual_target_path": str(requested_target),
        "loop_image_path": None,
        "loop_mount_path": None,
        "filesystem_type": filesystem_type,
        "loop_backed": False,
        "image_created": False,
        "loop_mounted": False,
        "command_summary": f"mkdir -p {requested_target} && chmod 750 {requested_target}",
        "execution_cwd": str(Path.cwd()),
        "stdout_log": f"Prepared target directory {requested_target}",
        "stderr_log": None,
        "message": "Target directory is ready for external datastore export.",
        "return_code": 0,
    }
    logger.info("Prepared external datastore target %s", requested_target)
    return payload


def prepare_dedicated_pbs_datastore_result(
    identifier: str,
    datastore_name: str,
    confirmation: bool,
    force_format: bool,
    settings: AgentSettings,
    preferred_mount_path: str | None = None,
    callback_run_id: int | None = None,
    callback_url: str | None = None,
    callback_token: str | None = None,
) -> dict[str, Any]:
    progress = ExternalExportProgress(settings, callback_run_id, callback_url, callback_token)

    disk, _ = resolve_disk(identifier)
    serial = disk_serial_number(disk, load_udev_properties(device_name(disk))) or device_name(disk)
    device_path = str(disk["path"])
    raw_size = disk.get("size")
    size_gb = bytes_to_gb(raw_size)
    if size_gb < 32:
        raise RuntimeError(
            f"Refusing to prepare `{device_path}`; raw size=`{raw_size}`, "
            f"parsed size=`{size_gb} GB`, minimum=`32 GB`."
        )
    _assert_safe_dedicated_disk(disk)

    mount_path = Path(preferred_mount_path).resolve(strict=False) if preferred_mount_path else default_mount_base_path(None) / serial / "pbs-datastore"
    _assert_safe_pbo_datastore_mount_path(mount_path, action="mount")
    partition_path = _first_partition_path(device_path)
    command_summaries: list[str] = []
    stdout_logs: list[str] = []
    stderr_logs: list[str] = []
    manager = shutil.which("proxmox-backup-manager")
    if manager is None:
        raise RuntimeError("Missing required host dependency: `proxmox-backup-manager` was not found in PATH.")

    existing_partition = _find_ext4_partition(disk)
    if existing_partition is not None:
        existing_partition_path = str(existing_partition["path"])
        ensure_mountpoint(mount_path)
        ensure_fstab_entry(existing_partition_path, str(mount_path), "ext4")
        if not _is_mounted_at(mount_path):
            _run_logged_command(
                ["mount", existing_partition_path, str(mount_path)],
                command_summaries,
                stdout_logs,
                stderr_logs,
                f"Failed to mount existing ext4 partition `{existing_partition_path}` at `{mount_path}`.",
                progress=progress,
                step="mount_datastore",
            )

        marker = _read_dedicated_datastore_marker(mount_path)
        existing_datastore = _find_pbs_datastore_name_for_path(manager, mount_path, settings)
        if marker is not None or existing_datastore == datastore_name:
            _ensure_dedicated_datastore_permissions(mount_path, command_summaries, stdout_logs, stderr_logs, progress)
            _ensure_pbs_datastore(manager, datastore_name, mount_path, settings, command_summaries, stdout_logs, stderr_logs, progress)
            _write_dedicated_datastore_marker(mount_path, serial, datastore_name, "ext4", existing_partition_path)
            progress.post(
                "prepare_dedicated_datastore",
                "Existing dedicated PBS datastore reused. No formatting performed.",
            )
            return _dedicated_datastore_payload(
                device_path=device_path,
                partition_path=existing_partition_path,
                mount_path=mount_path,
                datastore_name=datastore_name,
                command_summaries=command_summaries,
                stdout_logs=stdout_logs,
                stderr_logs=stderr_logs,
                message="Existing dedicated PBS datastore reused.",
            )

        if not force_format:
            raise RuntimeError(
                f"Refusing to format `{device_path}`. The disk has an ext4 partition mounted or mountable at "
                f"`{mount_path}`, but no PBO dedicated datastore marker was found. "
                "Use force_format=true only after verifying this disk can be erased."
            )

    if not confirmation:
        raise RuntimeError("Dedicated PBS datastore preparation requires destructive confirmation.")

    progress.post("destructive_format", f"Preparing `{device_path}` as dedicated PBS datastore `{datastore_name}`.")
    for partition in list_partition_nodes(disk):
        mountpoint = partition.get("mountpoint")
        if mountpoint:
            _run_logged_command(
                ["umount", str(partition["path"])],
                command_summaries,
                stdout_logs,
                stderr_logs,
                f"Failed to unmount `{partition['path']}`.",
                progress=progress,
                step="unmount",
            )

    _run_logged_command(
        ["wipefs", "--all", "--force", device_path],
        command_summaries,
        stdout_logs,
        stderr_logs,
        f"Failed to wipe filesystem signatures on `{device_path}`.",
        progress=progress,
        step="wipe_disk",
    )
    _run_logged_command(
        ["sgdisk", "--zap-all", device_path],
        command_summaries,
        stdout_logs,
        stderr_logs,
        f"Failed to wipe partition table on `{device_path}`.",
        progress=progress,
        step="wipe_partition_table",
    )
    _run_logged_command(
        ["parted", "-s", device_path, "mklabel", "gpt", "mkpart", "primary", "ext4", "0%", "100%"],
        command_summaries,
        stdout_logs,
        stderr_logs,
        f"Failed to create GPT partition on `{device_path}`.",
        progress=progress,
        step="partition_disk",
    )
    _run_logged_command(
        ["partprobe", device_path],
        command_summaries,
        stdout_logs,
        stderr_logs,
        f"Failed to refresh partition table for `{device_path}`.",
        progress=progress,
        step="partition_disk",
    )
    _run_logged_command(
        ["mkfs.ext4", "-F", partition_path],
        command_summaries,
        stdout_logs,
        stderr_logs,
        f"Failed to format `{partition_path}` as ext4.",
        progress=progress,
        step="format_ext4",
    )
    ensure_mountpoint(mount_path)
    ensure_fstab_entry(partition_path, str(mount_path), "ext4")
    _run_logged_command(
        ["mount", partition_path, str(mount_path)],
        command_summaries,
        stdout_logs,
        stderr_logs,
        f"Failed to mount `{partition_path}` at `{mount_path}`.",
        progress=progress,
        step="mount_datastore",
    )
    _ensure_dedicated_datastore_permissions(mount_path, command_summaries, stdout_logs, stderr_logs, progress)
    _ensure_pbs_datastore(manager, datastore_name, mount_path, settings, command_summaries, stdout_logs, stderr_logs, progress)
    _write_dedicated_datastore_marker(mount_path, serial, datastore_name, "ext4", partition_path)
    progress.post("prepare_dedicated_datastore", f"Dedicated PBS datastore mount is ready at `{mount_path}`.")

    return _dedicated_datastore_payload(
        device_path=device_path,
        partition_path=partition_path,
        mount_path=mount_path,
        datastore_name=datastore_name,
        command_summaries=command_summaries,
        stdout_logs=stdout_logs,
        stderr_logs=stderr_logs,
        message="Dedicated PBS datastore disk formatted and mounted.",
    )


def eject_dedicated_pbs_datastore_result(
    serial: str,
    datastore_name: str,
    mount_path: str,
    settings: AgentSettings | None = None,
) -> dict[str, Any]:
    settings = settings or AgentSettings()
    clean_serial = serial.strip()
    requested_mount = Path(mount_path)
    expected_mounts = _expected_pbo_datastore_mount_paths(clean_serial)
    resolved_mount = requested_mount.resolve(strict=False)
    command_summaries: list[str] = []
    stdout_logs: list[str] = []
    stderr_logs: list[str] = []

    if not clean_serial:
        raise RuntimeError("Dedicated datastore eject requires a disk serial number.")
    if resolved_mount not in {path.resolve(strict=False) for path in expected_mounts}:
        raise RuntimeError(
            "Refusing to eject "
            f"`{requested_mount}` because it is not an expected PBO path for disk serial `{clean_serial}`."
        )
    _assert_safe_pbo_datastore_mount_path(resolved_mount, action="unmount")

    manager = shutil.which("proxmox-backup-manager")
    if manager is None:
        raise RuntimeError("Missing required host dependency: `proxmox-backup-manager` was not found in PATH.")

    if _pbs_datastore_has_running_tasks(manager, datastore_name, settings, command_summaries, stdout_logs, stderr_logs):
        raise RuntimeError("A PBS task is currently running for this datastore.")
    if _pbo_export_sync_job_running(manager, settings, command_summaries, stdout_logs, stderr_logs):
        raise RuntimeError("A temporary PBO export sync job is currently running.")

    sync_result = run_subprocess(["sync"], timeout_seconds=60)
    record_command_result(sync_result, command_summaries, stdout_logs, stderr_logs)
    if sync_result.returncode != 0:
        raise RuntimeError(format_command_failure("Failed to sync filesystem buffers before eject.", sync_result))

    mounted_source = _find_mount_source(resolved_mount)
    if mounted_source:
        umount_result = run_subprocess(["umount", str(resolved_mount)], timeout_seconds=settings.export_timeout_seconds)
        record_command_result(umount_result, command_summaries, stdout_logs, stderr_logs)
        if umount_result.returncode != 0:
            if not _is_target_busy_umount_result(umount_result):
                raise RuntimeError(format_command_failure(f"Failed to unmount `{resolved_mount}`.", umount_result))
            _handle_busy_dedicated_datastore_unmount(
                resolved_mount,
                manager,
                datastore_name,
                settings,
                umount_result,
                command_summaries,
                stdout_logs,
                stderr_logs,
            )

    if _find_mount_source(resolved_mount):
        raise RuntimeError(f"Refusing to eject because `{resolved_mount}` is still mounted.")

    return {
        "ok": True,
        "success": True,
        "message": "External datastore unmounted safely. Disk can be detached.",
        "serial": clean_serial,
        "datastore_name": datastore_name,
        "mount_path": str(resolved_mount),
        "command_summary": "\n".join(command_summaries),
        "stdout_log": "\n".join(stdout_logs),
        "stderr_log": "\n".join(stderr_logs),
        "execution_cwd": str(Path.cwd()),
        "return_code": 0,
    }


def qemu_usb_attach_result(vmid: int, slot: str, host: str, usb3: bool | None = None) -> dict[str, Any]:
    _validate_qemu_usb_request(vmid, slot, host)
    value = f"host={host}" + (f",usb3={1 if usb3 else 0}" if usb3 is not None else "")
    command = ["qm", "set", str(vmid), f"-{slot}", value]
    result = run_subprocess(command, timeout_seconds=60)
    if result.returncode != 0:
        raise RuntimeError(format_command_failure("Failed to attach QEMU USB passthrough.", result))
    return {
        "ok": True,
        "success": True,
        "message": "QEMU USB passthrough attached.",
        "command_summary": redact_command(command),
        "stdout_log": result.stdout,
        "stderr_log": result.stderr,
        "execution_cwd": str(Path.cwd()),
        "return_code": result.returncode,
        "vmid": vmid,
        "slot": slot,
        "host": host,
        "usb3": usb3,
    }


def qemu_usb_detach_result(vmid: int, slot: str) -> dict[str, Any]:
    _validate_qemu_usb_request(vmid, slot, "placeholder")
    command = ["qm", "set", str(vmid), "-delete", slot]
    result = run_subprocess(command, timeout_seconds=60)
    if result.returncode != 0:
        raise RuntimeError(format_command_failure("Failed to detach QEMU USB passthrough.", result))
    return {
        "ok": True,
        "success": True,
        "message": "QEMU USB passthrough detached.",
        "command_summary": redact_command(command),
        "stdout_log": result.stdout,
        "stderr_log": result.stderr,
        "execution_cwd": str(Path.cwd()),
        "return_code": result.returncode,
        "vmid": vmid,
        "slot": slot,
    }


def qemu_config_result(vmid: int) -> dict[str, Any]:
    if vmid <= 0:
        raise RuntimeError("VMID must be positive.")
    command = ["qm", "config", str(vmid)]
    result = run_subprocess(command, timeout_seconds=30)
    if result.returncode != 0:
        raise RuntimeError(format_command_failure("Failed to read QEMU VM config.", result))
    return {
        "ok": True,
        "success": True,
        "message": "QEMU VM config read.",
        "command_summary": redact_command(command),
        "stdout_log": result.stdout,
        "stderr_log": result.stderr,
        "execution_cwd": str(Path.cwd()),
        "return_code": result.returncode,
        "vmid": vmid,
        "config": result.stdout,
    }


def _validate_qemu_usb_request(vmid: int, slot: str, host: str) -> None:
    if vmid <= 0:
        raise RuntimeError("VMID must be positive.")
    if not slot.startswith("usb") or not slot[3:].isdigit():
        raise RuntimeError(f"Invalid QEMU USB slot `{slot}`.")
    if not host.strip():
        raise RuntimeError("QEMU USB host mapping is required.")


def _dedicated_datastore_payload(
    *,
    device_path: str,
    partition_path: str,
    mount_path: Path,
    datastore_name: str,
    command_summaries: list[str],
    stdout_logs: list[str],
    stderr_logs: list[str],
    message: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "success": True,
        "device_path": device_path,
        "partition_path": partition_path,
        "mount_path": str(mount_path),
        "target_path": str(mount_path),
        "actual_target_path": str(mount_path),
        "filesystem_type": "ext4",
        "datastore_name": datastore_name,
        "command_summary": "\n".join(command_summaries),
        "execution_cwd": str(Path.cwd()),
        "stdout_log": "\n\n".join(chunk for chunk in stdout_logs if chunk) or None,
        "stderr_log": "\n\n".join(chunk for chunk in stderr_logs if chunk) or None,
        "message": message,
        "return_code": 0,
    }


def run_external_export_result(
    target_path: str,
    datastore_name: str,
    mode: str,
    settings: AgentSettings,
    callback_run_id: int | None = None,
    callback_url: str | None = None,
    callback_token: str | None = None,
    target_datastore_name: str | None = None,
    persist_target_datastore: bool = False,
) -> dict[str, Any]:
    progress = ExternalExportProgress(settings, callback_run_id, callback_url, callback_token)
    target = Path(target_path).resolve()
    progress.post("prepare_external_datastore", f"Validating target path `{target}`.")
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
    progress.post("inspect_datastores", "Inspecting PBS source datastores.")
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
    target_store_name = existing_target_store or target_datastore_name or build_resource_name("pbo-export-store", str(target))
    run_suffix = str(callback_run_id or int(datetime.now(timezone.utc).timestamp() * 1000))
    remote_name = build_resource_name("pbo-export-remote", f"{api['host']}:{datastore_name}:{target}:{run_suffix}")
    sync_job_name = build_resource_name("pbo-export-sync", f"{datastore_name}:{target}:{run_suffix}")

    command_summaries: list[str] = []
    stdout_logs: list[str] = []
    stderr_logs: list[str] = []
    cleanup_errors: list[str] = []
    sync_completed = False
    created_temp_datastore = False
    created_remote = False
    created_sync_job = False
    target_was_initialized = is_initialized_pbs_datastore_path(target)
    datastore_create_timeout = max(
        settings.export_timeout_seconds,
        settings.datastore_create_timeout_seconds,
    )
    target_filesystem_type = filesystem_type_for_path(target)

    try:
        _cleanup_stale_export_sync_objects(
            manager,
            settings,
            command_summaries,
            stdout_logs,
            stderr_logs,
            progress,
        )

        if created_datastore:
            progress.post("target_datastore", f"Creating or reusing target PBS datastore `{target_store_name}`.")
            create_store_command = [
                manager,
                "datastore",
                "create",
                target_store_name,
                str(target),
            ]
            create_context = "existing initialized PBS datastore path"
            if target_was_initialized:
                create_store_command.extend(["--reuse-datastore", "true"])
            else:
                create_context = "new datastore initialization"

            detection_message = (
                f"Target datastore path `{target}` detected as "
                f"{'initialized' if target_was_initialized else 'new/uninitialized'}; "
                f"filesystem={target_filesystem_type or 'unknown'}; "
                f"create_timeout_seconds={datastore_create_timeout}; "
                f"command={redact_command(create_store_command)}"
            )
            stdout_logs.append(detection_message)
            logger.info(detection_message)

            try:
                if progress.enabled:
                    create_store_result = run_subprocess_streaming(
                        create_store_command,
                        timeout_seconds=datastore_create_timeout,
                        on_stdout=lambda line: progress.post("target_datastore_stdout", line, stdout_line=line),
                        on_stderr=lambda line: progress.post("target_datastore_stderr", line, stderr_line=line),
                    )
                else:
                    create_store_result = run_subprocess(
                        create_store_command,
                        timeout_seconds=datastore_create_timeout,
                    )
                progress.post(
                    "target_datastore",
                    f"Target PBS datastore command finished with exit {create_store_result.returncode}.",
                    command=redact_command(create_store_command),
                )
            except RuntimeError as exc:
                raise RuntimeError(
                    f"Failed to create target datastore `{target_store_name}` "
                    f"for {create_context}; filesystem={target_filesystem_type or 'unknown'}; "
                    f"timeout_seconds={datastore_create_timeout}; "
                    f"command={redact_command(create_store_command)}. {exc}"
                ) from exc
            record_command_result(create_store_result, command_summaries, stdout_logs, stderr_logs)
            if create_store_result.returncode != 0:
                raise RuntimeError(
                    format_command_failure(
                        (
                            f"Failed to create target datastore `{target_store_name}` "
                            f"for {create_context}; filesystem="
                            f"{target_filesystem_type or 'unknown'}."
                        ),
                        create_store_result,
                    )
                )
            created_temp_datastore = True
        else:
            progress.post("target_datastore", f"Reusing target PBS datastore `{target_store_name}`.")

        progress.post("remote", f"Creating temporary PBS remote `{remote_name}`.")
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

        progress.post("sync_job", f"Creating temporary PBS sync job `{sync_job_name}`.")
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

        progress.post(
            "sync_run",
            f"Starting PBS sync job `{sync_job_name}` from `{datastore_name}` to `{target_store_name}`.",
            command=redact_command([manager, "sync-job", "run", sync_job_name]),
        )
        sync_run_command = [manager, "sync-job", "run", sync_job_name]
        if progress.enabled:
            sync_run_result = run_subprocess_streaming(
                sync_run_command,
                timeout_seconds=settings.export_timeout_seconds,
                on_stdout=lambda line: progress.post("sync_stdout", line, stdout_line=line),
                on_stderr=lambda line: progress.post("sync_stderr", line, stderr_line=line),
            )
        else:
            sync_run_result = run_subprocess(
                sync_run_command,
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
        progress.post("sync_run", f"PBS sync job `{sync_job_name}` finished.")
    finally:
        if created_sync_job:
            progress.post("cleanup", f"Removing temporary PBS sync job `{sync_job_name}`.")
            cleanup_errors.extend(
                cleanup_resource([manager, "sync-job", "remove", sync_job_name], settings.export_timeout_seconds)
            )
        if created_remote:
            progress.post("cleanup", f"Removing temporary PBS remote `{remote_name}`.")
            cleanup_errors.extend(
                cleanup_resource([manager, "remote", "remove", remote_name], settings.export_timeout_seconds)
            )
        if created_temp_datastore and not persist_target_datastore:
            progress.post("cleanup", f"Removing temporary target PBS datastore `{target_store_name}`.")
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
    progress.post("success" if sync_completed else "failure", message)

    payload = {
        "ok": sync_completed,
        "success": sync_completed,
        "target_path": str(target),
        "datastore_name": datastore_name,
        "mode": mode,
        "pbs_sync_job_id": sync_job_name,
        "pbs_remote_id": remote_name,
        "command_summary": "\n".join(command_summaries),
        "execution_cwd": str(Path.cwd()),
        "stdout_log": "\n\n".join(chunk for chunk in stdout_logs if chunk) or None,
        "stderr_log": "\n\n".join(chunk for chunk in stderr_logs if chunk) or None,
        "message": message,
        "return_code": 0 if sync_completed else 1,
    }
    logger.info("External export finished for datastore %s into %s", datastore_name, target)
    return payload


def inspect_disk_result(identifier: str, mount_base_path: str | None = None) -> dict[str, Any]:
    disk, _ = resolve_disk(identifier)
    serial = disk_serial_number(disk, load_udev_properties(device_name(disk))) or device_name(disk)
    filesystem_node = find_filesystem_node(disk)
    blkid_info = get_blkid_info(filesystem_node["path"]) if filesystem_node else {}
    filesystem_type = None
    if filesystem_node is not None:
        filesystem_type = blkid_info.get("TYPE") or filesystem_node.get("fstype")
    filesystem_usage = filesystem_usage_for_mount_path(filesystem_node["mountpoint"] if filesystem_node else None)
    candidate_mount_path = str(default_mount_base_path(mount_base_path) / serial)
    payload = {
        "success": True,
        "disk": summarize_node(disk),
        "filesystem_info": {
            "device_path": filesystem_node["path"] if filesystem_node else None,
            "filesystem_type": filesystem_type,
            "uuid": blkid_info.get("UUID"),
            "mount_path": filesystem_node["mountpoint"] if filesystem_node else None,
            "filesystem_total_gb": filesystem_usage["total_gb"],
            "filesystem_used_gb": filesystem_usage["used_gb"],
            "filesystem_free_gb": filesystem_usage["free_gb"],
        },
        "partition_info": [summarize_node(node) for node in list_partition_nodes(disk)],
        "candidate_mount_path": candidate_mount_path,
        "message": "Disk inspection completed.",
    }
    logger.info("Inspected disk %s", identifier)
    return payload


def prepare_disk_result(
    identifier: str,
    mode: str,
    mount_base_path: str | None,
    confirm_destructive: bool,
) -> dict[str, Any]:
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
            "ok": True,
            "success": True,
            "mount_path": str(mount_path),
            "filesystem_type": filesystem_type,
            "message": "Existing filesystem mounted under an application-managed path.",
            "command_summary": f"mount {filesystem_node['path']} {mount_path}",
            "execution_cwd": str(Path.cwd()),
            "stdout_log": f"Mounted existing filesystem at {mount_path}",
            "stderr_log": None,
            "return_code": 0,
        }
        logger.info("Prepared disk %s in preserve mode at %s", identifier, mount_path)
        return payload

    if mode == "dedicated_backup":
        if not confirm_destructive:
            raise RuntimeError("Dedicated backup mode requires destructive confirmation.")

        _assert_safe_dedicated_disk(disk)
        target_node = find_format_target(disk)
        run_command(["mkfs.ext4", "-F", target_node["path"]])
        filesystem_type = "ext4"
        ensure_mountpoint(mount_path)
        ensure_fstab_entry(target_node["path"], str(mount_path), filesystem_type)
        mount_target(target_node["path"], str(mount_path))
        payload = {
            "ok": True,
            "success": True,
            "mount_path": str(mount_path),
            "filesystem_type": filesystem_type,
            "message": "Disk formatted as ext4 and mounted under an application-managed path.",
            "command_summary": f"mkfs.ext4 -F {target_node['path']} && mount {target_node['path']} {mount_path}",
            "execution_cwd": str(Path.cwd()),
            "stdout_log": f"Formatted {target_node['path']} as ext4 and mounted it at {mount_path}",
            "stderr_log": None,
            "return_code": 0,
        }
        logger.info("Prepared disk %s in dedicated mode at %s", identifier, mount_path)
        return payload

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
    identifier_aliases = set(serial_aliases(normalized))
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
        if identifier_aliases and identifier_aliases & set(disk_identifier_aliases(node)):
            return node, all_nodes

    raise FileNotFoundError(f"Unable to resolve disk from identifier: {identifier}")


def disk_identifier_aliases(node: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    raw_values: list[str | None] = [
        str(node.get("serial") or "") or None,
        str(node.get("model") or "") or None,
    ]
    udev_props = load_udev_properties(device_name(node))
    raw_values.extend(
        [
            udev_props.get("ID_SERIAL"),
            udev_props.get("ID_SERIAL_SHORT"),
            udev_props.get("ID_WWN"),
            udev_props.get("ID_MODEL"),
            udev_props.get("ID_VENDOR"),
            " ".join(
                value
                for value in [udev_props.get("ID_VENDOR"), udev_props.get("ID_MODEL")]
                if value
            )
            or None,
        ]
    )
    for raw_value in raw_values:
        for alias in serial_aliases(raw_value):
            if alias and alias not in aliases:
                aliases.append(alias)
    return aliases


def list_all_block_nodes() -> list[dict[str, Any]]:
    mount_lookup = load_mount_lookup()
    output = run_command(
        [
            "lsblk",
            "-J",
            "-b",
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


def _first_partition_path(device_path: str) -> str:
    if device_path.startswith("/dev/nvme") or device_path.startswith("/dev/mmcblk"):
        return f"{device_path}p1"
    return f"{device_path}1"


def _assert_safe_dedicated_disk(disk: dict[str, Any]) -> None:
    nodes = [disk, *list_partition_nodes(disk)]
    dangerous_mounts = {"/", "/boot", "/boot/efi", "/mnt/datastore/backup-store"}
    for node in nodes:
        mountpoint = node.get("mountpoint")
        if isinstance(mountpoint, str) and mountpoint:
            if mountpoint in dangerous_mounts or mountpoint.startswith("/mnt/datastore/backup-store/"):
                raise RuntimeError(f"Refusing to format disk because `{node['path']}` is mounted at `{mountpoint}`.")
    datastore_path = Path("/mnt/datastore/backup-store")
    for node in nodes:
        mountpoint = node.get("mountpoint")
        if isinstance(mountpoint, str) and mountpoint:
            try:
                datastore_path.relative_to(Path(mountpoint))
            except ValueError:
                continue
            raise RuntimeError(f"Refusing to format disk because it contains source datastore `{datastore_path}`.")

    # The explicit mountpoint checks above miss the common Proxmox case where the
    # system/root disk is an LVM (or ZFS) member: its physical partition has no
    # mountpoint of its own (the logical volume is what's mounted), so it would
    # otherwise sail through. Reuse the same exclusion logic used to keep such
    # disks out of the discovery/report listing (see discover_real_disks) so a
    # bad or manipulated disk identifier can't reach wipefs/sgdisk/mkfs here.
    reason = get_exclusion_reason(disk, load_udev_properties(device_name(disk)))
    if reason is not None:
        raise RuntimeError(f"Refusing to format disk `{disk['path']}`: it {reason}.")


def _find_ext4_partition(disk: dict[str, Any]) -> dict[str, Any] | None:
    for partition in list_partition_nodes(disk):
        filesystem_type = partition.get("fstype") or get_blkid_info(str(partition["path"])).get("TYPE")
        if isinstance(filesystem_type, str) and filesystem_type.lower() == "ext4":
            return partition
    return None


def _is_mounted_at(path: Path) -> bool:
    try:
        run_command(["mountpoint", "-q", str(path)])
        return True
    except (RuntimeError, subprocess.CalledProcessError):
        return False


def _read_dedicated_datastore_marker(mount_path: Path) -> dict[str, Any] | None:
    marker_path = _dedicated_datastore_marker_path(mount_path)
    if not marker_path.exists():
        return None
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_dedicated_datastore_marker(
    mount_path: Path,
    serial: str,
    datastore_name: str,
    filesystem_type: str,
    partition_path: str,
) -> None:
    marker = {
        "serial": serial,
        "datastore_name": datastore_name,
        "created_at": current_timestamp(),
        "app_name": "proxmox_backup_orchestrator",
        "filesystem_type": filesystem_type,
        "partition_path": partition_path,
    }
    _dedicated_datastore_marker_path(mount_path).write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _dedicated_datastore_marker_path(mount_path: Path) -> Path:
    return mount_path / ".pbo-dedicated-datastore.json"


def _find_pbs_datastore_name_for_path(
    manager: str,
    datastore_path: Path,
    settings: AgentSettings,
) -> str | None:
    result = run_subprocess([manager, "datastore", "list", "--output-format", "json"], settings.export_timeout_seconds)
    if result.returncode != 0:
        raise RuntimeError(format_command_failure("Unable to inspect PBS datastores.", result))
    return find_datastore_by_path(parse_json_output(result.stdout, "datastore list"), datastore_path)


def _ensure_pbs_datastore(
    manager: str,
    datastore_name: str,
    datastore_path: Path,
    settings: AgentSettings,
    command_summaries: list[str],
    stdout_logs: list[str],
    stderr_logs: list[str],
    progress: ExternalExportProgress | None,
) -> None:
    existing_name = _find_pbs_datastore_name_for_path(manager, datastore_path, settings)
    if existing_name == datastore_name:
        stdout_logs.append(f"Reusing existing PBS datastore `{datastore_name}` at {datastore_path}")
        return
    if existing_name and existing_name != datastore_name:
        raise RuntimeError(
            f"Datastore path `{datastore_path}` is already registered as `{existing_name}`, not `{datastore_name}`."
        )
    _run_logged_command(
        [manager, "datastore", "create", datastore_name, str(datastore_path), "--reuse-datastore", "true"],
        command_summaries,
        stdout_logs,
        stderr_logs,
        f"Failed to create/reuse PBS datastore `{datastore_name}` at `{datastore_path}`.",
        timeout_seconds=max(settings.export_timeout_seconds, settings.datastore_create_timeout_seconds),
        progress=progress,
        step="target_datastore",
    )


def _ensure_dedicated_datastore_permissions(
    mount_path: Path,
    command_summaries: list[str],
    stdout_logs: list[str],
    stderr_logs: list[str],
    progress: ExternalExportProgress | None,
) -> None:
    _run_logged_command(
        ["chown", "backup:backup", str(mount_path)],
        command_summaries,
        stdout_logs,
        stderr_logs,
        f"Failed to chown `{mount_path}`.",
        progress=progress,
        step="permissions",
    )
    _run_logged_command(
        ["chmod", "750", str(mount_path)],
        command_summaries,
        stdout_logs,
        stderr_logs,
        f"Failed to chmod `{mount_path}`.",
        progress=progress,
        step="permissions",
    )


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
    filesystem_usage = filesystem_usage_for_mount_path(partition_info["mount_path"])

    return {
        "serial_number": serial_number,
        "display_name": display_name,
        "model_name": model_name,
        "capacity_gb": capacity_gb,
        "filesystem_total_gb": filesystem_usage["total_gb"],
        "filesystem_used_gb": filesystem_usage["used_gb"],
        "filesystem_free_gb": filesystem_usage["free_gb"],
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


def filesystem_usage_for_mount_path(mount_path: str | None) -> dict[str, int | None]:
    if not mount_path:
        return {"total_gb": None, "used_gb": None, "free_gb": None}

    try:
        if not os.path.ismount(mount_path):
            return {"total_gb": None, "used_gb": None, "free_gb": None}
        stats = os.statvfs(mount_path)
    except (FileNotFoundError, NotADirectoryError, OSError):
        return {"total_gb": None, "used_gb": None, "free_gb": None}

    fragment_size = stats.f_frsize or stats.f_bsize
    total_bytes = stats.f_blocks * fragment_size
    free_bytes = stats.f_bavail * fragment_size
    used_bytes = max(0, total_bytes - free_bytes)
    return {
        "total_gb": bytes_to_gb(total_bytes),
        "used_gb": bytes_to_gb(used_bytes),
        "free_gb": bytes_to_gb(free_bytes),
    }


def filesystem_usage_result(mount_path: str) -> dict[str, Any]:
    resolved_mount = Path(mount_path).resolve(strict=False)
    _assert_safe_filesystem_usage_mount_path(resolved_mount)
    usage = filesystem_usage_for_mount_path(str(resolved_mount))
    return {
        "ok": True,
        "success": True,
        "mount_path": str(resolved_mount),
        "filesystem_total_gb": usage["total_gb"],
        "filesystem_used_gb": usage["used_gb"],
        "filesystem_free_gb": usage["free_gb"],
        "message": "Filesystem usage inspected.",
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


def _requires_loop_backed_datastore(filesystem_type: str | None) -> bool:
    if filesystem_type is None:
        return True
    return filesystem_type.strip().lower() not in {"ext4", "xfs"}


def _extract_serial_from_external_target(mount: Path, target: Path) -> str:
    try:
        relative_parts = target.relative_to(mount).parts
    except ValueError as exc:
        raise RuntimeError(f"Target path `{target}` must remain inside mount path `{mount}`.") from exc

    if len(relative_parts) >= 3 and relative_parts[0] == "proxmox-backup-orchestrator":
        serial = relative_parts[1].strip()
        if serial:
            return serial

    raise RuntimeError(
        "Unable to derive disk serial from external target path. Expected "
        "`<mount>/proxmox-backup-orchestrator/<serial>/pbs-datastore`."
    )


def _ensure_loop_image_mounted(
    image_path: Path,
    loop_mount_path: Path,
    command_summaries: list[str],
    stdout_logs: list[str],
    stderr_logs: list[str],
    progress: ExternalExportProgress | None = None,
) -> bool:
    mounted_source = _find_mount_source(loop_mount_path)
    if mounted_source:
        resolved_backing_file = loop_backing_file(mounted_source)
        stdout_logs.append(
            f"Existing loop datastore mount source for {loop_mount_path}: {mounted_source}; "
            f"resolved_backing_file={resolved_backing_file or 'none'}"
        )
        logger.info(
            "Existing loop datastore mount source for %s: %s; resolved_backing_file=%s",
            loop_mount_path,
            mounted_source,
            resolved_backing_file,
        )

        if _same_path(mounted_source, image_path) or (
            resolved_backing_file is not None and _same_path(resolved_backing_file, image_path)
        ):
            stdout_logs.append(f"Reusing existing loop-backed datastore mount at {loop_mount_path}")
            if progress is not None:
                progress.post("loop_mount", f"Reusing existing loop-backed datastore mount at `{loop_mount_path}`.")
            logger.info("Reusing existing loop-backed datastore mount at %s", loop_mount_path)
            return True
        raise RuntimeError(
            f"Loop datastore mount point `{loop_mount_path}` is already mounted from "
            f"`{mounted_source}`"
            + (f" backed by `{resolved_backing_file}`" if resolved_backing_file else "")
            + f", not `{image_path}`."
        )

    _run_logged_command(
        ["mount", "-o", "loop", str(image_path), str(loop_mount_path)],
        command_summaries,
        stdout_logs,
        stderr_logs,
        f"Failed to mount loop-backed datastore image `{image_path}` at `{loop_mount_path}`.",
        progress=progress,
        step="loop_mount",
    )
    if progress is not None:
        progress.post("loop_mount", f"Loop-backed datastore image mounted at `{loop_mount_path}`.")
    return True


def _find_mount_source(path: Path) -> str | None:
    findmnt = shutil.which("findmnt")
    if not findmnt:
        return None
    try:
        output = run_command([findmnt, "-no", "SOURCE", "--mountpoint", str(path)]).strip()
    except (RuntimeError, subprocess.CalledProcessError):
        return None
    for line in output.splitlines():
        source = line.strip()
        if source:
            return source
    return None


def loop_backing_file(loop_source: str) -> Path | None:
    source_path = Path(loop_source)
    if not source_path.name.startswith("loop") and not loop_source.startswith("/dev/loop"):
        return None

    losetup = shutil.which("losetup")
    if not losetup:
        return None
    commands = (
        [losetup, "--noheadings", "--output", "BACK-FILE", loop_source],
        [losetup, "-n", "-O", "BACK-FILE", loop_source],
    )
    for command in commands:
        try:
            output = run_command(command)
        except (RuntimeError, subprocess.CalledProcessError):
            continue
        backing_file = _first_non_empty_line(output)
        if backing_file:
            return _resolve_path_best_effort(backing_file)
    return None


def _first_non_empty_line(value: str) -> str | None:
    for line in value.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _resolve_path_best_effort(value: str | Path) -> Path:
    path = Path(value)
    try:
        return path.resolve()
    except OSError:
        return Path(os.path.realpath(str(path)))


def _same_path(left: str | Path, right: str | Path) -> bool:
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return os.path.realpath(str(left)) == os.path.realpath(str(right))


def _run_logged_command(
    command: list[str],
    command_summaries: list[str],
    stdout_logs: list[str],
    stderr_logs: list[str],
    failure_prefix: str,
    timeout_seconds: float = 7200,
    progress: ExternalExportProgress | None = None,
    step: str | None = None,
) -> SubprocessResult:
    try:
        command_text = redact_command(command)
        if progress is not None and progress.enabled:
            progress.post(step or "command", f"Starting `{command_text}`.", command=command_text)
            result = run_subprocess_streaming(
                command,
                timeout_seconds=timeout_seconds,
                on_stdout=lambda line: progress.post(step or "command_stdout", line, stdout_line=line, command=command_text),
                on_stderr=lambda line: progress.post(step or "command_stderr", line, stderr_line=line, command=command_text),
            )
            progress.post(step or "command", f"Finished `{command_text}` with exit {result.returncode}.", command=command_text)
        else:
            result = run_subprocess(command, timeout_seconds=timeout_seconds)
    except RuntimeError as exc:
        raise RuntimeError(f"{failure_prefix} {exc}") from exc
    record_command_result(result, command_summaries, stdout_logs, stderr_logs)
    if result.returncode != 0:
        raise RuntimeError(format_command_failure(failure_prefix, result))
    return result


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


def is_initialized_pbs_datastore_path(path: Path) -> bool:
    chunks = path / ".chunks"
    return chunks.is_dir()


def filesystem_type_for_path(path: Path) -> str | None:
    findmnt = shutil.which("findmnt")
    if findmnt:
        try:
            return run_command([findmnt, "-no", "FSTYPE", "--target", str(path)]).strip() or None
        except (RuntimeError, subprocess.CalledProcessError):
            pass

    lsblk = shutil.which("lsblk")
    if lsblk:
        try:
            return run_command([lsblk, "-no", "FSTYPE", str(path)]).strip() or None
        except (RuntimeError, subprocess.CalledProcessError):
            pass

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


def run_subprocess_with_cwd(command: list[str], cwd: Path, timeout_seconds: float) -> SubprocessResult:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
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


def run_subprocess_streaming(
    command: list[str],
    timeout_seconds: float,
    *,
    on_stdout: Callable[[str], None] | None = None,
    on_stderr: Callable[[str], None] | None = None,
) -> SubprocessResult:
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        missing = command[0] if command else "<unknown>"
        raise RuntimeError(f"Required command `{missing}` was not found in PATH.") from exc

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def read_stream(stream, lines: list[str], callback: Callable[[str], None] | None) -> None:
        if stream is None:
            return
        for raw_line in iter(stream.readline, ""):
            line = raw_line.rstrip("\n")
            if line:
                lines.append(line)
                if callback is not None:
                    callback(line)
        stream.close()

    stdout_thread = threading.Thread(target=read_stream, args=(process.stdout, stdout_lines, on_stdout), daemon=True)
    stderr_thread = threading.Thread(target=read_stream, args=(process.stderr, stderr_lines, on_stderr), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    try:
        return_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        stdout = "\n".join(stdout_lines).strip()
        stderr = "\n".join(stderr_lines).strip()
        details = [f"Command timed out after {timeout_seconds} seconds: {redact_command(command)}"]
        if stderr:
            details.append(f"stderr: {_tail_text(stderr)}")
        if stdout:
            details.append(f"stdout: {_tail_text(stdout)}")
        raise RuntimeError(" ".join(details)) from exc

    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    return SubprocessResult(
        command=command,
        returncode=return_code,
        stdout="\n".join(stdout_lines).strip(),
        stderr="\n".join(stderr_lines).strip(),
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
        details.append(f"stderr: {_tail_text(result.stderr)}")
    if result.stdout:
        details.append(f"stdout: {_tail_text(result.stdout)}")
    return " ".join(details)


def _tail_text(value: str, max_length: int = 2000) -> str:
    if len(value) <= max_length:
        return value
    return f"...[truncated]\n{value[-max_length:]}"


def cleanup_resource(command: list[str], timeout_seconds: float) -> list[str]:
    result = run_subprocess(command, timeout_seconds)
    if result.returncode == 0:
        return []
    return [format_command_failure("Cleanup command failed.", result)]


def _cleanup_stale_export_sync_objects(
    manager: str,
    settings: AgentSettings,
    command_summaries: list[str],
    stdout_logs: list[str],
    stderr_logs: list[str],
    progress: ExternalExportProgress,
) -> None:
    progress.post("cleanup", "Checking for stale PBO temporary sync jobs and remotes.")
    sync_jobs = _list_pbs_resource_names(manager, "sync-job", settings, command_summaries, stdout_logs, stderr_logs)
    stale_sync_jobs = [name for name in sync_jobs if name.startswith("pbo-export-sync-")]
    for sync_job_name in stale_sync_jobs:
        lock_path = _sync_job_lock_path(sync_job_name)
        if _is_sync_job_running(sync_job_name, lock_path):
            raise RuntimeError(
                f"Refusing cleanup because temporary sync job `{sync_job_name}` appears to be running. "
                f"Lock path: `{lock_path}`."
            )
        progress.post("cleanup", f"Removing stale temporary sync job `{sync_job_name}`.")
        result = run_subprocess([manager, "sync-job", "remove", sync_job_name], settings.export_timeout_seconds)
        record_command_result(result, command_summaries, stdout_logs, stderr_logs)
        if result.returncode != 0:
            raise RuntimeError(format_command_failure(f"Failed to remove stale sync job `{sync_job_name}`.", result))
        _remove_stale_sync_job_lock(sync_job_name, stdout_logs, progress)

    remotes = _list_pbs_resource_names(manager, "remote", settings, command_summaries, stdout_logs, stderr_logs)
    for remote_name in [name for name in remotes if name.startswith("pbo-export-remote-")]:
        progress.post("cleanup", f"Removing stale temporary remote `{remote_name}`.")
        result = run_subprocess([manager, "remote", "remove", remote_name], settings.export_timeout_seconds)
        record_command_result(result, command_summaries, stdout_logs, stderr_logs)
        if result.returncode != 0:
            raise RuntimeError(format_command_failure(f"Failed to remove stale remote `{remote_name}`.", result))


def _assert_safe_pbo_datastore_mount_path(mount_path: Path, *, action: str = "use") -> None:
    """Confine a dedicated-PBS-datastore mount path to `<base>/<serial>/pbs-datastore`.

    `<base>` is `default_mount_base_path(None)` (`/mnt/pbo` in production). Used
    both before mounting (prepare) and before unmounting (eject) a dedicated
    datastore, so a caller-supplied `mount_path`/`preferred_mount_path` can
    never point at `/`, `/boot`, or anywhere outside the managed layout.
    """
    dangerous_mounts = {
        Path("/"),
        Path("/boot"),
        Path("/boot/efi"),
        Path("/mnt/datastore/backup-store"),
    }
    if mount_path in dangerous_mounts:
        raise RuntimeError(f"Refusing to {action} protected path `{mount_path}`.")
    base_path = default_mount_base_path(None)
    if mount_path.name != "pbs-datastore":
        raise RuntimeError(f"Refusing to {action} non-PBO datastore path `{mount_path}`.")
    try:
        mount_path.relative_to(base_path)
    except ValueError as exc:
        raise RuntimeError(f"Refusing to {action} non-PBO datastore path `{mount_path}`.") from exc
    if mount_path.parent.parent != base_path:
        raise RuntimeError(f"Refusing to {action} non-PBO datastore path `{mount_path}`.")


def _assert_safe_filesystem_usage_mount_path(mount_path: Path) -> None:
    dangerous_mounts = {Path("/"), Path("/boot"), Path("/boot/efi"), Path("/etc")}
    if mount_path in dangerous_mounts:
        raise RuntimeError(f"Refusing to inspect protected path `{mount_path}`.")
    try:
        mount_path.relative_to(Path("/mnt"))
    except ValueError as exc:
        raise RuntimeError(f"Refusing to inspect filesystem usage outside `/mnt`: `{mount_path}`.") from exc


def _expected_pbo_datastore_mount_paths(serial: str) -> list[Path]:
    base_path = default_mount_base_path(None)
    return [base_path / alias / "pbs-datastore" for alias in mount_path_serial_aliases(serial)]


def normalize_serial_for_compare(value: str | None) -> str:
    if value is None:
        return ""
    return "".join(char for char in value.strip().upper() if char not in " _-")


def decode_hex_ascii_serial(value: str | None) -> str | None:
    clean = normalize_serial_for_compare(value)
    if len(clean) < 8 or len(clean) % 2 != 0:
        return None
    if any(char not in string.hexdigits.upper() for char in clean):
        return None
    try:
        decoded = binascii.unhexlify(clean).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    if not decoded or any(char not in string.printable or char in "\r\n\t\x0b\x0c" for char in decoded):
        return None
    return decoded


def canonical_serial_number(value: str | None) -> str:
    decoded = decode_hex_ascii_serial(value)
    candidate = normalize_serial_for_compare(decoded or value)
    for prefix in ("WDC", "WD"):
        if candidate.startswith(prefix):
            remainder = candidate[len(prefix) :]
            if len(remainder) >= 6 and remainder.startswith("W"):
                return remainder
    return candidate


def serial_aliases(value: str | None) -> list[str]:
    aliases: list[str] = []
    for candidate in (value, decode_hex_ascii_serial(value), canonical_serial_number(value)):
        normalized = normalize_serial_for_compare(candidate)
        if normalized and normalized not in aliases:
            aliases.append(normalized)
        canonical = canonical_serial_number(candidate)
        if canonical and canonical not in aliases:
            aliases.append(canonical)
    return aliases


def mount_path_serial_aliases(value: str | None) -> list[str]:
    aliases: list[str] = []
    for candidate in (value, decode_hex_ascii_serial(value), canonical_serial_number(value)):
        if isinstance(candidate, str):
            stripped = candidate.strip()
            if stripped and stripped not in aliases:
                aliases.append(stripped)
            normalized = normalize_serial_for_compare(candidate)
            if normalized and normalized not in aliases:
                aliases.append(normalized)
    canonical = canonical_serial_number(value)
    if canonical:
        for candidate in (canonical, f"WD-{canonical}", f"WDC-{canonical}", f"WDC_{canonical}"):
            if candidate not in aliases:
                aliases.append(candidate)
    return aliases


def _is_target_busy_umount_result(result: SubprocessResult) -> bool:
    output = f"{result.stdout}\n{result.stderr}".casefold()
    return "busy" in output or "target is busy" in output


def _handle_busy_dedicated_datastore_unmount(
    mount_path: Path,
    manager: str,
    datastore_name: str,
    settings: AgentSettings,
    original_umount_result: SubprocessResult,
    command_summaries: list[str],
    stdout_logs: list[str],
    stderr_logs: list[str],
) -> None:
    fuser_result = _run_fuser_verbose(mount_path)
    record_command_result(fuser_result, command_summaries, stdout_logs, stderr_logs)
    fuser_output = _combined_command_output(fuser_result)

    if _pbs_datastore_has_running_tasks(manager, datastore_name, settings, command_summaries, stdout_logs, stderr_logs):
        raise RuntimeError(
            f"Refusing to eject because a PBS task started while `{mount_path}` was busy.\n"
            f"fuser output:\n{fuser_output or '(no fuser output)'}"
        )
    if _pbo_export_sync_job_running(manager, settings, command_summaries, stdout_logs, stderr_logs):
        raise RuntimeError(
            f"Refusing to eject because a temporary PBO export sync job started while `{mount_path}` was busy.\n"
            f"fuser output:\n{fuser_output or '(no fuser output)'}"
        )

    sync_result = run_subprocess(["sync"], timeout_seconds=60)
    record_command_result(sync_result, command_summaries, stdout_logs, stderr_logs)
    if sync_result.returncode != 0:
        raise RuntimeError(format_command_failure("Failed to sync filesystem buffers before stopping PBS services.", sync_result))

    stopped_services: list[str] = []
    retry_result: SubprocessResult | None = None
    try:
        for service in ("proxmox-backup-proxy.service", "proxmox-backup.service"):
            result = run_subprocess(["systemctl", "stop", service], timeout_seconds=60)
            record_command_result(result, command_summaries, stdout_logs, stderr_logs)
            if result.returncode != 0:
                raise RuntimeError(format_command_failure(f"Failed to stop `{service}` before eject.", result))
            stopped_services.append(service)

        time.sleep(3)
        sync_result = run_subprocess(["sync"], timeout_seconds=60)
        record_command_result(sync_result, command_summaries, stdout_logs, stderr_logs)
        if sync_result.returncode != 0:
            raise RuntimeError(format_command_failure("Failed to sync filesystem buffers before retrying unmount.", sync_result))

        retry_result = run_subprocess(["umount", str(mount_path)], timeout_seconds=settings.export_timeout_seconds)
        record_command_result(retry_result, command_summaries, stdout_logs, stderr_logs)
    finally:
        for service in ("proxmox-backup.service", "proxmox-backup-proxy.service"):
            if service not in stopped_services:
                continue
            result = run_subprocess(["systemctl", "start", service], timeout_seconds=60)
            record_command_result(result, command_summaries, stdout_logs, stderr_logs)
            if result.returncode != 0:
                stderr_logs.append(format_command_failure(f"Failed to start `{service}` after eject attempt.", result))

    if (retry_result is not None and retry_result.returncode != 0) or _find_mount_source(mount_path):
        details = [
            f"Refusing to eject because `{mount_path}` is still mounted after stopping PBS services.",
            format_command_failure("Original unmount attempt failed.", original_umount_result),
            f"fuser output:\n{fuser_output or '(no fuser output)'}",
        ]
        if retry_result is not None:
            details.append(format_command_failure("Second unmount attempt failed.", retry_result))
        raise RuntimeError("\n".join(details))


def _run_fuser_verbose(mount_path: Path) -> SubprocessResult:
    fuser = shutil.which("fuser")
    if not fuser:
        return SubprocessResult(["fuser", "-vm", str(mount_path)], 127, "", "Missing required dependency: fuser")
    return run_subprocess([fuser, "-vm", str(mount_path)], timeout_seconds=15)


def _combined_command_output(result: SubprocessResult) -> str:
    return "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part).strip()


def _only_pbs_services_block_mount(fuser_output: str) -> bool:
    lines = [line for line in fuser_output.splitlines() if line.strip()]
    if not lines:
        return False
    return all(_is_safe_pbs_fuser_line(line) for line in lines)


def _is_safe_pbs_fuser_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if "USER" in stripped and "PID" in stripped and "COMMAND" in stripped:
        return True
    if stripped.endswith(":"):
        return True
    if " kernel " in f" {stripped} " and " mount " in f" {stripped} ":
        return True
    safe_tokens = (
        "proxmox-backup-",
        "proxmox-backup-proxy",
        "proxmox-backup-api",
        "proxmox-backup.service",
        "proxmox-backup-proxy.service",
    )
    return any(token in stripped for token in safe_tokens)


def _fuser_process_lines(fuser_output: str) -> list[str]:
    lines: list[str] = []
    for raw_line in fuser_output.splitlines():
        line = raw_line.strip().casefold()
        if not line:
            continue
        if _is_fuser_header_line(line) or _is_fuser_mount_label_line(line):
            continue
        if _is_fuser_kernel_mount_line(line):
            continue
        tokens = line.split()
        if _looks_like_fuser_process_line(tokens):
            lines.append(line)
    return lines


def _is_fuser_header_line(line: str) -> bool:
    tokens = set(line.split())
    return {"user", "pid", "access", "command"}.issubset(tokens)


def _is_fuser_mount_label_line(line: str) -> bool:
    return line.endswith(":") and (line.startswith("/") or line.startswith("/mnt/pbo/"))


def _is_fuser_kernel_mount_line(line: str) -> bool:
    tokens = line.replace(":", " ").split()
    return "kernel" in tokens and "mount" in tokens


def _looks_like_fuser_process_line(tokens: list[str]) -> bool:
    if len(tokens) < 4:
        return False
    return any(token.isdigit() for token in tokens)


def _pbs_datastore_has_running_tasks(
    manager: str,
    datastore_name: str,
    settings: AgentSettings,
    command_summaries: list[str],
    stdout_logs: list[str],
    stderr_logs: list[str],
) -> bool:
    result = run_subprocess([manager, "task", "list", "--output-format", "json"], settings.export_timeout_seconds)
    record_command_result(result, command_summaries, stdout_logs, stderr_logs)
    if result.returncode != 0:
        raise RuntimeError(format_command_failure("Failed to list PBS tasks before eject.", result))

    for item in parse_json_output(result.stdout, "task list"):
        if not _pbs_task_is_running(item):
            continue
        if datastore_name and datastore_name in json.dumps(item, sort_keys=True):
            return True
    return False


def _pbs_task_is_running(task: dict[str, Any]) -> bool:
    status_value = task.get("status") or task.get("state")
    if status_value is None:
        return True
    return str(status_value).strip().casefold() in {"running", "active", "pending"}


def _pbo_export_sync_job_running(
    manager: str,
    settings: AgentSettings,
    command_summaries: list[str],
    stdout_logs: list[str],
    stderr_logs: list[str],
) -> bool:
    sync_jobs = _list_pbs_resource_names(manager, "sync-job", settings, command_summaries, stdout_logs, stderr_logs)
    for sync_job_name in sync_jobs:
        if sync_job_name.startswith("pbo-export-sync-") and _is_sync_job_running(
            sync_job_name,
            _sync_job_lock_path(sync_job_name),
        ):
            return True
    return False


def _list_pbs_resource_names(
    manager: str,
    resource: str,
    settings: AgentSettings,
    command_summaries: list[str],
    stdout_logs: list[str],
    stderr_logs: list[str],
) -> list[str]:
    result = run_subprocess([manager, resource, "list", "--output-format", "json"], settings.export_timeout_seconds)
    record_command_result(result, command_summaries, stdout_logs, stderr_logs)
    if result.returncode != 0:
        raise RuntimeError(format_command_failure(f"Failed to list PBS {resource} resources.", result))
    names: list[str] = []
    for item in parse_json_output(result.stdout, f"{resource} list"):
        name = item.get("id") or item.get("name") or item.get("store")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _sync_job_lock_path(sync_job_name: str) -> Path:
    return Path("/var/lib/proxmox-backup/jobstates") / f"syncjob-{sync_job_name}.lck"


def _is_sync_job_running(sync_job_name: str, lock_path: Path) -> bool:
    fuser = shutil.which("fuser")
    if fuser and lock_path.exists():
        result = run_subprocess([fuser, str(lock_path)], timeout_seconds=5)
        if result.returncode == 0:
            return True

    pgrep = shutil.which("pgrep")
    if pgrep:
        result = run_subprocess([pgrep, "-f", sync_job_name], timeout_seconds=5)
        if result.returncode == 0 and result.stdout:
            return True

    return False


def _remove_stale_sync_job_lock(
    sync_job_name: str,
    stdout_logs: list[str],
    progress: ExternalExportProgress,
) -> None:
    lock_path = _sync_job_lock_path(sync_job_name)
    if not lock_path.exists():
        return
    lock_path.unlink()
    message = f"Removed stale sync job lock `{lock_path}`."
    stdout_logs.append(message)
    progress.post("cleanup", message)


def external_export_objects_status(settings: AgentSettings | None = None) -> dict[str, Any]:
    settings = settings or AgentSettings()
    manager = shutil.which("proxmox-backup-manager")
    if manager is None:
        raise RuntimeError("Missing required host dependency: `proxmox-backup-manager` was not found in PATH.")

    command_summaries: list[str] = []
    stdout_logs: list[str] = []
    stderr_logs: list[str] = []
    sync_jobs = [
        name
        for name in _list_pbs_resource_names(manager, "sync-job", settings, command_summaries, stdout_logs, stderr_logs)
        if name.startswith("pbo-export-sync-")
    ]
    remotes = [
        name
        for name in _list_pbs_resource_names(manager, "remote", settings, command_summaries, stdout_logs, stderr_logs)
        if name.startswith("pbo-export-remote-")
    ]

    items: list[dict[str, Any]] = []
    active = False
    for name in sync_jobs:
        lock_path = _sync_job_lock_path(name)
        running = _is_sync_job_running(name, lock_path)
        active = active or running
        items.append(
            {
                "kind": "sync-job",
                "name": name,
                "path": None,
                "status": "active" if running else "stale",
                "safe_to_remove": not running,
            }
        )
        if lock_path.exists():
            items.append(
                {
                    "kind": "jobstate-lock",
                    "name": lock_path.name,
                    "path": str(lock_path),
                    "status": "active" if running else "stale",
                    "safe_to_remove": not running,
                }
            )

    for remote in remotes:
        items.append(
            {
                "kind": "remote",
                "name": remote,
                "path": None,
                "status": "stale",
                "safe_to_remove": not active,
            }
        )

    for lock_path in _pbo_operation_lock_paths():
        items.append(
            {
                "kind": "operation-lock",
                "name": lock_path.name,
                "path": str(lock_path),
                "status": "active" if active else "stale",
                "safe_to_remove": not active,
            }
        )

    return {
        "ok": True,
        "success": True,
        "active": active,
        "message": "PBO temporary external export objects inspected.",
        "items": items,
        "command_summary": "\n".join(command_summaries),
        "execution_cwd": str(Path.cwd()),
        "stdout_log": "\n\n".join(stdout_logs) or None,
        "stderr_log": "\n\n".join(stderr_logs) or None,
        "return_code": 0,
    }


def cleanup_external_export_objects_result(settings: AgentSettings | None = None) -> dict[str, Any]:
    settings = settings or AgentSettings()
    status_payload = external_export_objects_status(settings)
    if status_payload["active"]:
        return {
            "ok": False,
            "success": False,
            "active": True,
            "message": "Refusing cleanup because a PBO PBS task or process is active.",
            "items": status_payload["items"],
            "return_code": 1,
        }

    manager = shutil.which("proxmox-backup-manager")
    if manager is None:
        raise RuntimeError("Missing required host dependency: `proxmox-backup-manager` was not found in PATH.")
    command_summaries: list[str] = []
    stdout_logs: list[str] = []
    stderr_logs: list[str] = []
    errors: list[str] = []
    actions: list[str] = []

    for item in status_payload["items"]:
        if not item.get("safe_to_remove"):
            continue
        kind = item.get("kind")
        name = item.get("name")
        path = item.get("path")
        if kind == "sync-job" and isinstance(name, str):
            result = run_subprocess([manager, "sync-job", "remove", name], settings.export_timeout_seconds)
            record_command_result(result, command_summaries, stdout_logs, stderr_logs)
            actions.append(f"remove sync-job {name}")
            if result.returncode != 0:
                errors.append(format_command_failure(f"Failed to remove stale sync job `{name}`.", result))
        elif kind == "remote" and isinstance(name, str):
            result = run_subprocess([manager, "remote", "remove", name], settings.export_timeout_seconds)
            record_command_result(result, command_summaries, stdout_logs, stderr_logs)
            actions.append(f"remove remote {name}")
            if result.returncode != 0:
                errors.append(format_command_failure(f"Failed to remove stale remote `{name}`.", result))
        elif kind in {"jobstate-lock", "operation-lock"} and isinstance(path, str):
            lock_path = Path(path)
            if lock_path.name == ".lock" or ".chunks" in lock_path.parts:
                continue
            if lock_path.exists():
                lock_path.unlink()
                actions.append(f"remove lock {lock_path}")

    return {
        "ok": not errors,
        "success": not errors,
        "active": False,
        "message": "PBO temporary external export cleanup completed." if not errors else "PBO temporary cleanup completed with errors.",
        "items": status_payload["items"],
        "actions": actions,
        "command_summary": "\n".join(command_summaries),
        "execution_cwd": str(Path.cwd()),
        "stdout_log": "\n\n".join([*stdout_logs, *actions]) or None,
        "stderr_log": "\n\n".join([*stderr_logs, *errors]) or None,
        "return_code": 0 if not errors else 1,
    }


def _pbo_operation_lock_paths() -> list[Path]:
    candidates: list[Path] = []
    for directory in (Path("/run/lock"), Path("/var/lock"), Path("/tmp")):
        if not directory.exists():
            continue
        candidates.extend(path for path in directory.glob("pbo-wd-*") if path.is_file())
    return candidates


def cleanup_legacy_external_export_objects(settings: AgentSettings | None = None) -> dict[str, Any]:
    settings = settings or AgentSettings()
    manager = shutil.which("proxmox-backup-manager")
    if manager is None:
        raise RuntimeError("Missing required host dependency: `proxmox-backup-manager` was not found in PATH.")
    command_summaries: list[str] = []
    stdout_logs: list[str] = []
    stderr_logs: list[str] = []
    errors: list[str] = []
    for resource, list_command, remove_prefix in [
        ("sync-job", [manager, "sync-job", "list", "--output-format", "json"], [manager, "sync-job", "remove"]),
        ("remote", [manager, "remote", "list", "--output-format", "json"], [manager, "remote", "remove"]),
        ("datastore", [manager, "datastore", "list", "--output-format", "json"], [manager, "datastore", "remove"]),
    ]:
        result = run_subprocess(list_command, settings.export_timeout_seconds)
        record_command_result(result, command_summaries, stdout_logs, stderr_logs)
        if result.returncode != 0:
            errors.append(format_command_failure(f"Failed to list PBS {resource}.", result))
            continue
        for item in parse_json_output(result.stdout, f"{resource} list"):
            name = item.get("id") or item.get("name") or item.get("store")
            if not isinstance(name, str) or not name.startswith("pbo-export-"):
                continue
            if name == settings.pbs_auth_id or name == "backup-store":
                continue
            remove_result = run_subprocess([*remove_prefix, name], settings.export_timeout_seconds)
            record_command_result(remove_result, command_summaries, stdout_logs, stderr_logs)
            if remove_result.returncode != 0:
                errors.append(format_command_failure(f"Failed to remove legacy PBS {resource} `{name}`.", remove_result))
    return {
        "ok": not errors,
        "success": not errors,
        "message": "Legacy external export cleanup completed." if not errors else "Legacy cleanup completed with errors.",
        "command_summary": "\n".join(command_summaries),
        "execution_cwd": str(Path.cwd()),
        "stdout_log": "\n\n".join(stdout_logs) or None,
        "stderr_log": "\n\n".join([*stderr_logs, *errors]) or None,
        "return_code": 0 if not errors else 1,
    }


def maintenance_check_result(settings: AgentSettings | None = None) -> dict[str, Any]:
    settings = settings or AgentSettings()
    status_payload = _maintenance_git_status(
        Path(settings.repo_path),
        settings.maintenance_timeout_seconds,
    )
    return {
        "ok": status_payload["status"] != "error",
        "message": "Maintenance status checked.",
        "status": status_payload,
    }


def maintenance_update_result(settings: AgentSettings | None = None) -> dict[str, Any]:
    settings = settings or AgentSettings()
    repo = Path(settings.repo_path)
    current_status = _maintenance_git_status(repo, settings.maintenance_timeout_seconds)
    if current_status["status"] == "error":
        return {
            "ok": False,
            "message": current_status["error"] or "Maintenance check failed.",
            "action_status": "error",
            "status": current_status,
            "logs": current_status["logs"],
            "return_code": 1,
        }
    if current_status["local_commit"] == current_status["remote_commit"]:
        return {
            "ok": True,
            "message": "Already up to date.",
            "action_status": "up_to_date",
            "status": current_status,
            "logs": current_status["logs"],
            "return_code": 0,
        }

    logs = _maintenance_run_sequence(
        repo,
        [
            ["git", "status", "--short"],
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            ["git", "rev-parse", "HEAD"],
            ["git", "rev-parse", "@{u}"],
            ["git", "pull", "--ff-only"],
        ],
        settings.maintenance_timeout_seconds,
    )
    status_payload = _maintenance_git_status(repo, settings.maintenance_timeout_seconds)
    ok = all(item["return_code"] == 0 for item in logs) and status_payload["status"] != "error"
    return {
        "ok": ok,
        "message": "Agent update completed." if ok else "Agent update failed.",
        "action_status": "success" if ok else "error",
        "status": status_payload,
        "logs": logs,
        "return_code": 0 if ok else 1,
    }


def _maintenance_git_status(repo: Path, timeout_seconds: float) -> dict[str, Any]:
    logs = _maintenance_run_sequence(repo, [["git", "fetch"], ["git", "status", "--short"]], timeout_seconds)
    branch = _maintenance_run(repo, ["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout_seconds)
    local = _maintenance_run(repo, ["git", "rev-parse", "HEAD"], timeout_seconds)
    remote = _maintenance_run(repo, ["git", "rev-parse", "@{u}"], timeout_seconds)
    logs.extend([branch, local, remote])
    error = next((item["stderr"] or item["stdout"] for item in logs if item["return_code"] != 0), None)
    status = "error" if error else ("up_to_date" if local["stdout"] == remote["stdout"] else "update_available")
    return {
        "branch": branch["stdout"],
        "local_commit": local["stdout"],
        "remote_commit": remote["stdout"],
        "status": status,
        "error": error,
        "logs": logs,
    }


def _maintenance_run_sequence(repo: Path, commands: list[list[str]], timeout_seconds: float) -> list[dict[str, Any]]:
    logs: list[dict[str, Any]] = []
    for command in commands:
        result = _maintenance_run(repo, command, timeout_seconds)
        logs.append(result)
        if result["return_code"] != 0:
            break
    return logs


def _maintenance_run(repo: Path, command: list[str], timeout_seconds: float) -> dict[str, Any]:
    try:
        result = run_subprocess_with_cwd(command, repo, timeout_seconds)
    except RuntimeError as exc:
        return {
            "command": redact_command(command),
            "stdout": None,
            "stderr": str(exc),
            "return_code": 1,
        }
    return {
        "command": redact_command(result.command),
        "stdout": result.stdout or None,
        "stderr": result.stderr or None,
        "return_code": result.returncode,
    }


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


def post_json(settings: AgentSettings, path: str, payload: dict[str, Any], token: str | None = None) -> None:
    base_url = settings.api_base_url.rstrip("/")
    headers = {"X-Agent-Token": token} if token else None
    with httpx.Client(timeout=settings.timeout_seconds) as client:
        response = client.post(f"{base_url}{path}", json=payload, headers=headers)
        response.raise_for_status()


def post_progress_callback(
    settings: AgentSettings,
    callback_url: str | None,
    fallback_path: str,
    payload: dict[str, Any],
    *,
    token: str | None,
) -> None:
    headers = {"X-Agent-Token": token} if token else None
    url = callback_url or f"{settings.api_base_url.rstrip('/')}{fallback_path}"
    with httpx.Client(timeout=settings.timeout_seconds) as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()


def current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sys_executable() -> str:
    return sys.executable


def _git_sha(repo_path: str) -> str | None:
    try:
        return run_command(["git", "-C", repo_path, "rev-parse", "HEAD"])
    except Exception:
        return None


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
    size_bytes = _parse_size_bytes(raw_size)
    if size_bytes <= 0:
        return 0

    return round(size_bytes / (1024**3))


def _parse_size_bytes(raw_size: Any) -> float:
    if isinstance(raw_size, bool) or raw_size is None:
        return 0
    if isinstance(raw_size, int | float):
        return float(raw_size)
    if not isinstance(raw_size, str):
        return 0

    value = raw_size.strip()
    if not value:
        return 0
    try:
        return float(value)
    except ValueError:
        pass

    unit = value[-1].upper()
    multiplier_by_unit = {
        "K": 1024,
        "M": 1024**2,
        "G": 1024**3,
        "T": 1024**4,
        "P": 1024**5,
    }
    multiplier = multiplier_by_unit.get(unit)
    if multiplier is None:
        return 0
    try:
        number = float(value[:-1].strip())
    except ValueError:
        return 0
    return number * multiplier


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal Proxmox host agent scaffold")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("serve", help="Start the host agent HTTP API server")
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


def build_command_failure_payload(command_name: str, exc: Exception) -> dict[str, Any]:
    return {
        "ok": False,
        "message": str(exc),
        "command_summary": command_name,
        "execution_cwd": str(Path.cwd()),
        "stdout_log": None,
        "stderr_log": str(exc),
        "return_code": _infer_error_return_code(exc),
    }


def emit_command_failure(command_name: str, exc: Exception) -> None:
    payload = build_command_failure_payload(command_name, exc)
    print(json.dumps(payload))
    logger.exception("Agent command %s failed", command_name)
    raise SystemExit(1) from exc


def _infer_error_return_code(exc: Exception) -> int:
    if isinstance(exc, subprocess.CalledProcessError):
        return exc.returncode
    return 1


def serve_http_api(settings: AgentSettings) -> None:
    uvicorn.run(
        "agent.server:app",
        host=settings.server_host,
        port=settings.server_port,
        log_level="info",
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = AgentSettings()

    if args.command == "serve":
        serve_http_api(settings)
        return

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
        print(json.dumps(inspect_disk_result(args.disk, args.mount_base_path)))
        return

    if args.command == "prepare-disk":
        try:
            print(json.dumps(prepare_disk_result(args.disk, args.mode, args.mount_base_path, args.confirm_destructive)))
        except Exception as exc:
            emit_command_failure(args.command, exc)
        return

    if args.command == "prepare-external-datastore":
        try:
            print(json.dumps(prepare_external_datastore_result(args.mount_path, args.target_path, args.mode, settings)))
        except Exception as exc:
            emit_command_failure(args.command, exc)
        return

    if args.command == "run-external-export":
        try:
            print(json.dumps(run_external_export_result(args.target_path, args.datastore_name, args.mode, settings)))
        except Exception as exc:
            emit_command_failure(args.command, exc)
        return

    parser.error("Unknown command")


if __name__ == "__main__":
    main()
