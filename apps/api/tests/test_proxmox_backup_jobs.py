from unittest import TestCase

from app.api.routes.proxmox import (
    _build_backup_job_payload,
    _build_retention_string,
    _find_job_by_signature,
    _format_retention,
)
from app.schemas import ProxmoxBackupJobUpsert


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


class BuildRetentionStringTests(TestCase):
    def test_returns_none_when_no_rule_is_set(self):
        payload = ProxmoxBackupJobUpsert(storage="pbs", schedule="sun 03:00", selected_vmids=[100])

        self.assertIsNone(_build_retention_string(payload))

    def test_joins_only_the_provided_rules(self):
        payload = ProxmoxBackupJobUpsert(
            storage="pbs",
            schedule="sun 03:00",
            selected_vmids=[100],
            keep_last=4,
            keep_monthly=8,
        )

        self.assertEqual(_build_retention_string(payload), "keep-last=4,keep-monthly=8")


class BuildBackupJobPayloadTests(TestCase):
    def test_builds_the_minimal_payload(self):
        payload = ProxmoxBackupJobUpsert(storage="pbs", schedule="sun 03:00", selected_vmids=[101, 100])

        data = _build_backup_job_payload(payload)

        self.assertEqual(data["storage"], "pbs")
        self.assertEqual(data["schedule"], "sun 03:00")
        self.assertEqual(data["mode"], "snapshot")
        self.assertEqual(data["enabled"], 1)
        self.assertEqual(data["all"], 0)
        self.assertEqual(data["vmid"], "100,101")
        self.assertNotIn("node", data)
        self.assertNotIn("comment", data)
        self.assertNotIn("prune-backups", data)

    def test_includes_node_comment_and_retention_when_set(self):
        payload = ProxmoxBackupJobUpsert(
            storage="pbs",
            schedule="sun 03:00",
            node="promox",
            selected_vmids=[100],
            enabled=False,
            comment="nightly",
            keep_last=4,
        )

        data = _build_backup_job_payload(payload)

        self.assertEqual(data["node"], "promox")
        self.assertEqual(data["comment"], "nightly")
        self.assertEqual(data["enabled"], 0)
        self.assertEqual(data["prune-backups"], "keep-last=4")


class FindJobBySignatureTests(TestCase):
    def test_matches_on_schedule_storage_and_vmid(self):
        class _FakeClient:
            def list_backup_jobs(self):
                return [
                    {"id": "backup-1", "schedule": "sun 03:00", "storage": "pbs", "vmid": "100,101"},
                    {"id": "backup-2", "schedule": "mon 04:00", "storage": "pbs", "vmid": "100"},
                ]

        submitted = {"schedule": "sun 03:00", "storage": "pbs", "vmid": "100,101"}

        found = _find_job_by_signature(_FakeClient(), submitted)

        self.assertEqual(found["id"], "backup-1")

    def test_returns_none_when_no_job_matches(self):
        class _FakeClient:
            def list_backup_jobs(self):
                return [{"id": "backup-1", "schedule": "sun 03:00", "storage": "pbs", "vmid": "100"}]

        submitted = {"schedule": "sun 03:00", "storage": "pbs", "vmid": "999"}

        self.assertIsNone(_find_job_by_signature(_FakeClient(), submitted))
