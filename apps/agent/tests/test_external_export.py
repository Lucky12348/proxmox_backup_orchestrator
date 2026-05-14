import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from agent.main import (
    AgentSettings,
    SubprocessResult,
    is_initialized_pbs_datastore_path,
    run_external_export_result,
)


class ExternalExportDatastoreCreateTests(TestCase):
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
