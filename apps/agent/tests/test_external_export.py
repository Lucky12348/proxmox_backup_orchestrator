import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from agent.main import (
    AgentSettings,
    SubprocessResult,
    _ensure_loop_image_mounted,
    _find_mount_source,
    bytes_to_gb,
    is_initialized_pbs_datastore_path,
    loop_backing_file,
    prepare_dedicated_pbs_datastore_result,
    prepare_external_datastore_result,
    run_external_export_result,
)


class ExternalExportDatastoreCreateTests(TestCase):
    def test_bytes_to_gb_parses_human_readable_sizes(self):
        self.assertGreater(bytes_to_gb("3.6T"), 3000)
        self.assertGreaterEqual(bytes_to_gb("750G"), 749)
        self.assertLessEqual(bytes_to_gb("750G"), 751)
        self.assertLess(bytes_to_gb("16M"), 1)
        self.assertGreaterEqual(bytes_to_gb(4000000000000), 3724)
        self.assertLessEqual(bytes_to_gb(4000000000000), 3726)

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
                AgentSettings(),
            )

        message = str(raised.exception)
        self.assertIn("raw size=`16M`", message)
        self.assertIn("parsed size=`0 GB`", message)
        self.assertIn("minimum=`32 GB`", message)

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
