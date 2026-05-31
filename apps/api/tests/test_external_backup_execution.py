from types import SimpleNamespace
from unittest import TestCase

from app.models import ExternalBackupMode
from app.services.external_backup_agent import AgentCommandResult
from app.services.external_backup_agent import _disk_identifiers
from app.services.external_backup_execution import ExternalBackupExecutionService


class ExternalBackupExecutionTests(TestCase):
    def test_execute_uses_actual_target_path_returned_by_prepare(self):
        bridge = FakeBridge()
        service = ExternalBackupExecutionService()
        service._bridge = bridge
        disk = SimpleNamespace(serial_number="WD-WXD2DA1L1E7C")

        result = service.execute(
            disk=disk,
            datastore_name="source-store",
            mode=ExternalBackupMode.COEXISTENCE,
        )

        self.assertEqual(
            bridge.export_target_path,
            "/mnt/pbo/WD-WXD2DA1L1E7C/loop-pbs-datastore",
        )
        self.assertEqual(
            result.target_path,
            "/mnt/pbo/WD-WXD2DA1L1E7C/loop-pbs-datastore",
        )
        self.assertIn("Requested target path:", result.prepare.stdout_log or "")
        self.assertIn("Actual datastore path:", result.prepare.stdout_log or "")
        self.assertIn("Loop image path:", result.prepare.stdout_log or "")

    def test_disk_identifiers_include_historical_canonical_reported_and_aliases(self):
        disk = SimpleNamespace(
            serial_number="WD-WXD2DA1L1E7C",
            canonical_serial_number="WXD2DA1L1E7C",
            reported_serial_number="575844324441314C31453743",
            serial_aliases=["WDC_WXD2DA1L1E7C"],
            pbs_device_path="/dev/sdc",
        )

        identifiers = _disk_identifiers(disk)

        self.assertLess(identifiers.index("WD-WXD2DA1L1E7C"), identifiers.index("WXD2DA1L1E7C"))
        self.assertIn("575844324441314C31453743", identifiers)
        self.assertIn("WDC_WXD2DA1L1E7C", identifiers)
        self.assertIn("/dev/sdc", identifiers)


class FakeBridge:
    export_target_path: str | None = None

    def prepare_disk_on_pbs(self, disk, mode):
        return AgentCommandResult(
            ok=True,
            message="disk prepared",
            stdout_log=None,
            stderr_log=None,
            command_summary="prepare disk",
            execution_cwd="/",
            return_code=0,
            payload={"mount_path": "/mnt/pbo/WD-WXD2DA1L1E7C"},
        )

    def inspect_disk_on_pbs(self, disk):
        return AgentCommandResult(
            ok=True,
            message="disk inspected",
            stdout_log="disk visible",
            stderr_log=None,
            command_summary="inspect disk",
            execution_cwd="/",
            return_code=0,
            payload={"mount_path": "/mnt/pbo/WD-WXD2DA1L1E7C"},
        )

    def prepare_external_datastore(self, mount_path, target_path, mode, run_id=None):
        return AgentCommandResult(
            ok=True,
            message="datastore prepared",
            stdout_log="prepared loop datastore",
            stderr_log=None,
            command_summary="prepare datastore",
            execution_cwd="/",
            return_code=0,
            payload={
                "requested_target_path": target_path,
                "target_path": "/mnt/pbo/WD-WXD2DA1L1E7C/loop-pbs-datastore",
                "actual_target_path": "/mnt/pbo/WD-WXD2DA1L1E7C/loop-pbs-datastore",
                "loop_image_path": "/mnt/pbo/WD-WXD2DA1L1E7C/images/pbs-export.ext4",
                "loop_backed": True,
            },
        )

    def run_external_export(
        self,
        target_path,
        datastore_name,
        mode,
        run_id=None,
        target_datastore_name=None,
        persist_target_datastore=False,
    ):
        self.export_target_path = target_path
        return AgentCommandResult(
            ok=True,
            message="export complete",
            stdout_log=None,
            stderr_log=None,
            command_summary="run export",
            execution_cwd="/",
            return_code=0,
            payload=None,
        )
