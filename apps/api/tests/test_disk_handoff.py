from types import SimpleNamespace
from unittest import TestCase

from fastapi import HTTPException

from app.services.disk_handoff import _find_matching_usb_device


def _disk(**overrides):
    values = {
        "serial_number": "WD-WXD2DA1L1E7C",
        "model_name": "WDC WD40NMZW-59BCBS0",
        "display_name": "WDC WD40NMZW-59BCBS0",
        "candidate_type": "usb",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


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
                },
            ],
            _disk(),
        )

        self.assertEqual(result, {"mapping": "7"})

    def test_safe_fallback_matches_real_western_digital_game_drive(self):
        result = _find_matching_usb_device(
            [
                {
                    "manufacturer": "Western Digital",
                    "product": "Game Drive",
                    "vendid": "1058",
                    "prodid": "2630",
                    "usbpath": "5",
                    "busnum": 2,
                    "devnum": 2,
                }
            ],
            _disk(),
        )

        self.assertEqual(result, {"mapping": "5"})

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
