from types import SimpleNamespace
from unittest import TestCase

from app.services.proxmox_client import ProxmoxClient, is_include_selected_backup_job, parse_backup_job_vmids


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
