from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from agent.main import (
    AgentSettings,
    _maintenance_restart_http_service,
    _maintenance_restart_http_service_command,
    maintenance_update_result,
)


class MaintenanceRestartCommandTests(TestCase):
    def test_uses_systemd_run_when_available(self):
        settings = AgentSettings(http_service_name="proxmox-backup-orchestrator-agent-http.service")
        with patch("agent.main.shutil.which", return_value="/usr/bin/systemd-run"):
            command = _maintenance_restart_http_service_command(settings)

        self.assertEqual(
            command,
            [
                "systemd-run",
                "--on-active=10",
                "--unit",
                "pbo-agent-http-restart",
                "systemctl",
                "restart",
                "proxmox-backup-orchestrator-agent-http.service",
            ],
        )

    def test_falls_back_to_try_restart_without_systemd_run(self):
        settings = AgentSettings(http_service_name="proxmox-backup-orchestrator-pbs-agent-http.service")
        with patch("agent.main.shutil.which", return_value=None):
            command = _maintenance_restart_http_service_command(settings)

        self.assertEqual(
            command,
            ["systemctl", "try-restart", "proxmox-backup-orchestrator-pbs-agent-http.service", "--no-block"],
        )


class MaintenanceRestartServiceTests(TestCase):
    def test_missing_service_name_fails_without_running_a_command(self):
        settings = AgentSettings(http_service_name="")
        with patch("agent.main.run_subprocess_with_cwd") as run_mock:
            result = _maintenance_restart_http_service(Path("/tmp/repo"), settings)

        run_mock.assert_not_called()
        self.assertEqual(result["return_code"], 1)
        self.assertIn("AGENT_HTTP_SERVICE_NAME is not configured", result["stderr"])

    def test_missing_systemctl_fails_without_running_a_command(self):
        settings = AgentSettings(http_service_name="proxmox-backup-orchestrator-agent-http.service")
        with (
            patch("agent.main.shutil.which", return_value=None),
            patch("agent.main.run_subprocess_with_cwd") as run_mock,
        ):
            result = _maintenance_restart_http_service(Path("/tmp/repo"), settings)

        run_mock.assert_not_called()
        self.assertEqual(result["return_code"], 1)
        self.assertIn("systemctl is not available", result["stderr"])


class MaintenanceUpdateResultTests(TestCase):
    def test_successful_pull_triggers_service_restart(self):
        settings = AgentSettings(
            repo_path="/tmp/repo",
            http_service_name="proxmox-backup-orchestrator-agent-http.service",
        )
        up_to_date_status = {
            "branch": "main",
            "local_commit": "abc123",
            "remote_commit": "abc123",
            "status": "up_to_date",
            "error": None,
            "logs": [],
        }
        stale_status = {**up_to_date_status, "local_commit": "old111", "status": "update_available"}
        pull_logs = [{"command": "git pull --ff-only", "stdout": "ok", "stderr": None, "return_code": 0}]
        restart_result = {"command": "systemctl restart ...", "stdout": "scheduled", "stderr": None, "return_code": 0}

        with (
            patch("agent.main._maintenance_git_status", side_effect=[stale_status, up_to_date_status]),
            patch("agent.main._maintenance_run_sequence", return_value=pull_logs),
            patch("agent.main._maintenance_restart_http_service", return_value=restart_result) as restart_mock,
        ):
            result = maintenance_update_result(settings)

        restart_mock.assert_called_once()
        self.assertTrue(result["ok"])
        self.assertIn(restart_result, result["logs"])

    def test_restart_failure_marks_update_as_failed(self):
        settings = AgentSettings(
            repo_path="/tmp/repo",
            http_service_name="proxmox-backup-orchestrator-agent-http.service",
        )
        up_to_date_status = {
            "branch": "main",
            "local_commit": "abc123",
            "remote_commit": "abc123",
            "status": "up_to_date",
            "error": None,
            "logs": [],
        }
        stale_status = {**up_to_date_status, "local_commit": "old111", "status": "update_available"}
        pull_logs = [{"command": "git pull --ff-only", "stdout": "ok", "stderr": None, "return_code": 0}]
        restart_result = {
            "command": "systemctl restart ...",
            "stdout": None,
            "stderr": "AGENT_HTTP_SERVICE_NAME is not configured",
            "return_code": 1,
        }

        with (
            patch("agent.main._maintenance_git_status", side_effect=[stale_status, up_to_date_status]),
            patch("agent.main._maintenance_run_sequence", return_value=pull_logs),
            patch("agent.main._maintenance_restart_http_service", return_value=restart_result),
        ):
            result = maintenance_update_result(settings)

        self.assertFalse(result["ok"])
        self.assertEqual(result["action_status"], "error")
