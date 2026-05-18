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
import threading
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
    datastore_create_timeout_seconds: float = float(
        os.getenv("AGENT_DATASTORE_CREATE_TIMEOUT_SECONDS", "14400")
    )
    loop_datastore_size_gb: int = int(os.getenv("AGENT_LOOP_DATASTORE_SIZE_GB", "500"))
    server_host: str = os.getenv("AGENT_SERVER_HOST", "0.0.0.0")
    server_port: int = int(os.getenv("AGENT_SERVER_PORT", "8081"))
    server_token: str = os.getenv("AGENT_SERVER_TOKEN", "")


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
        self.callback_token = callback_token or settings.server_token

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
    settings: AgentSettings,
    callback_run_id: int | None = None,
    callback_url: str | None = None,
    callback_token: str | None = None,
) -> dict[str, Any]:
    progress = ExternalExportProgress(settings, callback_run_id, callback_url, callback_token)
    if not confirmation:
        raise RuntimeError("Dedicated PBS datastore preparation requires destructive confirmation.")

    disk, _ = resolve_disk(identifier)
    serial = disk_serial_number(disk, load_udev_properties(device_name(disk))) or device_name(disk)
    device_path = str(disk["path"])
    size_gb = bytes_to_gb(disk.get("size"))
    if size_gb < 32:
        raise RuntimeError(f"Refusing to prepare `{device_path}` because it is below the 32 GB minimum.")
    _assert_safe_dedicated_disk(disk)

    mount_path = default_mount_base_path(None) / serial / "pbs-datastore"
    partition_path = _first_partition_path(device_path)
    command_summaries: list[str] = []
    stdout_logs: list[str] = []
    stderr_logs: list[str] = []

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
    _run_logged_command(["chown", "backup:backup", str(mount_path)], command_summaries, stdout_logs, stderr_logs, f"Failed to chown `{mount_path}`.", progress=progress, step="permissions")
    _run_logged_command(["chmod", "750", str(mount_path)], command_summaries, stdout_logs, stderr_logs, f"Failed to chmod `{mount_path}`.", progress=progress, step="permissions")
    progress.post("prepare_dedicated_datastore", f"Dedicated PBS datastore mount is ready at `{mount_path}`.")

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
        "message": "Dedicated PBS datastore disk formatted and mounted.",
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
    target_was_initialized = is_initialized_pbs_datastore_path(target)
    datastore_create_timeout = max(
        settings.export_timeout_seconds,
        settings.datastore_create_timeout_seconds,
    )
    target_filesystem_type = filesystem_type_for_path(target)

    try:
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
                create_store_result = run_subprocess_streaming(
                    create_store_command,
                    timeout_seconds=datastore_create_timeout,
                    on_stdout=lambda line: progress.post("target_datastore_stdout", line, stdout_line=line),
                    on_stderr=lambda line: progress.post("target_datastore_stderr", line, stderr_line=line),
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
        sync_run_result = run_subprocess_streaming(
            [manager, "sync-job", "run", sync_job_name],
            timeout_seconds=settings.export_timeout_seconds,
            on_stdout=lambda line: progress.post("sync_stdout", line, stdout_line=line),
            on_stderr=lambda line: progress.post("sync_stderr", line, stderr_line=line),
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
        if progress is not None:
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
