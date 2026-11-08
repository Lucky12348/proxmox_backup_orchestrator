import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent import server
from agent.main import (
    AgentSettings,
    SubprocessResult,
    _assert_disk_hosts_no_pbs_datastore,
    _assert_safe_dedicated_disk,
    check_source_datastore,
    cleanup_legacy_external_export_objects,
    prepare_dedicated_pbs_datastore_result,
    prepare_disk_result,
)

# Arbitrary names on purpose: nothing may depend on a particular datastore name.
DATASTORE_NAMES = ["store8to", "backup-store", "pbs_main-01"]
MANAGER = "/usr/sbin/proxmox-backup-manager"


def _disk(partition_mount: str | None = None, partition_fstype: str | None = "ext4") -> dict[str, object]:
    return {
        "name": "sdc",
        "kname": "sdc",
        "path": "/dev/sdc",
        "type": "disk",
        "serial": "WD-WXD2DA1L1E7C",
        "size": "3.6T",
        "mountpoint": None,
        "children": [
            {
                "name": "sdc1",
                "kname": "sdc1",
                "path": "/dev/sdc1",
                "type": "part",
                "serial": None,
                "size": "3.6T",
                "mountpoint": partition_mount,
                "fstype": partition_fstype,
                "children": [],
            }
        ],
    }


def _which_manager(name: str) -> str | None:
    return MANAGER if name == "proxmox-backup-manager" else None


def _datastore_list(*datastores: dict[str, object]):
    def fake_run_subprocess(command: list[str], timeout_seconds: float) -> SubprocessResult:
        if command[1:3] == ["datastore", "list"]:
            return SubprocessResult(command, 0, json.dumps(list(datastores)), "")
        return SubprocessResult(command, 0, "", "")

    return fake_run_subprocess


def _failing_datastore_list(command: list[str], timeout_seconds: float) -> SubprocessResult:
    return SubprocessResult(command, 1, "", "proxmox-backup-proxy is not running")


