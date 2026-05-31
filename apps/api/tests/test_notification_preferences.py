from unittest import TestCase

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.services.notifications import (
    get_notification_preferences,
    reset_notification_preferences,
    update_notification_preferences,
)


class NotificationPreferencesTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_preferences_override_non_secret_event_toggles(self):
        preferences = update_notification_preferences(
            self.session,
            {
                "notifications_enabled_override": False,
                "notify_on_backup_success": False,
                "notify_on_planned_backup_missed": False,
                "low_coverage_threshold_percent": 75,
                "disk_detection_notify_cooldown_seconds": 600,
            },
        )

        self.assertFalse(preferences.notifications_enabled_override)
        self.assertFalse(preferences.events["backup_success"])
        self.assertFalse(preferences.events["planned_backup_missed"])
        self.assertEqual(preferences.low_coverage_threshold_percent, 75)
        self.assertEqual(preferences.disk_detection_notify_cooldown_seconds, 600)

    def test_reset_preferences_returns_environment_defaults(self):
        update_notification_preferences(self.session, {"notify_on_backup_success": False})

        preferences = reset_notification_preferences(self.session)

        self.assertTrue(preferences.events["backup_success"])
        self.assertIsNone(preferences.notifications_enabled_override)
        self.assertEqual(get_notification_preferences(self.session).events["backup_success"], True)
        self.assertEqual(preferences.source, "environment/server value")

    def test_database_preferences_report_override_source(self):
        preferences = update_notification_preferences(self.session, {"notify_on_backup_success": False})

        self.assertEqual(preferences.source, "database override")
