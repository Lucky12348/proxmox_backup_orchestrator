from typing import Any
from unittest import TestCase

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import ActivityEvent
from app.schemas.host_notifications import HostNotificationTemplates, HostNotificationTestRequest
from app.services.host_agent import HostAgentError, HostAgentResult
from app.services.host_notifications import (
    describe_diff,
    diff_templates,
    get_history,
    save_templates,
    send_test,
)


TEMPLATES = {
    "defaults": {"topic": "pve", "click": "https://pve.lan", "icon": "", "late_after_sec": 300},
    "events": {
        "test": {"enabled": True, "priority": 3, "emoji": "bell", "title": "Test", "message": "{texte}"},
        "ups.onbatt": {"enabled": True, "priority": 4, "emoji": "battery", "title": "Batterie", "message": "{charge}%"},
    },
}


def result(payload: dict[str, Any]) -> HostAgentResult:
    return HostAgentResult(
        ok=bool(payload.get("ok", True)),
        message="",
        stdout_log=None,
        stderr_log=None,
        command_summary=None,
        execution_cwd=None,
        return_code=payload.get("return_code"),
        payload=payload,
    )


def agent_error(status_code: int, payload: dict[str, Any]) -> HostAgentError:
    return HostAgentError(
        "agent error",
        stdout_log=None,
        stderr_log=None,
        command_summary=None,
        execution_cwd=None,
        return_code=status_code,
        status_code=status_code,
        payload=payload,
    )


class FakeAgent:
    def __init__(self, *, current=None, put_error=None, post_payload=None, post_error=None):
        self.current = current
        self.put_error = put_error
        self.post_payload = post_payload or {"ok": True, "return_code": 0, "message": "ok"}
        self.post_error = post_error
        self.calls: list[tuple[str, str, Any]] = []

    def get(self, path, params=None):
        self.calls.append(("GET", path, params))
        if path == "/notifications/templates":
            return result({"ok": True, "templates": self.current})
        return result({"ok": True, "entries": [], "skipped_lines": 0})

    def put(self, path, payload):
        self.calls.append(("PUT", path, payload))
        if self.put_error:
            raise self.put_error
        return result({"ok": True, "templates": payload, "backup_path": "/etc/ntfy-notif/backups/x.json"})

    def post(self, path, payload):
        self.calls.append(("POST", path, payload))
        if self.post_error:
            raise self.post_error
        return result(self.post_payload)


class HostNotificationServiceTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def activity(self) -> list[ActivityEvent]:
        return list(self.session.query(ActivityEvent).order_by(ActivityEvent.id))

    def test_save_relays_to_agent_and_logs_diff(self):
        previous = {
            "defaults": TEMPLATES["defaults"],
            "events": {"test": TEMPLATES["events"]["test"] | {"priority": 2}, "old.event": TEMPLATES["events"]["test"]},
        }
        agent = FakeAgent(current=previous)
        save_templates(self.session, HostNotificationTemplates.model_validate(TEMPLATES), agent)

        put_call = [call for call in agent.calls if call[0] == "PUT"][0]
        self.assertEqual(put_call[2], TEMPLATES)
        entries = self.activity()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].status, "success")
        self.assertEqual(entries[0].details["diff"]["added"], ["ups.onbatt"])
        self.assertEqual(entries[0].details["diff"]["removed"], ["old.event"])
        self.assertEqual(entries[0].details["diff"]["changed"], ["test"])

    def test_agent_validation_error_becomes_422_and_is_logged(self):
        agent = FakeAgent(
            current=TEMPLATES,
            put_error=agent_error(422, {"message": "x", "errors": ["events.test.title: too long"]}),
        )
        with self.assertRaises(HTTPException) as ctx:
            save_templates(self.session, HostNotificationTemplates.model_validate(TEMPLATES), agent)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("events.test.title: too long", ctx.exception.detail["message"])
        self.assertEqual(self.activity()[0].status, "failed")

    def test_old_agent_without_endpoints_is_reported(self):
        agent = FakeAgent(current=TEMPLATES, put_error=agent_error(404, {"detail": "Not Found"}))
        with self.assertRaises(HTTPException) as ctx:
            save_templates(self.session, HostNotificationTemplates.model_validate(TEMPLATES), agent)
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("mettez l'agent a jour", ctx.exception.detail)

    def test_send_test_logs_return_code(self):
        agent = FakeAgent(post_payload={"ok": False, "return_code": 3, "message": "exit 3"})
        payload = send_test(self.session, HostNotificationTestRequest(event="test", vars={"texte": "hello"}), agent)
        self.assertEqual(payload["return_code"], 3)
        self.assertEqual(agent.calls[0], ("POST", "/notifications/test", {"event": "test", "vars": {"texte": "hello"}}))
        entry = self.activity()[0]
        self.assertEqual(entry.action, "test")
        self.assertEqual(entry.status, "failed")
        self.assertEqual(entry.details["return_code"], 3)

    def test_history_only_sends_set_filters(self):
        agent = FakeAgent()
        get_history(50, None, "sent", agent)
        self.assertEqual(agent.calls[0], ("GET", "/notifications/history", {"limit": 50, "status": "sent"}))

    def test_describe_diff(self):
        diff = diff_templates(None, TEMPLATES)
        self.assertEqual(describe_diff(diff), "etat precedent inconnu")
        self.assertEqual(describe_diff(diff_templates(TEMPLATES, TEMPLATES)), "aucun changement")


class HostNotificationSchemaTests(TestCase):
    def test_unknown_keys_and_bad_values_are_rejected(self):
        for mutate in (
            lambda d: d.update(extra=1),
            lambda d: d["defaults"].update(color="red"),
            lambda d: d["events"]["test"].update(priority=6),
            lambda d: d["events"]["test"].update(priority="3"),
            lambda d: d["events"]["test"].update(enabled=1),
            lambda d: d["events"]["test"].update(emoji="Bell"),
            lambda d: d["events"]["test"].update(title="x" * 61),
            lambda d: d["events"]["test"].update(title="  "),
            lambda d: d["events"]["test"].update(message="x" * 201),
            lambda d: d["events"]["test"].update(click="ftp://x"),
            lambda d: d["defaults"].update(late_after_sec=86401),
            lambda d: d["defaults"].update(topic="a b"),
            lambda d: d["events"].update({"Bad.Code": d["events"]["test"]}),
        ):
            data = {"defaults": dict(TEMPLATES["defaults"]), "events": {k: dict(v) for k, v in TEMPLATES["events"].items()}}
            mutate(data)
            with self.assertRaises(ValidationError):
                HostNotificationTemplates.model_validate(data)

    def test_optional_fields_are_not_written_when_absent(self):
        payload = HostNotificationTemplates.model_validate(TEMPLATES).to_file_payload()
        self.assertNotIn("topic", payload["events"]["test"])
        self.assertEqual(payload["defaults"]["icon"], "")

    def test_test_request_validation(self):
        HostNotificationTestRequest(event="f2b.ban", vars={"ip": "1.2.3.4", "jail": "sshd"})
        for kwargs in ({"event": "-h"}, {"event": "test", "vars": {"a-b": "x"}}, {"event": "test", "vars": {"a": "x\ny"}}, {"event": "test", "vars": {"a": "x" * 101}}):
            with self.assertRaises(ValidationError):
                HostNotificationTestRequest(**kwargs)