class FormatGuardTests(TestCase):
    def _assert_guard(self, disk, *datastores, mount_source=None, uuid=None, extra=None):
        with (
            patch("agent.main.shutil.which", side_effect=_which_manager),
            patch("agent.main.run_subprocess", side_effect=_datastore_list(*datastores)),
            patch("agent.main._mount_source_for_target", return_value=mount_source),
            patch("agent.main.get_blkid_info", return_value={"UUID": uuid} if uuid else {}),
        ):
            _assert_disk_hosts_no_pbs_datastore(disk, AgentSettings(), extra_mount_paths=extra)

    def test_refuses_disk_hosting_source_datastore_whatever_its_name(self):
        for name in DATASTORE_NAMES:
            with self.subTest(name=name), self.assertRaises(RuntimeError) as raised:
                self._assert_guard(_disk("/srv/pbs"), {"name": name, "path": f"/srv/pbs/{name}"})
            self.assertIn(f"PBS datastore `{name}`", str(raised.exception))

    def test_refuses_when_any_of_several_datastores_is_on_the_disk(self):
        datastores = [
            {"name": "store8to", "path": "/mnt/datastore/store8to"},
            {"name": "offsite", "path": "/srv/offsite/store"},
            {"name": "pbo-wd-other", "path": "/mnt/pbo/OTHER/pbs-datastore"},
        ]
        with self.assertRaises(RuntimeError) as raised:
            self._assert_guard(_disk("/srv/offsite"), *datastores)
        self.assertIn("`offsite`", str(raised.exception))

    def test_allows_disk_that_hosts_none_of_several_datastores(self):
        datastores = [
            {"name": "store8to", "path": "/mnt/datastore/store8to"},
            {"name": "offsite", "path": "/srv/offsite/store"},
        ]
        self._assert_guard(_disk("/mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore"), *datastores, mount_source="/dev/sda3")

    def test_refuses_when_datastore_is_stored_on_disk_even_if_lsblk_shows_no_mount(self):
        with self.assertRaises(RuntimeError) as raised:
            self._assert_guard(_disk(None), {"name": "store8to", "path": "/data/store8to"}, mount_source="/dev/sdc1")
        self.assertIn("is stored on `/dev/sdc1`", str(raised.exception))

    def test_refuses_mount_made_after_disk_snapshot(self):
        mount = "/mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore"
        with self.assertRaises(RuntimeError):
            self._assert_guard(_disk(None), {"name": "old-pbo", "path": mount}, extra=[mount])

    def test_refuses_backing_device_of_removable_datastore(self):
        with self.assertRaises(RuntimeError) as raised:
            self._assert_guard(
                _disk(None),
                {"name": "removable", "path": "removable", "backing-device": "1234-ABCD"},
                uuid="1234-ABCD",
            )
        self.assertIn("removable", str(raised.exception))

    def test_refuses_datastore_whose_location_cannot_be_determined(self):
        with self.assertRaises(RuntimeError) as raised:
            self._assert_guard(_disk(None), {"name": "weird", "path": "relative/path"})
        self.assertIn("cannot determine", str(raised.exception))

    def test_fails_closed_when_datastore_list_command_fails(self):
        with (
            patch("agent.main.shutil.which", side_effect=_which_manager),
            patch("agent.main.run_subprocess", side_effect=_failing_datastore_list),
            self.assertRaises(RuntimeError) as raised,
        ):
            _assert_disk_hosts_no_pbs_datastore(_disk(None), AgentSettings())
        self.assertIn("unable to read the PBS datastore list", str(raised.exception))

    def test_fails_closed_when_datastore_list_is_not_json(self):
        with (
            patch("agent.main.shutil.which", side_effect=_which_manager),
            patch("agent.main.run_subprocess", return_value=SubprocessResult([MANAGER], 0, "not json", "")),
            self.assertRaises(RuntimeError) as raised,
        ):
            _assert_disk_hosts_no_pbs_datastore(_disk(None), AgentSettings())
        self.assertIn("unable to read the PBS datastore list", str(raised.exception))

    def test_fails_closed_when_pbs_is_installed_but_manager_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("agent.main.shutil.which", return_value=None),
                patch("agent.main.PBS_CONFIG_DIR", Path(temp_dir)),
                self.assertRaises(RuntimeError) as raised,
            ):
                _assert_disk_hosts_no_pbs_datastore(_disk(None), AgentSettings())
        self.assertIn("unable to read the PBS datastore list", str(raised.exception))

    def test_allows_machine_without_pbs_installed(self):
        # Proxmox host agent: no proxmox-backup-manager and no /etc/proxmox-backup.
        with (
            patch("agent.main.shutil.which", return_value=None),
            patch("agent.main.PBS_CONFIG_DIR", Path(tempfile.gettempdir()) / "pbo-no-such-pbs-config"),
        ):
            _assert_disk_hosts_no_pbs_datastore(_disk(None), AgentSettings())

    def test_static_check_refuses_any_mount_overlapping_pbs_datastore_root(self):
        for mount in [*(f"/mnt/datastore/{name}" for name in DATASTORE_NAMES), "/mnt/datastore", "/mnt", "/boot"]:
            with self.subTest(mount=mount), patch("agent.main.load_udev_properties", return_value={}):
                with self.assertRaises(RuntimeError):
                    _assert_safe_dedicated_disk(_disk(mount))

    def test_static_check_allows_pbo_managed_mount(self):
        with patch("agent.main.load_udev_properties", return_value={}):
            _assert_safe_dedicated_disk(_disk("/mnt/pbo/WD-WXD2DA1L1E7C/pbs-datastore"))


