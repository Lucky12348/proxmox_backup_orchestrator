import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent import server
from agent.main import (
    EJECT_NOT_FINISHED_ERROR_CODE,
    AgentSettings,
    EjectNotFinishedError,
    SubprocessResult,
    _dirty_writeback_summary,
    build_command_failure_payload,
    eject_dedicated_pbs_datastore_result,
)

AGENT_ROOT = Path(__file__).resolve().parents[1]
MEMINFO = "MemTotal:       16384000 kB\nDirty:           2097152 kB\nWriteback:         51200 kB\n"


class _SlowSyncProcess:
    """Fake `sync -f`: still flushing for `busy_ticks` waits, then done (or never)."""

    def __init__(self, clock: list[float], busy_ticks: int | None, returncode: int = 0) -> None:
        self.clock = clock
        self.busy_ticks = busy_ticks
        self.returncode = None
        self._final_returncode = returncode
        self.communicate_timeouts: list[float] = []
        self.killed = False

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        self.communicate_timeouts.append(timeout)
        if self.busy_ticks is None or self.busy_ticks > 0:
            if self.busy_ticks is not None:
                self.busy_ticks -= 1
            self.clock[0] += timeout
            raise subprocess.TimeoutExpired(["sync"], timeout)
        self.returncode = self._final_returncode
        return "", ""

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        return -9


class EjectFlushTests(TestCase):
    def _eject(self, process: _SlowSyncProcess, clock: list[float], timeout_seconds: float = 1800):
        commands: list[list[str]] = []
        popen_commands: list[list[str]] = []

        def fake_run_subprocess(command: list[str], timeout_seconds: float) -> SubprocessResult:
            commands.append(command)
            return SubprocessResult(command, 0, "", "")

        def fake_popen(command, **kwargs):
            popen_commands.append(command)
            return process

        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            mount = base / "WD-WXD2DA1L1E7C" / "pbs-datastore"
            mount.mkdir(parents=True)
            meminfo = base / "meminfo"
            meminfo.write_text(MEMINFO, encoding="utf-8")
            with (
                patch("agent.main.default_mount_base_path", return_value=base),
                patch("agent.main._assert_safe_pbo_datastore_mount_path"),
                patch("agent.main.shutil.which", return_value="/usr/sbin/proxmox-backup-manager"),
                patch("agent.main._pbs_datastore_has_running_tasks", return_value=False),
                patch("agent.main._pbo_export_sync_job_running", return_value=False),
                patch("agent.main._find_mount_source", side_effect=["/dev/sdc1", None, None]),
                patch("agent.main.run_subprocess", side_effect=fake_run_subprocess),
                patch("agent.main.subprocess.Popen", side_effect=fake_popen),
                patch("agent.main.time.monotonic", side_effect=lambda: clock[0]),
                patch("agent.main.PROC_MEMINFO_PATH", meminfo),
                patch("agent.main.post_progress_callback") as callback,
            ):
                try:
                    result = eject_dedicated_pbs_datastore_result(
                        "WD-WXD2DA1L1E7C",
                        "pbo-wd-wxd2da1l1e7c",
                        str(mount),
                        AgentSettings(eject_sync_timeout_seconds=timeout_seconds),
                        callback_run_id=42,
                        callback_url="http://app/api/v1",
                        callback_token="token",
                    )
                except EjectNotFinishedError as exc:
                    result = exc
        return result, commands, popen_commands, callback, str(mount.resolve(strict=False))

    def test_targeted_sync_runs_before_umount_and_logs_progress_every_15_seconds(self):
        clock = [0.0]
        process = _SlowSyncProcess(clock, busy_ticks=2)

        result, commands, popen_commands, callback, mount = self._eject(process, clock)

        self.assertTrue(result["ok"])
        self.assertEqual(popen_commands, [["sync", "-f", mount]])
        self.assertEqual(process.communicate_timeouts, [15.0, 15.0, 15.0])
        progress_lines = [line for line in result["stdout_log"].splitlines() if line.startswith("Écriture en cours")]
        self.assertEqual(len(progress_lines), 2)
        self.assertIn("Dirty 2.0 GiB, Writeback 50.0 MiB", progress_lines[0])
        self.assertTrue(any(command[0] == "umount" for command in commands))
        posted_steps = [call.args[3]["step"] for call in callback.call_args_list]
        self.assertEqual(posted_steps.count("eject_flush"), 4)  # start, 2 progress lines, done

    def test_timeout_does_not_unmount_and_reports_do_not_unplug(self):
        clock = [0.0]
        process = _SlowSyncProcess(clock, busy_ticks=None)

        result, commands, _, callback, _ = self._eject(process, clock, timeout_seconds=40)

        self.assertIsInstance(result, EjectNotFinishedError)
        self.assertEqual(result.error_code, EJECT_NOT_FINISHED_ERROR_CODE)
        self.assertIn("Éjection non terminée", str(result))
        self.assertIn("NE PAS débrancher le disque", str(result))
        self.assertTrue(process.killed)
        self.assertFalse(any(command[0] == "umount" for command in commands))
        # Waits capped by the remaining time: 15 + 15 + 10 = 40 s.
        self.assertEqual(process.communicate_timeouts, [15.0, 15.0, 10.0])
        self.assertIn("Écriture en cours", result.stdout_log)
        self.assertEqual(callback.call_args_list[-1].args[3]["step"], "eject_not_finished")

    def test_failed_sync_does_not_unmount(self):
        clock = [0.0]
        process = _SlowSyncProcess(clock, busy_ticks=0, returncode=1)

        with self.assertRaises(RuntimeError) as raised:
            result, commands, *_ = self._eject(process, clock)
            if isinstance(result, Exception):
                raise result
        self.assertIn("Failed to flush", str(raised.exception))

    def test_failure_payload_carries_error_code_and_progress_log(self):
        payload = build_command_failure_payload(
            "eject-dedicated-pbs-datastore",
            EjectNotFinishedError("Éjection non terminée", stdout_log="Écriture en cours"),
        )
        self.assertEqual(payload["error_code"], EJECT_NOT_FINISHED_ERROR_CODE)
        self.assertEqual(payload["stdout_log"], "Écriture en cours")
        self.assertNotIn("error_code", build_command_failure_payload("x", RuntimeError("boom")))

    def test_dirty_writeback_summary_handles_unreadable_meminfo(self):
        with patch("agent.main.PROC_MEMINFO_PATH", Path(tempfile.gettempdir()) / "pbo-no-such-meminfo"):
            self.assertEqual(_dirty_writeback_summary(), "Dirty/Writeback indisponibles")


