from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from app_maintenance_agent.main import _env_file_check_command, _notification_env_preflight_command, _run


class EnvPreservationTests(TestCase):
    def test_existing_env_is_preserved_exactly(self):
        with TemporaryDirectory() as directory:
            repo = Path(directory)
            env_file = repo / ".env"
            original = (
                "NOTIFICATIONS_ENABLED=true\n"
                "NTFY_BASE_URL=https://ntfy.example.test\n"
                "NTFY_USERNAME=pbo\n"
                "NTFY_PASSWORD=secret value with spaces\n"
            )
            env_file.write_text(original, encoding="utf-8")
            (repo / ".env.example").write_text("NOTIFICATIONS_ENABLED=false\n", encoding="utf-8")

            result = _run(repo, _env_file_check_command(), 1)

            self.assertEqual(result["return_code"], 0)
            self.assertEqual(result["stdout"], ".env preserved")
            self.assertEqual(env_file.read_text(encoding="utf-8"), original)

    def test_missing_env_is_created_from_template_once(self):
        with TemporaryDirectory() as directory:
            repo = Path(directory)
            template = "NOTIFICATIONS_ENABLED=true\nNTFY_BASE_URL=https://ntfy.example.test\n"
            (repo / ".env.example").write_text(template, encoding="utf-8")

            created = _run(repo, _env_file_check_command(), 1)
            preserved = _run(repo, _env_file_check_command(), 1)

            self.assertEqual(created["return_code"], 0)
            self.assertEqual(created["stdout"], ".env created from template")
            self.assertEqual(preserved["stdout"], ".env preserved")
            self.assertEqual((repo / ".env").read_text(encoding="utf-8"), template)

    def test_notification_preflight_fails_when_enabled_values_are_missing(self):
        with TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / ".env").write_text("NOTIFICATIONS_ENABLED=true\nNTFY_BASE_URL=https://ntfy.sh\n", encoding="utf-8")

            result = _run(repo, _notification_env_preflight_command(), 1)

            self.assertEqual(result["return_code"], 1)
            self.assertIn("NTFY_TOPIC", result["stderr"])
            self.assertIn("NTFY_USERNAME", result["stderr"])
            self.assertIn("NTFY_PASSWORD", result["stderr"])