class DestructivePathGuardTests(TestCase):
    def _prepare_dedicated(self, run_subprocess_side_effect, disk):
        commands: list[list[str]] = []

        def fake_run_logged_command(command, *args, **kwargs):
            commands.append(command)
            return SubprocessResult(command, 0, "", "")

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("agent.main.resolve_disk", return_value=(disk, [disk])),
                patch("agent.main.load_udev_properties", return_value={}),
                patch("agent.main.default_mount_base_path", return_value=Path(temp_dir)),
                patch("agent.main.shutil.which", side_effect=_which_manager),
                patch("agent.main.run_subprocess", side_effect=run_subprocess_side_effect),
                patch("agent.main._mount_source_for_target", return_value=None),
                patch("agent.main._run_logged_command", side_effect=fake_run_logged_command),
                patch("agent.main.ensure_mountpoint"),
                patch("agent.main.ensure_fstab_entry"),
                patch("agent.main._ensure_dedicated_datastore_permissions"),
                patch("agent.main._ensure_pbs_datastore"),
                patch("agent.main._write_dedicated_datastore_marker"),
            ):
                try:
                    return prepare_dedicated_pbs_datastore_result(
                        "/dev/sdc", "pbo-wd-wxd2da1l1e7c", True, True, AgentSettings()
                    ), commands
                except RuntimeError as exc:
                    return exc, commands

    def test_dedicated_prepare_does_not_wipe_when_datastore_list_is_unreadable(self):
        disk = _disk(None)
        disk["children"] = []
        result, commands = self._prepare_dedicated(_failing_datastore_list, disk)

        self.assertIsInstance(result, RuntimeError)
        self.assertIn("unable to read the PBS datastore list", str(result))
        self.assertEqual(commands, [])

    def test_dedicated_prepare_formats_when_no_datastore_is_on_the_disk(self):
        disk = _disk(None)
        disk["children"] = []
        result, commands = self._prepare_dedicated(
            _datastore_list({"name": "store8to", "path": "/mnt/datastore/store8to"}), disk
        )

        self.assertIsInstance(result, dict)
        self.assertEqual(commands[0][0], "wipefs")

    def test_prepare_disk_dedicated_mode_does_not_mkfs_when_datastore_list_is_unreadable(self):
        disk = _disk(None)
        with (
            patch("agent.main.resolve_disk", return_value=(disk, [disk])),
            patch("agent.main.load_udev_properties", return_value={}),
            patch("agent.main.shutil.which", side_effect=_which_manager),
            patch("agent.main.run_subprocess", side_effect=_failing_datastore_list),
            patch("agent.main.run_command") as run_command,
            self.assertRaises(RuntimeError),
        ):
            prepare_disk_result("/dev/sdc", "dedicated_backup", None, True, AgentSettings())
        run_command.assert_not_called()


class LegacyCleanupTests(TestCase):
    def test_skips_configured_source_datastore_instead_of_a_literal_name(self):
        removed: list[list[str]] = []
        listings = {
            "sync-job": [],
            "remote": [],
            "datastore": [{"name": "pbo-export-store8to"}, {"name": "pbo-export-old"}],
        }

        def fake_run_subprocess(command: list[str], timeout_seconds: float) -> SubprocessResult:
            if command[2] == "list":
                return SubprocessResult(command, 0, json.dumps(listings[command[1]]), "")
            removed.append(command)
            return SubprocessResult(command, 0, "", "")

        with (
            patch("agent.main.shutil.which", return_value=MANAGER),
            patch("agent.main.run_subprocess", side_effect=fake_run_subprocess),
        ):
            cleanup_legacy_external_export_objects(AgentSettings(pbs_datastore="pbo-export-store8to"))

        self.assertEqual(removed, [[MANAGER, "datastore", "remove", "pbo-export-old"]])


