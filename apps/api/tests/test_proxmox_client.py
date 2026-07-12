from types import SimpleNamespace
from unittest import TestCase

from app.services.proxmox_client import (
    ProxmoxClient,
    flatten_pve_property_value,
    is_include_selected_backup_job,
    parse_backup_job_vmids,
)


class ProxmoxClientConfigUpdateTests(TestCase):
    def test_set_qemu_usb_device_uses_put_and_returns_response(self):
        client = _RecordingProxmoxClient(response=None)

        response = client.set_qemu_usb_device("pve", 100, "usb0", "1058:2630", usb3=False)

        self.assertIsNone(response)
        self.assertEqual(client.put_calls, [("nodes/pve/qemu/100/config", {"usb0": "host=1058:2630,usb3=0"})])

    def test_delete_qemu_usb_device_uses_put_and_returns_response(self):
        client = _RecordingProxmoxClient(response=None)

        response = client.delete_qemu_usb_device("pve", 100, "usb0")

        self.assertIsNone(response)
        self.assertEqual(client.put_calls, [("nodes/pve/qemu/100/config", {"delete": "usb0"})])

    def test_upid_response_waits_for_task_completion(self):
        client = _RecordingProxmoxClient(
            response="UPID:pve:123:abc:",
            get_responses=[
                {"status": "running"},
                {"status": "stopped", "exitstatus": "OK"},
            ],
        )

        response = client.set_qemu_usb_device("pve", 100, "usb0", "1058:2630")

        self.assertEqual(response["upid"], "UPID:pve:123:abc:")
        self.assertEqual(response["task_status"]["exitstatus"], "OK")

    def test_parse_backup_job_vmids(self):
        self.assertEqual(parse_backup_job_vmids({"vmid": "101,102, 103"}), [101, 102, 103])

    def test_include_selected_backup_job_detection(self):
        self.assertTrue(is_include_selected_backup_job({"vmid": "101,102", "all": 0}))
        self.assertFalse(is_include_selected_backup_job({"all": 1}))
        self.assertFalse(is_include_selected_backup_job({"vmid": "101", "pool": "prod"}))

    def test_update_backup_job_selection_preserves_existing_fields(self):
        client = _BackupJobRecordingClient(
            job={
                "id": "backup-123",
                "schedule": "sun 03:00",
                "storage": "pbs",
                "prune-backups": "keep-last=4",
                "vmid": "101,102",
                "all": 0,
                "comment": "existing",
            }
        )

        client.update_backup_job_selection("backup-123", [103, 101])

        self.assertEqual(client.put_calls[0][0], "cluster/backup/backup-123")
        self.assertEqual(client.put_calls[0][1]["vmid"], "101,103")
        self.assertEqual(client.put_calls[0][1]["schedule"], "sun 03:00")
        self.assertEqual(client.put_calls[0][1]["storage"], "pbs")

    def test_create_backup_job_posts_to_cluster_backup(self):
        client = _CrudRecordingClient()

        client.create_backup_job({"storage": "pbs", "schedule": "sun 03:00", "vmid": "100"})

        self.assertEqual(client.post_calls, [("cluster/backup", {"storage": "pbs", "schedule": "sun 03:00", "vmid": "100"})])

    def test_replace_backup_job_puts_to_the_job_path(self):
        client = _CrudRecordingClient()

        client.replace_backup_job("backup-123", {"storage": "pbs"})

        self.assertEqual(client.put_calls, [("cluster/backup/backup-123", {"storage": "pbs"})])

    def test_delete_backup_job_deletes_the_job_path(self):
        client = _CrudRecordingClient()

        client.delete_backup_job("backup-123")

        self.assertEqual(client.delete_calls, ["cluster/backup/backup-123"])

    def test_update_backup_job_selection_flattens_multi_rule_retention(self):
        # Regression test: the Proxmox API expands `prune-backups` into a dict
        # once a job has more than one keep-* rule. Sending that dict back
        # verbatim in the PUT body used to make Proxmox reject the whole
        # request with a generic 400 "Parameter verification failed" — the
        # actual bug reported by the user when adding/removing a VM from a
        # job configured with e.g. keep-last=4 and keep-monthly=8.
        client = _BackupJobRecordingClient(
            job={
                "id": "backup-0580d237-fe75",
                "schedule": "sun 03:00",
                "storage": "pbs",
                "prune-backups": {"keep-monthly": "8", "keep-last": "4"},
                "vmid": "101,102",
                "all": 0,
            }
        )

        client.update_backup_job_selection("backup-0580d237-fe75", [103, 101])

        sent = client.put_calls[0][1]
        self.assertEqual(sent["prune-backups"], "keep-last=4,keep-monthly=8")
        self.assertIsInstance(sent["prune-backups"], str)


class FlattenPveScalarPropertyValueTests(TestCase):
    def test_passes_through_a_plain_string(self):
        self.assertEqual(flatten_pve_property_value("keep-last=4"), "keep-last=4")

    def test_passes_through_non_string_scalars(self):
        self.assertEqual(flatten_pve_property_value(0), 0)
        self.assertIsNone(flatten_pve_property_value(None))

    def test_joins_a_multi_rule_dict_into_a_stable_string(self):
        value = {"keep-monthly": "8", "keep-last": "4"}

        self.assertEqual(flatten_pve_property_value(value), "keep-last=4,keep-monthly=8")


class _RecordingProxmoxClient(ProxmoxClient):
    def __init__(self, *, response, get_responses=None):
        super().__init__(
            SimpleNamespace(
                pve_api_token_id="token",
                pve_api_token_secret="secret",
                pve_api_url="https://pve.example/api2/json",
                pve_verify_ssl=False,
            )
        )
        self.response = response
        self.get_responses = list(get_responses or [])
        self.put_calls = []

    def _put(self, path, *, data=None):
        self.put_calls.append((path, dict(data or {})))
        return self.response

    def _get(self, path):
        if self.get_responses:
            return self.get_responses.pop(0)
        return {"status": "stopped", "exitstatus": "OK"}


class _BackupJobRecordingClient(ProxmoxClient):
    def __init__(self, *, job):
        super().__init__(
            SimpleNamespace(
                pve_api_token_id="token",
                pve_api_token_secret="secret",
                pve_api_url="https://pve.example/api2/json",
                pve_verify_ssl=False,
            )
        )
        self.job = job
        self.put_calls = []

    def _get(self, path):
        return self.job

    def _put(self, path, *, data=None):
        self.put_calls.append((path, dict(data or {})))
        return None


class _CrudRecordingClient(ProxmoxClient):
    def __init__(self):
        super().__init__(
            SimpleNamespace(
                pve_api_token_id="token",
                pve_api_token_secret="secret",
                pve_api_url="https://pve.example/api2/json",
                pve_verify_ssl=False,
            )
        )
        self.post_calls = []
        self.put_calls = []
        self.delete_calls = []

    def _post(self, path, *, data=None):
        self.post_calls.append((path, dict(data or {})))
        return None

    def _put(self, path, *, data=None):
        self.put_calls.append((path, dict(data or {})))
        return None

    def _delete(self, path):
        self.delete_calls.append(path)
        return None
