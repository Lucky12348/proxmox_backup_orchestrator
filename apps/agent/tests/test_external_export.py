import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from agent.main import (
    AgentSettings,
    SubprocessResult,
    filesystem_usage_for_mount_path,
    filesystem_usage_result,
    _ensure_loop_image_mounted,
    _assert_safe_pbo_datastore_mount_path,
    _expected_pbo_datastore_mount_paths,
    _find_mount_source,
    _fuser_process_lines,
    _is_safe_pbs_fuser_line,
    _only_pbs_services_block_mount,
    bytes_to_gb,
    cleanup_external_export_objects_result,
    eject_dedicated_pbs_datastore_result,
    external_export_objects_status,
    is_initialized_pbs_datastore_path,
    loop_backing_file,
    prepare_dedicated_pbs_datastore_result,
    prepare_external_datastore_result,
    resolve_disk,
    run_external_export_result,
    qemu_config_result,
    qemu_usb_attach_result,
    qemu_usb_detach_result,
    spin_down_disk_result,
)


class ExternalExportDatastoreCreateTests(TestCase):
    def test_qemu_usb_attach_runs_qm_set(self):
        commands: list[list[str]] = []

        def fake_run_subprocess(command: list[str], timeout_seconds: float) -> SubprocessResult:
            commands.append(command)
            return SubprocessResult(command, 0, "updated", "")

        with patch("agent.main.run_subprocess", side_effect=fake_run_subprocess):
            result = qemu_usb_attach_result(100, "usb0", "1-9", False)

        self.assertTrue(result["ok"])
        self.assertEqual(commands, [["qm", "set", "100", "-usb0", "host=1-9,usb3=0"]])

    def test_qemu_usb_detach_runs_qm_delete(self):
        commands: list[list[str]] = []

        def fake_run_subprocess(command: list[str], timeout_seconds: float) -> SubprocessResult:
            commands.append(command)
            return SubprocessResult(command, 0, "updated", "")

        with patch("agent.main.run_subprocess", side_effect=fake_run_subprocess):
            result = qemu_usb_detach_result(100, "usb0")

        self.assertTrue(result["ok"])
        self.assertEqual(commands, [["qm", "set", "100", "-delete", "usb0"]])

    def test_spin_down_tries_hdparm_then_udisksctl_when_both_available(self):
        disk = {"path": "/dev/sdc", "type": "disk", "children": []}
        commands: list[list[str]] = []

        def fake_which(name: str) -> str | None:
            return f"/usr/bin/{name}" if name in {"hdparm", "udisksctl"} else None

        def fake_run_subprocess(command: list[str], timeout_seconds: float) -> SubprocessResult:
            commands.append(command)
            return SubprocessResult(command, 0, "ok", "")

        with (
            patch("agent.main.resolve_disk", return_value=(disk, [disk])),
            patch("agent.main.shutil.which", side_effect=fake_which),
            patch("agent.main.run_subprocess", side_effect=fake_run_subprocess),
        ):
            result = spin_down_disk_result("WD-SERIAL")

        self.assertTrue(result["ok"])
        self.assertEqual(commands, [["/usr/bin/hdparm", "-y", "/dev/sdc"], ["/usr/bin/udisksctl", "power-off", "-b", "/dev/sdc"]])
        self.assertTrue(all(attempt["ok"] for attempt in result["attempts"]))

    def test_spin_down_reports_unsupported_tools_without_failing(self):
        disk = {"path": "/dev/sdc", "type": "disk", "children": []}

        with (
            patch("agent.main.resolve_disk", return_value=(disk, [disk])),
            patch("agent.main.shutil.which", return_value=None),
        ):
            result = spin_down_disk_result("WD-SERIAL")

        self.assertTrue(result["ok"])
        self.assertFalse(any(attempt["ok"] for attempt in result["attempts"]))
        self.assertIn("may keep spinning", result["message"])

    def test_spin_down_handles_unresolvable_disk_without_raising(self):
        with (
            patch("agent.main.resolve_disk", side_effect=FileNotFoundError("no such disk")),
            patch("agent.main.shutil.which", return_value=None),
            patch("agent.main.time.sleep"),
        ):
            result = spin_down_disk_result("missing-serial")

        self.assertTrue(result["ok"])
        self.assertEqual(result["attempts"], [])
        self.assertIn("re-enumerating", result["message"])

    def test_spin_down_waits_for_disk_to_reappear_after_usb_detach(self):
        disk = {"path": "/dev/sdc", "type": "disk", "children": []}
        # Simulate the disk not being visible yet right after USB detach, then
        # showing up on the second lsblk-backed resolve_disk() call.
        resolve_effects = [FileNotFoundError("not yet"), (disk, [disk])]

        with (
            patch("agent.main.resolve_disk", side_effect=resolve_effects),
            patch("agent.main.shutil.which", return_value=None),
            patch("agent.main.time.sleep") as sleep_mock,
        ):
            result = spin_down_disk_result("WD-SERIAL")

        sleep_mock.assert_called_once()
        self.assertEqual(result["attempts"][0]["stderr_log"], "hdparm is not installed on this host; skipped.")

    def test_qemu_config_returns_qm_config_output(self):
        with patch(
            "agent.main.run_subprocess",
            return_value=SubprocessResult(["qm", "config", "100"], 0, "usb0: host=1-9,usb3=0", ""),
        ):
            result = qemu_config_result(100)

        self.assertEqual(result["config"], "usb0: host=1-9,usb3=0")

    def test_bytes_to_gb_parses_human_readable_sizes(self):
        self.assertGreater(bytes_to_gb("3.6T"), 3000)
        self.assertGreaterEqual(bytes_to_gb("750G"), 749)
        self.assertLessEqual(bytes_to_gb("750G"), 751)
        self.assertLess(bytes_to_gb("16M"), 1)
        self.assertGreaterEqual(bytes_to_gb(4000000000000), 3724)
        self.assertLessEqual(bytes_to_gb(4000000000000), 3726)

    def test_filesystem_usage_for_mount_path_returns_real_usage_when_mount_is_measurable(self):
        fake_stats = type(
            "StatVfs",
            (),
            {
                "f_frsize": 1024 * 1024,
                "f_bsize": 1024 * 1024,
                "f_blocks": 4000 * 1024,
                "f_bavail": 2500 * 1024,
            },
        )()

        with (
            patch("agent.main.os.path.ismount", return_value=True),
            patch("agent.main.os.statvfs", return_value=fake_stats, create=True),
        ):
            usage = filesystem_usage_for_mount_path("/mnt/test-disk")

        self.assertEqual(usage["total_gb"], 4000)
        self.assertEqual(usage["free_gb"], 2500)
        self.assertEqual(usage["used_gb"], 1500)

    def test_filesystem_usage_for_mount_path_returns_nulls_when_mount_is_unavailable(self):
        with patch("agent.main.os.path.ismount", return_value=False):
            usage = filesystem_usage_for_mount_path("/mnt/test-disk")

        self.assertEqual(usage, {"total_gb": None, "used_gb": None, "free_gb": None})

    def test_filesystem_usage_result_rejects_path_outside_mnt(self):
        with self.assertRaises(RuntimeError):
            filesystem_usage_result("/var/lib")

    def test_dedicated_prepare_size_error_includes_raw_and_parsed_values(self):
        disk = {
            "name": "sdc",
            "kname": "sdc",
            "path": "/dev/sdc",
            "type": "disk",
            "serial": "WD-WXD2DA1L1E7C",
            "size": "16M",
            "children": [],
        }

        with (
            patch("agent.main.resolve_disk", return_value=(disk, [disk])),
            patch("agent.main.load_udev_properties", return_value={}),
            self.assertRaises(RuntimeError) as raised,
        ):
            prepare_dedicated_pbs_datastore_result(
                "/dev/sdc",
                "pbo-WD-WXD2DA1L1E7C",
                True,
                False,
                AgentSettings(),
            )

        message = str(raised.exception)
        self.assertIn("raw size=`16M`", message)
        self.assertIn("parsed size=`0 GB`", message)
        self.assertIn("minimum=`32 GB`", message)

    def test_resolve_disk_accepts_canonical_serial_when_udev_reports_wd_prefix(self):
        disk = _dedicated_test_disk()
        disk["serial"] = None

        with (
            patch("agent.main.list_all_block_nodes", return_value=[disk]),
            patch("agent.main.load_udev_properties", return_value={"ID_SERIAL_SHORT": "WD-WXD2DA1L1E7C"}),
        ):
            resolved, _ = resolve_disk("WXD2DA1L1E7C")

        self.assertEqual(resolved["path"], "/dev/sdc")

    def test_resolve_disk_accepts_canonical_serial_when_udev_reports_hex_alias(self):
        disk = _dedicated_test_disk()
        disk["serial"] = None

        with (
            patch("agent.main.list_all_block_nodes", return_value=[disk]),
            patch("agent.main.load_udev_properties", return_value={"ID_SERIAL_SHORT": "575844324441314C31453743"}),
        ):
            resolved, _ = resolve_disk("WXD2DA1L1E7C")

        self.assertEqual(resolved["path"], "/dev/sdc")

    def test_dedicated_prepare_reuses_existing_marker_without_formatting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            mount = base / "WD-WXD2DA1L1E7C" / "pbs-datastore"
            mount.mkdir(parents=True)
            (mount / ".pbo-dedicated-datastore.json").write_text(
                json.dumps(
                    {
                        "serial": "WD-WXD2DA1L1E7C",
                        "datastore_name": "pbo-wd-wxd2da1l1e7c",
                        "created_at": "2026-05-18T00:00:00Z",
                        "app_name": "proxmox_backup_orchestrator",
                        "filesystem_type": "ext4",
                        "partition_path": "/dev/sdc1",
                    }
                ),
                encoding="utf-8",
            )
            disk = _dedicated_test_disk()
            commands: list[list[str]] = []

            def fake_run_logged_command(command, *args, **kwargs):
                commands.append(command)
                return SubprocessResult(command, 0, "", "")

            with (
                patch("agent.main.resolve_disk", return_value=(disk, [disk])),
                patch("agent.main.load_udev_properties", return_value={}),
                patch("agent.main.default_mount_base_path", return_value=base),
                patch("agent.main.shutil.which", return_value="/usr/sbin/proxmox-backup-manager"),
                patch("agent.main._is_mounted_at", return_value=True),
                patch("agent.main._find_pbs_datastore_name_for_path", return_value="pbo-wd-wxd2da1l1e7c"),
                patch("agent.main.ensure_mountpoint"),
                patch("agent.main.ensure_fstab_entry"),
                patch("agent.main._run_logged_command", side_effect=fake_run_logged_command),
            ):
                result = prepare_dedicated_pbs_datastore_result(
                    "/dev/sdc",
                    "pbo-wd-wxd2da1l1e7c",
                    True,
                    False,
                    AgentSettings(),
                )

        self.assertEqual(result["message"], "Existing dedicated PBS datastore reused.")
        flattened = [" ".join(command) for command in commands]
        self.assertFalse(any("wipefs" in command for command in flattened))
        self.assertFalse(any("sgdisk" in command for command in flattened))
        self.assertFalse(any("parted" in command for command in flattened))
        self.assertFalse(any("mkfs.ext4" in command for command in flattened))

    def test_dedicated_prepare_refuses_unmarked_ext4_without_force(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            mount = base / "WD-WXD2DA1L1E7C" / "pbs-datastore"
            mount.mkdir(parents=True)
            disk = _dedicated_test_disk()

            with (
                patch("agent.main.resolve_disk", return_value=(disk, [disk])),
                patch("agent.main.load_udev_properties", return_value={}),
                patch("agent.main.default_mount_base_path", return_value=base),
                patch("agent.main.shutil.which", return_value="/usr/sbin/proxmox-backup-manager"),
                patch("agent.main._is_mounted_at", return_value=True),
                patch("agent.main._find_pbs_datastore_name_for_path", return_value=None),
                patch("agent.main.ensure_mountpoint"),
                patch("agent.main.ensure_fstab_entry"),
                self.assertRaises(RuntimeError) as raised,
            ):
                prepare_dedicated_pbs_datastore_result(
                    "/dev/sdc",
                    "pbo-wd-wxd2da1l1e7c",
                    True,
                    False,
                    AgentSettings(),
                )

        self.assertIn("no PBO dedicated datastore marker was found", str(raised.exception))

    def test_eject_dedicated_datastore_refuses_when_export_sync_is_running(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mount = Path(temp_dir) / "WD-WXD2DA1L1E7C" / "pbs-datastore"
            mount.mkdir(parents=True)
            with (
                patch("agent.main.default_mount_base_path", return_value=Path(temp_dir)),
                patch("agent.main._assert_safe_pbo_datastore_mount_path"),
                patch("agent.main.shutil.which", return_value="/usr/sbin/proxmox-backup-manager"),
                patch("agent.main._pbs_datastore_has_running_tasks", return_value=False),
                patch("agent.main._pbo_export_sync_job_running", return_value=True),
                self.assertRaises(RuntimeError) as raised,
            ):
                eject_dedicated_pbs_datastore_result(
                    "WD-WXD2DA1L1E7C",
                    "pbo-wd-wxd2da1l1e7c",
                    str(mount),
                    AgentSettings(),
                )

        self.assertIn("sync job", str(raised.exception))

    def test_eject_dedicated_datastore_unmounts_when_idle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            mount = base / "WD-WXD2DA1L1E7C" / "pbs-datastore"
            mount.mkdir(parents=True)
            commands: list[list[str]] = []

            def fake_run_subprocess(command: list[str], timeout_seconds: float) -> SubprocessResult:
                commands.append(command)
                return SubprocessResult(command, 0, "", "")

            with (
                patch("agent.main.default_mount_base_path", return_value=base),
                patch("agent.main._assert_safe_pbo_datastore_mount_path"),
                patch("agent.main.shutil.which", return_value="/usr/sbin/proxmox-backup-manager"),
                patch("agent.main._pbs_datastore_has_running_tasks", return_value=False),
                patch("agent.main._pbo_export_sync_job_running", return_value=False),
                patch("agent.main._find_mount_source", side_effect=["/dev/sdc1", None, None]),
                patch("agent.main.run_subprocess", side_effect=fake_run_subprocess),
            ):
                result = eject_dedicated_pbs_datastore_result(
                    "WD-WXD2DA1L1E7C",
                    "pbo-wd-wxd2da1l1e7c",
                    str(mount),
                    AgentSettings(),
                )

        self.assertTrue(result["ok"])
        self.assertIn(["sync"], commands)
        self.assertTrue(any(command[0] == "umount" and command[1].endswith("pbs-datastore") for command in commands))

    def test_eject_accepts_historical_mount_path_for_canonical_wd_alias(self):
        commands: list[list[str]] = []

        def fake_run_subprocess(command: list[str], timeout_seconds: float) -> SubprocessResult:
            commands.append(command)
            return SubprocessResult(command, 0, "", "")

        with (
            patch("agent.main.default_mount_base_path", return_value=Path("/mnt/pbo")),
            patch("agent.main._assert_safe_pbo_datastore_mount_path"),
            patch("agent.main.shutil.which", return_value="/usr/sbin/proxmox-backup-manager"),
            patch("agent.main._pbs_datastore_has_running_tasks", return_value=False),
            patch("agent.main._pbo_export_sync_job_running", return_value=False),
            patch("agent.main._find_mount_source", side_effect=["/dev/sdc1", None, None]),
            patch("agent.main.run_subprocess", side_effect=fake_run_subprocess),
        ):
            result = eject_dedicated_pbs_datastore_result(
                "WXD2DA1L1E7C",
                "pbo-wd-wxd2da1l1e7c",
                "/mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore",
                AgentSettings(),
            )

        self.assertTrue(result["ok"])
        self.assertTrue(
            any(
                command[0] == "umount"
                and command[1].replace("\\", "/").endswith("WD-WXD2DA1L1E7C/pbs-datastore")
                for command in commands
            )
        )

    def test_expected_pbo_datastore_mount_paths_include_wd_historical_aliases(self):
        with patch("agent.main.default_mount_base_path", return_value=Path("/mnt/pbo")):
            paths = {str(path).replace("\\", "/") for path in _expected_pbo_datastore_mount_paths("WXD2DA1L1E7C")}

        self.assertIn("/mnt/pbo/WXD2DA1L1E7C/pbs-datastore", paths)
        self.assertIn("/mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore", paths)
        self.assertIn("/mnt/pbo/WDC-WXD2DA1L1E7C/pbs-datastore", paths)
        self.assertIn("/mnt/pbo/WDC_WXD2DA1L1E7C/pbs-datastore", paths)

    def test_expected_pbo_datastore_mount_paths_include_decoded_hex_aliases(self):
        with patch("agent.main.default_mount_base_path", return_value=Path("/mnt/pbo")):
            paths = {str(path).replace("\\", "/") for path in _expected_pbo_datastore_mount_paths("575844324441314C31453743")}

        self.assertIn("/mnt/pbo/575844324441314C31453743/pbs-datastore", paths)
        self.assertIn("/mnt/pbo/WXD2DA1L1E7C/pbs-datastore", paths)
        self.assertIn("/mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore", paths)

    def test_eject_refuses_unsafe_mount_paths(self):
        for path in ["/", "/boot", "/boot/efi", "/mnt/datastore/backup-store", "/tmp/WXD2DA1L1E7C/pbs-datastore", "/mnt/pbo/WXD2DA1L1E7C/not-pbs"]:
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                _assert_safe_pbo_datastore_mount_path(Path(path))

    def test_eject_busy_datastore_restarts_pbs_services_when_only_pbs_blocks_mount(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            mount = base / "WD-WXD2DA1L1E7C" / "pbs-datastore"
            mount.mkdir(parents=True)
            commands: list[list[str]] = []

            def fake_run_subprocess(command: list[str], timeout_seconds: float) -> SubprocessResult:
                commands.append(command)
                if command[0] == "umount" and len([item for item in commands if item[0] == "umount"]) == 1:
                    return SubprocessResult(command, 32, "", f"umount: {command[1]}: target is busy.")
                return SubprocessResult(command, 0, "", "")

            fuser_result = SubprocessResult(
                ["fuser", "-vm", str(mount)],
                0,
                "",
                "                     USER        PID ACCESS COMMAND\n"
                f"{mount}:            root     kernel mount\n"
                "                     backup     1234 F.... proxmox-backup-proxy\n",
            )
            with (
                patch("agent.main.default_mount_base_path", return_value=base),
                patch("agent.main._assert_safe_pbo_datastore_mount_path"),
                patch("agent.main.shutil.which", return_value="/usr/sbin/proxmox-backup-manager"),
                patch("agent.main._pbs_datastore_has_running_tasks", return_value=False),
                patch("agent.main._pbo_export_sync_job_running", return_value=False),
                patch("agent.main._find_mount_source", side_effect=["/dev/sdc1", None, None]),
                patch("agent.main._run_fuser_verbose", return_value=fuser_result),
                patch("agent.main.time.sleep"),
                patch("agent.main.run_subprocess", side_effect=fake_run_subprocess),
            ):
                result = eject_dedicated_pbs_datastore_result(
                    "WD-WXD2DA1L1E7C",
                    "pbo-wd-wxd2da1l1e7c",
                    str(mount),
                    AgentSettings(),
                )

        self.assertEqual(result["message"], "External datastore unmounted safely. Disk can be detached.")
        self.assertIn(["systemctl", "stop", "proxmox-backup-proxy.service"], commands)
        self.assertIn(["systemctl", "stop", "proxmox-backup.service"], commands)
        self.assertIn(["systemctl", "start", "proxmox-backup.service"], commands)
        self.assertIn(["systemctl", "start", "proxmox-backup-proxy.service"], commands)

    def test_fuser_parser_ignores_kernel_mount_and_accepts_truncated_pbs_process(self):
        output = (
            "                     USER        PID ACCESS COMMAND\n"
            "/mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore:\n"
            "                     root     kernel mount /mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore\n"
            "                     backup    13053 F.... proxmox-backup-\n"
        )

        self.assertEqual(len(_fuser_process_lines(output)), 1)
        self.assertIn("proxmox-backup-", _fuser_process_lines(output)[0])
        self.assertTrue(all(_is_safe_pbs_fuser_line(line) for line in output.splitlines()))
        self.assertTrue(_only_pbs_services_block_mount(output))

    def test_eject_busy_datastore_with_truncated_pbs_fuser_output_retries_umount(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            mount = base / "WD-WXD2DA1L1E7C" / "pbs-datastore"
            mount.mkdir(parents=True)
            commands: list[list[str]] = []

            def fake_run_subprocess(command: list[str], timeout_seconds: float) -> SubprocessResult:
                commands.append(command)
                if command[0] == "umount" and len([item for item in commands if item[0] == "umount"]) == 1:
                    return SubprocessResult(command, 32, "", f"umount: {command[1]}: target is busy.")
                return SubprocessResult(command, 0, "", "")

            fuser_result = SubprocessResult(
                ["fuser", "-vm", str(mount)],
                0,
                "",
                "                     USER        PID ACCESS COMMAND\n"
                "/mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore:\n"
                "                     root     kernel mount /mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore\n"
                "                     backup    13053 F.... proxmox-backup-\n",
            )
            with (
                patch("agent.main.default_mount_base_path", return_value=base),
                patch("agent.main._assert_safe_pbo_datastore_mount_path"),
                patch("agent.main.shutil.which", return_value="/usr/sbin/proxmox-backup-manager"),
                patch("agent.main._pbs_datastore_has_running_tasks", return_value=False),
                patch("agent.main._pbo_export_sync_job_running", return_value=False),
                patch("agent.main._find_mount_source", side_effect=["/dev/sdc1", None, None]),
                patch("agent.main._run_fuser_verbose", return_value=fuser_result),
                patch("agent.main.time.sleep"),
                patch("agent.main.run_subprocess", side_effect=fake_run_subprocess),
            ):
                result = eject_dedicated_pbs_datastore_result(
                    "WD-WXD2DA1L1E7C",
                    "pbo-wd-wxd2da1l1e7c",
                    str(mount),
                    AgentSettings(),
                )

        self.assertTrue(result["ok"])
        self.assertEqual(len([command for command in commands if command[0] == "umount"]), 2)
        self.assertIn(["systemctl", "stop", "proxmox-backup-proxy.service"], commands)
        self.assertIn(["systemctl", "stop", "proxmox-backup.service"], commands)
        self.assertIn(["systemctl", "start", "proxmox-backup.service"], commands)
        self.assertIn(["systemctl", "start", "proxmox-backup-proxy.service"], commands)

    def test_exfat_coexistence_prepare_returns_loop_backed_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mount = Path(temp_dir)
            target = mount / "proxmox-backup-orchestrator" / "WD-WXD2DA1L1E7C" / "pbs-datastore"
            settings = AgentSettings(loop_datastore_size_gb=50)
            commands: list[list[str]] = []

            def fake_run_subprocess(command: list[str], timeout_seconds: float) -> SubprocessResult:
                commands.append(command)
                return SubprocessResult(command, 0, "", "")

            with (
                patch("agent.main.filesystem_type_for_path", return_value="exfat"),
                patch("agent.main._find_mount_source", return_value=None),
                patch("agent.main.run_subprocess", side_effect=fake_run_subprocess),
            ):
                result = prepare_external_datastore_result(str(mount), str(target), "coexistence", settings)

        self.assertTrue(result["loop_backed"])
        self.assertEqual(
            result["actual_target_path"],
            str((mount / "proxmox-backup-orchestrator" / "WD-WXD2DA1L1E7C" / "loop-pbs-datastore").resolve()),
        )
        self.assertEqual(result["target_path"], result["actual_target_path"])
        self.assertEqual(
            result["loop_image_path"],
            str((mount / "proxmox-backup-orchestrator" / "WD-WXD2DA1L1E7C" / "images" / "pbs-export.ext4").resolve()),
        )
        self.assertIn(["truncate", "-s", "50G", result["loop_image_path"]], commands)

    def test_ext4_coexistence_prepare_keeps_direct_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mount = Path(temp_dir)
            target = mount / "proxmox-backup-orchestrator" / "WD-WXD2DA1L1E7C" / "pbs-datastore"
            with patch("agent.main.filesystem_type_for_path", return_value="ext4"):
                result = prepare_external_datastore_result(str(mount), str(target), "coexistence", AgentSettings())

        self.assertFalse(result["loop_backed"])
        self.assertEqual(result["target_path"], str(target.resolve()))
        self.assertEqual(result["actual_target_path"], str(target.resolve()))
        self.assertIsNone(result["loop_image_path"])

    def test_new_target_datastore_create_does_not_use_reuse_flag(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            calls = self._run_export_and_capture_calls(target)

        create_command, create_timeout = self._find_datastore_create_call(calls)
        self.assertNotIn("--reuse-datastore", create_command)
        self.assertEqual(create_timeout, 14400)

    def test_initialized_target_datastore_create_uses_reuse_flag(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            (target / ".chunks").mkdir()
            calls = self._run_export_and_capture_calls(target, export_timeout_seconds=20000)

        create_command, create_timeout = self._find_datastore_create_call(calls)
        self.assertIn("--reuse-datastore", create_command)
        self.assertIn("true", create_command)
        self.assertEqual(create_timeout, 20000)

    def test_chunks_directory_marks_path_initialized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            self.assertFalse(is_initialized_pbs_datastore_path(target))

            (target / ".chunks").mkdir()
            self.assertTrue(is_initialized_pbs_datastore_path(target))

    def test_create_failure_explains_new_datastore_initialization(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            settings = AgentSettings(
                pbs_api_url="https://pbs.example.test:8007",
                pbs_auth_id="root@pam!token",
                pbs_auth_secret="secret",
                export_timeout_seconds=7200,
                datastore_create_timeout_seconds=14400,
            )

            def fake_run_subprocess(command: list[str], timeout_seconds: float) -> SubprocessResult:
                if command[1:3] == ["datastore", "list"]:
                    stdout = json.dumps([{"name": "source-store", "path": "/srv/source-store"}])
                    return SubprocessResult(command, 0, stdout, "")
                if command[1:3] == ["datastore", "create"]:
                    return SubprocessResult(command, 1, "", "unable to open existing chunk store path")
                return SubprocessResult(command, 0, "", "")

            with (
                patch("agent.main.shutil.which", return_value="/usr/sbin/proxmox-backup-manager"),
                patch("agent.main.filesystem_type_for_path", return_value="exfat"),
                patch("agent.main.run_subprocess", side_effect=fake_run_subprocess),
                self.assertRaises(RuntimeError) as raised,
            ):
                run_external_export_result(str(target), "source-store", "coexistence", settings)

        message = str(raised.exception)
        self.assertIn("new datastore initialization", message)
        self.assertIn("filesystem=exfat", message)
        self.assertIn("datastore create", message)
        self.assertNotIn("--reuse-datastore", message)

    def test_existing_loop_mount_backed_by_expected_image_is_reused(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "pbs-export.ext4"
            image.touch()
            mount = Path(temp_dir) / "loop-pbs-datastore"
            mount.mkdir()
            stdout_logs: list[str] = []

            with (
                patch("agent.main._find_mount_source", return_value="/dev/loop0"),
                patch("agent.main.loop_backing_file", return_value=image),
            ):
                reused = _ensure_loop_image_mounted(image, mount, [], stdout_logs, [])

        self.assertTrue(reused)
        self.assertTrue(any("Reusing existing loop-backed datastore mount" in item for item in stdout_logs))

    def test_existing_loop_mount_backed_by_different_image_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "pbs-export.ext4"
            other_image = Path(temp_dir) / "other.ext4"
            image.touch()
            other_image.touch()
            mount = Path(temp_dir) / "loop-pbs-datastore"
            mount.mkdir()

            with (
                patch("agent.main._find_mount_source", return_value="/dev/loop0"),
                patch("agent.main.loop_backing_file", return_value=other_image),
                self.assertRaises(RuntimeError) as raised,
            ):
                _ensure_loop_image_mounted(image, mount, [], [], [])

        self.assertIn("already mounted from `/dev/loop0`", str(raised.exception))
        self.assertIn("backed by", str(raised.exception))
        self.assertIn("other.ext4", str(raised.exception))

    def test_existing_non_loop_mount_source_fails_unless_it_matches_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "pbs-export.ext4"
            image.touch()
            mount = Path(temp_dir) / "loop-pbs-datastore"
            mount.mkdir()

            with (
                patch("agent.main._find_mount_source", return_value="/dev/sdb1"),
                patch("agent.main.loop_backing_file", return_value=None),
                self.assertRaises(RuntimeError),
            ):
                _ensure_loop_image_mounted(image, mount, [], [], [])

            stdout_logs: list[str] = []
            with (
                patch("agent.main._find_mount_source", return_value=str(image)),
                patch("agent.main.loop_backing_file", return_value=None),
            ):
                reused = _ensure_loop_image_mounted(image, mount, [], stdout_logs, [])

        self.assertTrue(reused)
        self.assertTrue(any("Reusing existing loop-backed datastore mount" in item for item in stdout_logs))

    def test_find_mount_source_uses_first_valid_duplicate_line(self):
        with (
            patch("agent.main.shutil.which", return_value="/usr/bin/findmnt"),
            patch("agent.main.run_command", return_value="\n/dev/loop0\n/dev/loop0\n"),
        ):
            self.assertEqual(_find_mount_source(Path("/mnt/example")), "/dev/loop0")

    def test_loop_backing_file_uses_long_losetup_output_form(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "pbs-export.ext4"
            image.touch()
            commands: list[list[str]] = []

            def fake_run_command(command: list[str]) -> str:
                commands.append(command)
                return f"  {image}\n"

            with (
                patch("agent.main.shutil.which", return_value="/usr/sbin/losetup"),
                patch("agent.main.run_command", side_effect=fake_run_command),
            ):
                self.assertEqual(loop_backing_file("/dev/loop0"), image.resolve())

        self.assertEqual(
            commands,
            [["/usr/sbin/losetup", "--noheadings", "--output", "BACK-FILE", "/dev/loop0"]],
        )

    def test_loop_backing_file_falls_back_to_short_output_form(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Path(temp_dir) / "pbs-export.ext4"
            image.touch()
            commands: list[list[str]] = []

            def fake_run_command(command: list[str]) -> str:
                commands.append(command)
                if "--noheadings" in command:
                    raise RuntimeError("unsupported option")
                return f"{image}\n"

            with (
                patch("agent.main.shutil.which", return_value="/usr/sbin/losetup"),
                patch("agent.main.run_command", side_effect=fake_run_command),
            ):
                self.assertEqual(loop_backing_file("/dev/loop0"), image.resolve())

        self.assertEqual(
            commands,
            [
                ["/usr/sbin/losetup", "--noheadings", "--output", "BACK-FILE", "/dev/loop0"],
                ["/usr/sbin/losetup", "-n", "-O", "BACK-FILE", "/dev/loop0"],
            ],
        )

    def test_loop_backing_file_returns_none_without_backing_output(self):
        with (
            patch("agent.main.shutil.which", return_value="/usr/sbin/losetup"),
            patch("agent.main.run_command", return_value="\n\n"),
        ):
            self.assertIsNone(loop_backing_file("/dev/loop0"))

    def test_export_cleans_stale_temp_sync_jobs_and_remotes_before_retry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir).resolve()
            calls: list[list[str]] = []

            def fake_run_subprocess(command: list[str], timeout_seconds: float) -> SubprocessResult:
                calls.append(command)
                if command[1:3] == ["datastore", "list"]:
                    stdout = json.dumps(
                        [
                            {"name": "source-store", "path": "/srv/source-store"},
                            {"name": "pbo-wd-wxd2da1l1e7c", "path": str(target)},
                        ]
                    )
                    return SubprocessResult(command, 0, stdout, "")
                if command[1:3] == ["sync-job", "list"]:
                    return SubprocessResult(command, 0, json.dumps([{"id": "pbo-export-sync-old"}]), "")
                if command[1:3] == ["remote", "list"]:
                    return SubprocessResult(command, 0, json.dumps([{"name": "pbo-export-remote-old"}]), "")
                return SubprocessResult(command, 0, "", "")

            settings = AgentSettings(
                pbs_api_url="https://pbs.example.test:8007",
                pbs_auth_id="root@pam!token",
                pbs_auth_secret="secret",
            )

            with (
                patch("agent.main.shutil.which", return_value="/usr/sbin/proxmox-backup-manager"),
                patch("agent.main.filesystem_type_for_path", return_value="ext4"),
                patch("agent.main._is_sync_job_running", return_value=False),
                patch("agent.main.run_subprocess", side_effect=fake_run_subprocess),
            ):
                result = run_external_export_result(
                    str(target),
                    "source-store",
                    "dedicated",
                    settings,
                    target_datastore_name="pbo-wd-wxd2da1l1e7c",
                    persist_target_datastore=True,
                )

        self.assertTrue(result["success"])
        self.assertIn(["/usr/sbin/proxmox-backup-manager", "sync-job", "remove", "pbo-export-sync-old"], calls)
        self.assertIn(["/usr/sbin/proxmox-backup-manager", "remote", "remove", "pbo-export-remote-old"], calls)
        self.assertNotIn(["/usr/sbin/proxmox-backup-manager", "datastore", "remove", "pbo-wd-wxd2da1l1e7c"], calls)

    def test_export_refuses_cleanup_when_old_temp_sync_job_is_running(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir).resolve()

            def fake_run_subprocess(command: list[str], timeout_seconds: float) -> SubprocessResult:
                if command[1:3] == ["datastore", "list"]:
                    stdout = json.dumps(
                        [
                            {"name": "source-store", "path": "/srv/source-store"},
                            {"name": "pbo-wd-wxd2da1l1e7c", "path": str(target)},
                        ]
                    )
                    return SubprocessResult(command, 0, stdout, "")
                if command[1:3] == ["sync-job", "list"]:
                    return SubprocessResult(command, 0, json.dumps([{"id": "pbo-export-sync-old"}]), "")
                return SubprocessResult(command, 0, "", "")

            settings = AgentSettings(
                pbs_api_url="https://pbs.example.test:8007",
                pbs_auth_id="root@pam!token",
                pbs_auth_secret="secret",
            )

            with (
                patch("agent.main.shutil.which", return_value="/usr/sbin/proxmox-backup-manager"),
                patch("agent.main.filesystem_type_for_path", return_value="ext4"),
                patch("agent.main._is_sync_job_running", return_value=True),
                patch("agent.main.run_subprocess", side_effect=fake_run_subprocess),
                self.assertRaises(RuntimeError) as raised,
            ):
                run_external_export_result(
                    str(target),
                    "source-store",
                    "dedicated",
                    settings,
                    target_datastore_name="pbo-wd-wxd2da1l1e7c",
                    persist_target_datastore=True,
                )

        self.assertIn("appears to be running", str(raised.exception))

    def test_admin_cleanup_refuses_active_task(self):
        settings = AgentSettings()

        with (
            patch("agent.main.shutil.which", return_value="/usr/sbin/proxmox-backup-manager"),
            patch("agent.main._list_pbs_resource_names", side_effect=[["pbo-export-sync-active"], []]),
            patch("agent.main._is_sync_job_running", return_value=True),
            patch("agent.main._pbo_operation_lock_paths", return_value=[]),
        ):
            result = cleanup_external_export_objects_result(settings)

        self.assertFalse(result["ok"])
        self.assertTrue(result["active"])
        self.assertIn("Refusing cleanup", result["message"])

    def test_admin_cleanup_removes_only_stale_temp_jobs_and_remotes(self):
        settings = AgentSettings()
        commands: list[list[str]] = []

        def fake_run(command: list[str], timeout_seconds: float) -> SubprocessResult:
            commands.append(command)
            return SubprocessResult(command, 0, "", "")

        with (
            patch("agent.main.shutil.which", return_value="/usr/sbin/proxmox-backup-manager"),
            patch("agent.main._list_pbs_resource_names", side_effect=[["pbo-export-sync-stale"], ["pbo-export-remote-stale"]]),
            patch("agent.main._is_sync_job_running", return_value=False),
            patch("agent.main._pbo_operation_lock_paths", return_value=[]),
            patch("agent.main.run_subprocess", side_effect=fake_run),
        ):
            result = cleanup_external_export_objects_result(settings)

        self.assertTrue(result["ok"])
        self.assertIn(["/usr/sbin/proxmox-backup-manager", "sync-job", "remove", "pbo-export-sync-stale"], commands)
        self.assertIn(["/usr/sbin/proxmox-backup-manager", "remote", "remove", "pbo-export-remote-stale"], commands)
        self.assertFalse(any(command[1:3] == ["datastore", "remove"] for command in commands))

    def test_admin_status_reports_stale_temp_objects(self):
        settings = AgentSettings()
        with (
            patch("agent.main.shutil.which", return_value="/usr/sbin/proxmox-backup-manager"),
            patch("agent.main._list_pbs_resource_names", side_effect=[["pbo-export-sync-stale"], ["pbo-export-remote-stale"]]),
            patch("agent.main._is_sync_job_running", return_value=False),
            patch("agent.main._pbo_operation_lock_paths", return_value=[]),
        ):
            result = external_export_objects_status(settings)

        self.assertFalse(result["active"])
        self.assertEqual([item["kind"] for item in result["items"]], ["sync-job", "remote"])

    def _run_export_and_capture_calls(
        self,
        target: Path,
        *,
        export_timeout_seconds: float = 7200,
    ) -> list[tuple[list[str], float]]:
        calls: list[tuple[list[str], float]] = []

        def fake_run_subprocess(command: list[str], timeout_seconds: float) -> SubprocessResult:
            calls.append((command, timeout_seconds))
            if command[1:3] == ["datastore", "list"]:
                stdout = json.dumps([{"name": "source-store", "path": "/srv/source-store"}])
                return SubprocessResult(command, 0, stdout, "")
            return SubprocessResult(command, 0, "", "")

        settings = AgentSettings(
            pbs_api_url="https://pbs.example.test:8007",
            pbs_auth_id="root@pam!token",
            pbs_auth_secret="secret",
            export_timeout_seconds=export_timeout_seconds,
            datastore_create_timeout_seconds=14400,
        )

        with (
            patch("agent.main.shutil.which", return_value="/usr/sbin/proxmox-backup-manager"),
            patch("agent.main.filesystem_type_for_path", return_value="exfat"),
            patch("agent.main.run_subprocess", side_effect=fake_run_subprocess),
        ):
            result = run_external_export_result(str(target), "source-store", "coexistence", settings)

        self.assertTrue(result["success"])
        return calls

    def _find_datastore_create_call(
        self,
        calls: list[tuple[list[str], float]],
    ) -> tuple[list[str], float]:
        for command, timeout in calls:
            if command[1:3] == ["datastore", "create"]:
                return command, timeout
        raise AssertionError("datastore create command was not called")


def _dedicated_test_disk() -> dict[str, object]:
    return {
        "name": "sdc",
        "kname": "sdc",
        "path": "/dev/sdc",
        "type": "disk",
        "serial": "WD-WXD2DA1L1E7C",
        "size": "3.6T",
        "mountpoint": None,
        "children": [
            {
                "name": "sdc1",
                "kname": "sdc1",
                "path": "/dev/sdc1",
                "type": "part",
                "serial": None,
                "size": "3.6T",
                "mountpoint": None,
                "fstype": "ext4",
                "children": [],
            }
        ],
    }
