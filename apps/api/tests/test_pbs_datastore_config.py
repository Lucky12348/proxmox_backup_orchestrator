import os
import subprocess
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from pydantic import ValidationError

from app.api.routes.integrations_pbs import DATASTORE_NOT_CONFIGURED_MESSAGE, get_pbs_status
from app.core.config import get_settings
from app.schemas.planning import ScheduledBackupEventCreate, ScheduledBackupEventUpdate

API_ROOT = Path(__file__).resolve().parents[1]


class PbsDatastoreDefaultTests(TestCase):
    def _settings_value(self, env_value: str | None) -> str:
        env = {key: value for key, value in os.environ.items() if key != "PBS_DATASTORE"}
        if env_value is not None:
            env["PBS_DATASTORE"] = env_value
        # Settings defaults are read at import time, so check in a fresh interpreter.
        result = subprocess.run(
            [sys.executable, "-c", "from app.core.config import Settings; print(repr(Settings().pbs_datastore))"],
            cwd=API_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def test_no_datastore_name_is_assumed_when_unset(self):
        self.assertEqual(self._settings_value(None), "''")

    def test_operator_chooses_the_datastore_name(self):
        self.assertEqual(self._settings_value(" store8to "), "'store8to'")


class PbsStatusDatastoreTests(TestCase):
    def _status(self, datastore: str):
        settings = replace(get_settings(), pbs_datastore=datastore)
        sync_state = SimpleNamespace(last_sync_at=None, sync_running=False, last_error=None)
        with (
            patch("app.api.routes.integrations_pbs.get_settings", return_value=settings),
            patch("app.api.routes.integrations_pbs.get_pbs_sync_state", return_value=sync_state),
            patch("app.api.routes.integrations_pbs.PBSClient.get_version", return_value={}),
        ):
            return get_pbs_status()

    def test_status_reports_missing_configuration(self):
        status = self._status("")
        self.assertTrue(status.connected)
        self.assertEqual(status.datastore, "")
        self.assertIn(DATASTORE_NOT_CONFIGURED_MESSAGE, status.message)

    def test_status_reports_configured_datastore(self):
        status = self._status("store8to")
        self.assertEqual(status.datastore, "store8to")
        self.assertEqual(status.message, "Connection to PBS API succeeded")


class PlanningDatastoreRequiredTests(TestCase):
    def _payload(self, datastore: str) -> dict:
        return {
            "title": "Weekly",
            "disk_serial": "USB-123",
            "datastore": datastore,
            "window_starts_at": datetime(2026, 5, 3, 1, 0, 0),
        }

    def test_event_requires_a_datastore(self):
        with self.assertRaises(ValidationError):
            ScheduledBackupEventCreate(**self._payload(""))
        with self.assertRaises(ValidationError):
            ScheduledBackupEventUpdate(datastore="")

    def test_event_accepts_any_datastore_name(self):
        self.assertEqual(ScheduledBackupEventCreate(**self._payload("store8to")).datastore, "store8to")
