from types import SimpleNamespace
from unittest import TestCase

from app.services.proxmox_client import ProxmoxClient


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
