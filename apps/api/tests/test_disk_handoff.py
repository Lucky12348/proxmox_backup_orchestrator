from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException

from app.services.host_agent import HostAgentResult
from app.services.disk_handoff import (
    _attach_usb_candidate,
    _find_matching_usb_device,
    _handoff_candidates,
    _qemu_usb_host_mapping,
)


def _disk(**overrides):
    values = {
        "serial_number": "WD-WXD2DA1L1E7C",
        "model_name": "WDC WD40NMZW-59BCBS0",
        "display_name": "WDC WD40NMZW-59BCBS0",
        "candidate_type": "usb",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _settings():
    return SimpleNamespace(pbs_execution_vm_node="pve", pbs_execution_vm_id=100)


def _host_agent_result(command: str, stdout: str = ""):
    return HostAgentResult(
        ok=True,
        message="ok",
        stdout_log=stdout,
        stderr_log=None,
        command_summary=command,
        execution_cwd="/",
        return_code=0,
        payload={"config": stdout} if stdout else {},
    )


class _FakeProxmoxClient:
    def __init__(self, configs):
        self.configs = list(configs)
        self.get_calls = 0
        self.set_calls = []

    def get_qemu_config(self, node_name, vm_id):
        self.get_calls += 1
        if self.configs:
            return self.configs.pop(0)
        return {}


class DiskHandoffUsbMatchTests(TestCase):
    def test_strict_serial_match_is_preferred(self):
        result = _find_matching_usb_device(
            [
                {
                    "manufacturer": "Western Digital",
                    "product": "Game Drive",
                    "vendid": "1058",
                    "prodid": "2630",
                    "usbpath": "5",
                },
                {
                    "serial": "WD-WXD2DA1L1E7C",
                    "product": "WDC WD40NMZW-59BCBS0",
                    "usbpath": "7",
                    "busnum": 3,
                    "devnum": 4,
                },
            ],
            _disk(),
        )

        self.assertEqual(result["mapping"], "3-7")

    def test_safe_fallback_matches_real_western_digital_game_drive(self):
        result = _find_matching_usb_device(
            [
                {
                    "manufacturer": "Western Digital",
                    "product": "Game Drive",
                    "vendid": "1058",
                    "prodid": "2630",
                    "usbpath": "5",
                    "port": "4",
                    "busnum": 2,
                    "devnum": 2,
                }
            ],
            _disk(),
        )

        self.assertEqual(result["mapping"], "2-5")

    def test_qemu_mapping_does_not_use_devnum_when_usbpath_exists(self):
        mapping = _qemu_usb_host_mapping(
            {
                "busnum": 2,
                "devnum": 2,
                "usbpath": "5",
                "vendid": "1058",
                "prodid": "2630",
            }
        )

        self.assertEqual(mapping, "2-5")
        self.assertNotEqual(mapping, "2-2")

    def test_qemu_mapping_uses_busnum_and_port_plus_one_when_usbpath_missing(self):
        mapping = _qemu_usb_host_mapping(
            {
                "busnum": 1,
                "port": 8,
                "vendid": "1058",
                "prodid": "2630",
            }
        )

        self.assertEqual(mapping, "1-9")

    def test_qemu_mapping_falls_back_to_vendor_product_id(self):
        result = _find_matching_usb_device(
            [
                {
                    "manufacturer": "Western Digital",
                    "product": "Game Drive",
                    "vendid": "1058",
                    "prodid": "2630",
                }
            ],
            _disk(),
        )

        self.assertEqual(result["mapping"], "1058:2630")

    def test_usbpath_alone_is_not_qemu_mapping(self):
        self.assertIsNone(_qemu_usb_host_mapping({"usbpath": "5"}))

    def test_safe_fallback_rejects_forbidden_usb_devices(self):
        with self.assertRaises(HTTPException) as raised:
            _find_matching_usb_device(
                [
                    {
                        "manufacturer": "APC",
                        "product": "Back-UPS",
                        "vendid": "051d",
                        "prodid": "0002",
                        "usbpath": "2",
                        "class": "3",
                    }
                ],
                _disk(),
            )

        self.assertEqual(raised.exception.status_code, 404)
        self.assertIn("Available USB devices", raised.exception.detail)

    def test_safe_fallback_reports_ambiguous_matches(self):
        with self.assertRaises(HTTPException) as raised:
            _find_matching_usb_device(
                [
                    {
                        "manufacturer": "Western Digital",
                        "product": "Game Drive",
                        "vendid": "1058",
                        "prodid": "2630",
                        "usbpath": "5",
                    },
                    {
                        "manufacturer": "Western Digital",
                        "product": "Elements Drive",
                        "vendid": "1058",
                        "prodid": "25a3",
                        "usbpath": "6",
                    },
                ],
                _disk(),
            )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("Ambiguous Proxmox USB passthrough candidates", raised.exception.detail)
        self.assertIn("usbpath=5", raised.exception.detail)
        self.assertIn("usbpath=6", raised.exception.detail)

    def test_attach_verification_accepts_config_after_three_polls(self):
        client = _FakeProxmoxClient([{}, {}, {"usb0": "host=1-9,usb3=0"}])
        progress: list[str] = []

        with (
            patch("app.services.disk_handoff.sleep"),
            patch("app.services.disk_handoff._attach_usb_slot_via_host_agent", return_value=_host_agent_result("qm set 100 -usb0 host=1-9,usb3=0")) as attach,
            patch("app.services.disk_handoff._get_qemu_config_usb_map", side_effect=[{}, {}, {"usb0": "host=1-9,usb3=0"}]),
        ):
            _attach_usb_candidate(
                client,
                _settings(),
                _disk(),
                "usb0",
                {"mapping": "1-9", "speed": "480", "summary": "Western Digital"},
                lambda step, message, line=None: progress.append(message),
            )

        attach.assert_called_once()
        self.assertTrue(any("attempt 3/15" in message for message in progress))

    def test_attach_verification_accepts_raw_mapping_config_value(self):
        client = _FakeProxmoxClient([{"usb0": "1-9,usb3=0"}])

        with (
            patch("app.services.disk_handoff.sleep"),
            patch("app.services.disk_handoff._attach_usb_slot_via_host_agent", return_value=_host_agent_result("qm set 100 -usb0 host=1-9,usb3=0")),
            patch("app.services.disk_handoff._get_qemu_config_usb_map", return_value={"usb0": "1-9,usb3=0"}),
        ):
            _attach_usb_candidate(
                client,
                _settings(),
                _disk(),
                "usb0",
                {"mapping": "1-9", "speed": "480", "summary": "Western Digital"},
                None,
            )

    def test_handoff_candidates_include_vendor_product_fallback_after_bus_port_mapping(self):
        candidates = _handoff_candidates(
            {
                "mapping": "1-9",
                "vendid": "1058",
                "prodid": "2630",
                "summary": "Western Digital",
            }
        )

        self.assertEqual([candidate["mapping"] for candidate in candidates], ["1-9", "1058:2630"])
