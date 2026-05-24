from unittest import TestCase
from unittest.mock import patch

from app.core.config import Settings
from app.services.notifications import NotificationService


class NotificationServiceTests(TestCase):
    def test_status_masks_topic_and_omits_password(self):
        service = NotificationService(
            Settings(
                notifications_enabled=True,
                ntfy_base_url="https://ntfy.example.test",
                ntfy_topic="super-secret-topic",
                ntfy_username="pbo",
                ntfy_password="secret-password",
            )
        )

        status = service.status()

        self.assertEqual(status.topic, "supe...opic")
        self.assertEqual(status.username, "pbo")
        self.assertFalse(hasattr(status, "password"))

    def test_send_catches_ntfy_errors(self):
        service = NotificationService(
            Settings(
                notifications_enabled=True,
                ntfy_base_url="https://ntfy.example.test",
                ntfy_topic="topic",
                ntfy_username="pbo",
                ntfy_password="secret-password",
            )
        )

        with (
            patch("app.services.notifications.httpx.post", side_effect=RuntimeError("network secret-password")),
            self.assertLogs("app.services.notifications", level="WARNING") as logs,
        ):
            sent = service.send("title", "message")

        self.assertFalse(sent)
        self.assertIn("network ***", "\n".join(logs.output))
        self.assertNotIn("secret-password", "\n".join(logs.output))
