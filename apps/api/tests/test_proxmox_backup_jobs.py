from unittest import TestCase

from app.api.routes.proxmox import _format_retention


class FormatRetentionTests(TestCase):
    def test_passes_through_a_plain_string(self):
        self.assertEqual(_format_retention("keep-last=4"), "keep-last=4")

    def test_returns_none_when_missing(self):
        self.assertIsNone(_format_retention(None))

    def test_joins_a_multi_rule_dict_into_a_stable_string(self):
        # This is the exact shape the Proxmox API returns once a backup job has
        # more than one keep-* rule configured; it used to crash
        # GET /api/v1/proxmox/backup-jobs with a pydantic ValidationError
        # because ProxmoxBackupJobRead.retention expects a plain string.
        value = {"keep-monthly": "8", "keep-last": "4"}

        self.assertEqual(_format_retention(value), "keep-last=4,keep-monthly=8")