class SourceDatastoreCheckTests(TestCase):
    def _check(self, settings, run_subprocess_side_effect):
        with (
            patch("agent.main.shutil.which", side_effect=_which_manager),
            patch("agent.main.run_subprocess", side_effect=run_subprocess_side_effect),
        ):
            return check_source_datastore(settings)

    def test_ok_when_configured_datastore_exists(self):
        for name in DATASTORE_NAMES:
            with self.subTest(name=name):
                state = self._check(
                    AgentSettings(pbs_datastore=name),
                    _datastore_list({"name": "other", "path": "/srv/other"}, {"name": name, "path": f"/srv/{name}"}),
                )
                self.assertTrue(state["ok"])
                self.assertEqual(state["status"], "ok")

    def test_missing_after_rename_lists_available_datastores(self):
        state = self._check(
            AgentSettings(pbs_datastore="backup-store"),
            _datastore_list({"name": "store8to", "path": "/mnt/datastore/store8to"}, {"name": "archive", "path": "/a"}),
        )
        self.assertFalse(state["ok"])
        self.assertEqual(state["status"], "missing")
        self.assertEqual(state["available_datastores"], ["archive", "store8to"])
        self.assertEqual(
            state["message"],
            "Le datastore source backup-store n'existe pas sur ce PBS ; datastores disponibles : archive, store8to.",
        )

    def test_not_configured_when_pbs_datastore_is_empty(self):
        state = self._check(AgentSettings(pbs_datastore=""), _datastore_list({"name": "store8to", "path": "/x"}))
        self.assertFalse(state["ok"])
        self.assertEqual(state["status"], "not_configured")

    def test_unavailable_when_datastore_list_is_unreadable(self):
        state = self._check(AgentSettings(pbs_datastore="store8to"), _failing_datastore_list)
        self.assertFalse(state["ok"])
        self.assertEqual(state["status"], "unavailable")

    def test_not_applicable_on_machine_without_pbs(self):
        with (
            patch("agent.main.shutil.which", return_value=None),
            patch("agent.main.PBS_CONFIG_DIR", Path(tempfile.gettempdir()) / "pbo-no-such-pbs-config"),
        ):
            state = check_source_datastore(AgentSettings(pbs_datastore="store8to"))
        self.assertTrue(state["ok"])
        self.assertEqual(state["status"], "not_applicable")


class StartupCheckServerTests(TestCase):
    def setUp(self):
        self.settings = AgentSettings(server_token="test-token", pbs_datastore="backup-store")
        server.app.dependency_overrides[server.get_settings] = lambda: self.settings
        server._source_datastore_state = None

    def tearDown(self):
        server.app.dependency_overrides.clear()
        server._source_datastore_state = None

    def test_startup_logs_error_and_health_exposes_missing_source_datastore(self):
        list_store8to = _datastore_list({"name": "store8to", "path": "/mnt/datastore/store8to"})
        with (
            patch("agent.server.get_settings", return_value=self.settings),
            patch("agent.main.shutil.which", side_effect=_which_manager),
            patch("agent.main.run_subprocess", side_effect=list_store8to) as run_subprocess,
            self.assertLogs("agent", level="ERROR") as logs,
        ):
            with TestClient(server.app) as client:
                response = client.get("/health", headers={"X-Agent-Token": "test-token"})

        self.assertIn("Le datastore source backup-store n'existe pas sur ce PBS", "\n".join(logs.output))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["source_datastore"]["status"], "missing")
        self.assertEqual(payload["source_datastore"]["available_datastores"], ["store8to"])
        # Checked once at startup; /health serves the cached result.
        self.assertEqual(run_subprocess.call_count, 1)

    def test_health_rechecks_while_pbs_was_unavailable(self):
        responses = iter([_failing_datastore_list, _datastore_list({"name": "backup-store", "path": "/srv/b"})])

        def fake_run_subprocess(command, timeout_seconds):
            return next(responses)(command, timeout_seconds)

        with (
            patch("agent.server.get_settings", return_value=self.settings),
            patch("agent.main.shutil.which", side_effect=_which_manager),
            patch("agent.main.run_subprocess", side_effect=fake_run_subprocess),
            self.assertLogs("agent", level="INFO"),
        ):
            with TestClient(server.app) as client:
                response = client.get("/health", headers={"X-Agent-Token": "test-token"})

        self.assertEqual(response.json()["source_datastore"]["status"], "ok")
