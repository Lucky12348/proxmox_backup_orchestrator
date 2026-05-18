from types import SimpleNamespace
from unittest import TestCase

from fastapi import HTTPException

from app.services.disk_handoff import _find_matching_usb_device, _qemu_usb_host_mapping


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