class EjectSyncTimeoutSettingTests(TestCase):
    def _timeout(self, env_value: str | None) -> str:
        env = {key: value for key, value in os.environ.items() if key != "AGENT_EJECT_SYNC_TIMEOUT_SECONDS"}
        if env_value is not None:
            env["AGENT_EJECT_SYNC_TIMEOUT_SECONDS"] = env_value
        env["PYTHONPATH"] = str(AGENT_ROOT / "src")
        # Settings defaults are read at import time, so check in a fresh interpreter.
        result = subprocess.run(
            [sys.executable, "-c", "from agent.main import AgentSettings; print(AgentSettings().eject_sync_timeout_seconds)"],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def test_default_is_1800_seconds(self):
        self.assertEqual(self._timeout(None), "1800.0")

    def test_configurable_from_environment(self):
        self.assertEqual(self._timeout("3600"), "3600.0")


class EjectEndpointTests(TestCase):
    def setUp(self):
        settings = AgentSettings(server_token="test-token")
        server.app.dependency_overrides[server.get_settings] = lambda: settings
        self.client = TestClient(server.app)

    def tearDown(self):
        server.app.dependency_overrides.clear()

    def test_endpoint_returns_error_code_and_forwards_callback(self):
        with patch(
            "agent.server.eject_dedicated_pbs_datastore_result",
            side_effect=EjectNotFinishedError("Éjection non terminée. NE PAS débrancher le disque."),
        ) as eject:
            response = self.client.post(
                "/eject-dedicated-pbs-datastore",
                headers={"X-Agent-Token": "test-token"},
                json={
                    "serial": "WD-WXD2DA1L1E7C",
                    "datastore_name": "pbo-wd-wxd2da1l1e7c",
                    "mount_path": "/mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore",
                    "callback_run_id": 7,
                    "callback_url": "http://app/api/v1",
                    "callback_token": "cb",
                },
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error_code"], EJECT_NOT_FINISHED_ERROR_CODE)
        self.assertEqual(eject.call_args.kwargs["callback_run_id"], 7)
