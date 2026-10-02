import copy
import json
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from agent.ntfy_notif import (
    NtfyNotifPermissionError,
    NtfyNotifSettings,
    NtfyNotifValidationError,
    build_test_command,
    iter_lines_reverse,
    prune_backups,
    read_history_result,
    read_queue_result,
    send_test_result,
    validate_templates,
    validate_test_request,
    write_templates_result,
)


VALID_TEMPLATES = {
    "defaults": {
        "topic": "pve-alerts",
        "click": "https://pve.example.lan:8006",
        "icon": "",
        "late_after_sec": 300,
    },
    "events": {
        "ups.onbatt": {
            "enabled": True,
            "priority": 4,
            "emoji": "battery",
            "title": "Onduleur sur batterie",
            "message": "Charge {charge}% - autonomie {runtime}s",
        },
        "auth.ssh_fail": {
            "enabled": False,
            "topic": "security",
            "priority": 5,
            "emoji": "no_entry",
            "title": "Echec SSH",
            "message": "{user} depuis {ip}",
            "click": "http://example.lan",
            "icon": "https://example.lan/icon.png",
        },
    },
}


def templates(**overrides):
    data = copy.deepcopy(VALID_TEMPLATES)
    for path, value in overrides.items():
        target = data
        keys = path.split("__")
        for key in keys[:-1]:
            target = target[key]
        if value is _DELETE:
            del target[keys[-1]]
        else:
            target[keys[-1]] = value
    return data


_DELETE = object()


def errors_for(data):
    try:
        validate_templates(data)
    except NtfyNotifValidationError as exc:
        return exc.errors
    return []


class ValidateTemplatesTests(TestCase):
    def test_valid_document_passes(self):
        self.assertEqual(errors_for(templates()), [])

    def test_optional_defaults_may_be_omitted(self):
        data = templates(defaults={"topic": "pve"})
        self.assertEqual(errors_for(data), [])

    def test_unknown_keys_are_rejected_at_every_level(self):
        data = templates()
        data["extra"] = 1
        data["defaults"]["color"] = "red"
        data["events"]["ups.onbatt"]["tags"] = ["x"]
        errors = errors_for(data)
        self.assertIn("root: unknown key `extra`", errors)
        self.assertIn("defaults: unknown key `color`", errors)
        self.assertIn("events.ups.onbatt: unknown key `tags`", errors)

    def test_missing_required_keys(self):
        errors = errors_for(templates(**{"events__ups.onbatt__title": _DELETE}))
        self.assertIn("events.ups.onbatt: missing key `title`", errors)
        self.assertIn("root: missing key `events`", errors_for({"defaults": {"topic": "x"}}))

    def test_event_code_pattern(self):
        for code in ("UPS.onbatt", "ups..onbatt", ".ups", "ups.", "ups-onbatt", "ups onbatt", "-x"):
            data = templates()
            data["events"][code] = copy.deepcopy(VALID_TEMPLATES["events"]["ups.onbatt"])
            self.assertTrue(any(code in error and "invalid event code" in error for error in errors_for(data)), code)
        for code in ("test", "ups.onbatt", "system.boot_unclean", "a1.b2.c3"):
            data = templates()
            data["events"][code] = copy.deepcopy(VALID_TEMPLATES["events"]["ups.onbatt"])
            self.assertEqual(errors_for(data), [], code)

    def test_priority_must_be_int_between_1_and_5(self):
        for value in (0, 6, "3", 3.0, True, None):
            self.assertTrue(errors_for(templates(**{"events__ups.onbatt__priority": value})), value)
        for value in (1, 5):
            self.assertEqual(errors_for(templates(**{"events__ups.onbatt__priority": value})), [])

    def test_enabled_must_be_boolean(self):
        self.assertTrue(errors_for(templates(**{"events__ups.onbatt__enabled": 1})))

    def test_emoji_pattern(self):
        for value in ("", "Battery", "a" * 41, "white check", ":bell:"):
            self.assertTrue(errors_for(templates(**{"events__ups.onbatt__emoji": value})), value)
        for value in ("+1", "white_check_mark", "-1", "a" * 40):
            self.assertEqual(errors_for(templates(**{"events__ups.onbatt__emoji": value})), [], value)

    def test_topic_pattern(self):
        for value in ("", "a/b", "a b", "x" * 65, "été"):
            self.assertTrue(errors_for(templates(defaults__topic=value)), value)
            self.assertTrue(errors_for(templates(**{"events__auth.ssh_fail__topic": value})), value)
        self.assertEqual(errors_for(templates(defaults__topic="A_b-9")), [])

    def test_title_rules(self):
        self.assertTrue(errors_for(templates(**{"events__ups.onbatt__title": ""})))
        self.assertTrue(errors_for(templates(**{"events__ups.onbatt__title": "   "})))
        self.assertTrue(errors_for(templates(**{"events__ups.onbatt__title": "x" * 61})))
        self.assertTrue(errors_for(templates(**{"events__ups.onbatt__title": "a\nb"})))
        self.assertEqual(errors_for(templates(**{"events__ups.onbatt__title": "é" * 60})), [])

    def test_message_rules(self):
        self.assertTrue(errors_for(templates(**{"events__ups.onbatt__message": "x" * 201})))
        self.assertTrue(errors_for(templates(**{"events__ups.onbatt__message": 12})))
        self.assertEqual(errors_for(templates(**{"events__ups.onbatt__message": "x" * 200})), [])
        self.assertEqual(errors_for(templates(**{"events__ups.onbatt__message": "ligne 1\nligne 2"})), [])

    def test_urls_must_be_empty_or_http(self):
        for value in ("ftp://x", "javascript:alert(1)", "https://", "not a url", "https://a b", 5):
            self.assertTrue(errors_for(templates(defaults__click=value)), value)
            self.assertTrue(errors_for(templates(**{"events__auth.ssh_fail__icon": value})), value)
        for value in ("", "http://a", "https://a.b/c?d=e"):
            self.assertEqual(errors_for(templates(defaults__icon=value)), [], value)

    def test_late_after_sec_bounds(self):
        for value in (-1, 86401, "10", 1.5, False):
            self.assertTrue(errors_for(templates(defaults__late_after_sec=value)), value)
        for value in (0, 86400):
            self.assertEqual(errors_for(templates(defaults__late_after_sec=value)), [])

    def test_root_must_be_object(self):
        self.assertEqual(errors_for([]), ["root: must be a JSON object"])


class WriteTemplatesTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.settings = NtfyNotifSettings(
            templates_path=root / "templates.json",
            backups_dir=root / "backups",
            history_path=root / "history.jsonl",
            queue_dir=root / "queue",
            send_command="/usr/local/bin/ntfy-send",
        )
        self.settings.templates_path.write_text(json.dumps(VALID_TEMPLATES), encoding="utf-8")
        self.privileges = patch("agent.ntfy_notif.ensure_write_privileges")
        self.privileges.start()

    def tearDown(self):
        self.privileges.stop()
        self.tmp.cleanup()

    def test_write_replaces_file_and_keeps_backup(self):
        data = templates(defaults__topic="new-topic")
        with patch("agent.ntfy_notif.apply_owner_and_mode") as owner_mock:
            result = write_templates_result(data, self.settings)

        self.assertTrue(result["ok"])
        self.assertEqual(json.loads(self.settings.templates_path.read_text(encoding="utf-8")), data)
        backups = list(self.settings.backups_dir.glob("templates-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8")), VALID_TEMPLATES)
        mode = owner_mock.call_args.args[3]
        self.assertEqual(mode, 0o664)
        # No temporary file is left behind next to templates.json.
        self.assertEqual(sorted(p.name for p in self.settings.templates_path.parent.glob(".templates.json.*")), [])

    def test_invalid_document_is_not_written(self):
        before = self.settings.templates_path.read_text(encoding="utf-8")
        with self.assertRaises(NtfyNotifValidationError):
            write_templates_result(templates(defaults__topic="bad topic"), self.settings)
        self.assertEqual(self.settings.templates_path.read_text(encoding="utf-8"), before)
        self.assertFalse(self.settings.backups_dir.exists())

    def test_backups_are_pruned_to_ten(self):
        self.settings.backups_dir.mkdir()
        for index in range(15):
            (self.settings.backups_dir / f"templates-20260101T0000{index:02d}000000Z.json").write_text("{}")
        removed = prune_backups(self.settings.backups_dir, 10)
        remaining = sorted(p.name for p in self.settings.backups_dir.glob("templates-*.json"))
        self.assertEqual(len(removed), 5)
        self.assertEqual(len(remaining), 10)
        self.assertEqual(remaining[0], "templates-20260101T000005000000Z.json")

    def test_non_root_agent_is_refused_with_required_rights(self):
        self.privileges.stop()
        try:
            with patch("agent.ntfy_notif.os.geteuid", create=True, return_value=1000):
                with self.assertRaises(NtfyNotifPermissionError) as ctx:
                    write_templates_result(templates(), self.settings)
        finally:
            self.privileges.start()
        self.assertIn("not running as root", str(ctx.exception))
        self.assertIn("CAP_CHOWN", str(ctx.exception))


class HistoryTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.history = Path(self.tmp.name) / "history.jsonl"
        self.settings = NtfyNotifSettings(history_path=self.history, queue_dir=Path(self.tmp.name) / "queue")

    def tearDown(self):
        self.tmp.cleanup()

    def write_history(self, rows, trailing_newline=True):
        text = "\n".join(row if isinstance(row, str) else json.dumps(row) for row in rows)
        self.history.write_text(text + ("\n" if trailing_newline else ""), encoding="utf-8")

    def test_iter_lines_reverse_handles_small_chunks_and_unicode(self):
        lines = [f"ligne {index} é€😀" for index in range(50)]
        self.history.write_text("\n".join(lines), encoding="utf-8")
        self.assertEqual(list(iter_lines_reverse(self.history, chunk_size=7)), list(reversed(lines)))

    def test_most_recent_first_with_limit(self):
        self.write_history([{"ts": i, "event": "test", "status": "sent", "title": f"t{i}", "message": ""} for i in range(10)])
        result = read_history_result(limit=3, settings=self.settings)
        self.assertEqual([entry["ts"] for entry in result["entries"]], [9, 8, 7])

    def test_filters_and_invalid_lines(self):
        self.write_history(
            [
                {"ts": 1, "event": "ups.onbatt", "status": "queued", "title": "a", "message": "m"},
                "not json",
                {"ts": 2, "event": "ups.onbatt", "status": "sent", "title": "a", "message": "m"},
                {"ts": 3, "event": "test", "status": "muted", "title": "b", "message": "m"},
                "[1, 2]",
            ],
            trailing_newline=False,
        )
        result = read_history_result(event="ups.onbatt", settings=self.settings)
        self.assertEqual([entry["ts"] for entry in result["entries"]], [2, 1])
        self.assertEqual(result["skipped_lines"], 2)
        result = read_history_result(status="muted", settings=self.settings)
        self.assertEqual([entry["event"] for entry in result["entries"]], ["test"])

    def test_invalid_filters_are_rejected(self):
        with self.assertRaises(NtfyNotifValidationError):
            read_history_result(status="deleted", settings=self.settings)
        with self.assertRaises(NtfyNotifValidationError):
            read_history_result(event="../etc", settings=self.settings)

    def test_missing_file_returns_empty_list(self):
        result = read_history_result(settings=self.settings)
        self.assertEqual(result["entries"], [])

    def test_queue_count_and_oldest_age(self):
        queue = self.settings.queue_dir
        queue.mkdir()
        (queue / "a.json").write_text(json.dumps({"ts": 1000, "event": "x", "ntfy": {}}))
        (queue / "b.json").write_text(json.dumps({"ts": 900, "event": "y", "ntfy": {}}))
        (queue / "ignored.tmp").write_text("{}")
        result = read_queue_result(self.settings, now=1000)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["oldest_ts"], 900)
        self.assertEqual(result["oldest_age_seconds"], 100)

    def test_queue_missing_dir(self):
        result = read_queue_result(self.settings, now=0)
        self.assertEqual(result["count"], 0)
        self.assertIsNone(result["oldest_age_seconds"])


class SendTestTests(TestCase):
    def test_request_validation(self):
        self.assertEqual(validate_test_request("ups.onbatt", {"charge": "80", "runtime": "1200"}), [])
        self.assertTrue(validate_test_request("-h", {}))
        self.assertTrue(validate_test_request("test", {"bad-key": "x"}))
        self.assertTrue(validate_test_request("test", {"texte": "a\nb"}))
        self.assertTrue(validate_test_request("test", {"texte": "x" * 101}))
        self.assertTrue(validate_test_request("test", {"texte": 5}))

    def test_command_is_an_argument_list(self):
        self.assertEqual(
            build_test_command("/usr/local/bin/ntfy-send", "ups.onbatt", {"charge": "80; rm -rf /"}),
            ["/usr/local/bin/ntfy-send", "ups.onbatt", "charge=80; rm -rf /"],
        )

    def test_runs_without_shell_and_with_timeout(self):
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="sent tk_abcdefghijkl\n", stderr="")
        settings = NtfyNotifSettings(send_command="/usr/local/bin/ntfy-send")
        with patch("agent.ntfy_notif.subprocess.run", return_value=completed) as run_mock:
            result = send_test_result("test", {"texte": "bonjour"}, settings)

        args, kwargs = run_mock.call_args
        self.assertEqual(args[0], ["/usr/local/bin/ntfy-send", "test", "texte=bonjour"])
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["timeout"], 30)
        self.assertTrue(result["ok"])
        self.assertEqual(result["return_code"], 0)
        self.assertNotIn("tk_abcdefghijkl", result["stdout_log"])

    def test_invalid_request_never_runs_command(self):
        with patch("agent.ntfy_notif.subprocess.run") as run_mock:
            with self.assertRaises(NtfyNotifValidationError):
                send_test_result("test", {"texte": "a\nb"})
        run_mock.assert_not_called()

    def test_timeout_is_reported(self):
        with patch("agent.ntfy_notif.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=30)):
            result = send_test_result("test", {})
        self.assertFalse(result["ok"])
        self.assertIsNone(result["return_code"])
