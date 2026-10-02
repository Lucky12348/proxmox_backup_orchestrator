"""Relay between the operator UI and the Proxmox host agent's ntfy notification endpoints.

The host owns the notification engine (templates.json, ntfy-send, history,
queue). The app VM never sees the ntfy token: the agent does not read it.
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ActivityEvent
from app.schemas.host_notifications import HostNotificationTemplates, HostNotificationTestRequest
from app.services.host_agent import HostAgentClient, HostAgentError, get_host_agent_client


logger = logging.getLogger(__name__)

ACTIVITY_CATEGORY = "host_notifications"
ACTIVITY_LIST_LIMIT = 100


def get_templates(client: HostAgentClient | None = None) -> dict[str, Any]:
    return _call(lambda agent: agent.get("/notifications/templates"), client)


def save_templates(db: Session, templates: HostNotificationTemplates, client: HostAgentClient | None = None) -> dict[str, Any]:
    client = client or get_host_agent_client()
    payload = templates.to_file_payload()

    previous: dict[str, Any] | None = None
    try:
        previous = client.get("/notifications/templates").payload.get("templates")
    except HostAgentError as exc:
        # Diff is informational only; the save itself still goes through.
        logger.warning("Could not load current ntfy templates before saving: %s", exc)

    diff = diff_templates(previous, payload)
    try:
        result = _call(lambda agent: agent.put("/notifications/templates", payload), client)
    except HTTPException as exc:
        record_activity(
            db,
            action="templates_update",
            status="failed",
            summary=f"Echec de l'enregistrement des modeles ntfy : {_detail_text(exc.detail)}",
            details={"diff": diff},
        )
        raise

    record_activity(
        db,
        action="templates_update",
        status="success",
        summary=f"Modeles ntfy enregistres sur l'hote Proxmox ({describe_diff(diff)}).",
        details={"diff": diff, "backup_path": result.get("backup_path")},
    )
    return result


def send_test(db: Session, request: HostNotificationTestRequest, client: HostAgentClient | None = None) -> dict[str, Any]:
    try:
        result = _call(lambda agent: agent.post("/notifications/test", request.model_dump()), client)
    except HTTPException as exc:
        record_activity(
            db,
            action="test",
            status="failed",
            summary=f"Test ntfy `{request.event}` impossible : {_detail_text(exc.detail)}",
            details={"event": request.event, "vars": request.vars},
        )
        raise

    ok = bool(result.get("ok"))
    return_code = result.get("return_code")
    record_activity(
        db,
        action="test",
        status="success" if ok else "failed",
        summary=(
            f"Test ntfy `{request.event}` envoye (code retour {return_code})."
            if ok
            else f"Test ntfy `{request.event}` en echec (code retour {return_code})."
        ),
        details={"event": request.event, "vars": request.vars, "return_code": return_code},
    )
    return result


def get_history(
    limit: int,
    event: str | None,
    status_filter: str | None,
    client: HostAgentClient | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit}
    if event:
        params["event"] = event
    if status_filter:
        params["status"] = status_filter
    return _call(lambda agent: agent.get("/notifications/history", params), client)


def get_queue(client: HostAgentClient | None = None) -> dict[str, Any]:
    return _call(lambda agent: agent.get("/notifications/queue"), client)


def record_activity(db: Session, *, action: str, status: str, summary: str, details: dict[str, Any] | None = None) -> ActivityEvent:
    event = ActivityEvent(
        created_at=datetime.utcnow(),
        category=ACTIVITY_CATEGORY,
        action=action,
        status=status,
        summary=summary,
        details=details,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def list_activity_events(db: Session, limit: int = ACTIVITY_LIST_LIMIT) -> list[ActivityEvent]:
    return list(db.scalars(select(ActivityEvent).order_by(ActivityEvent.created_at.desc(), ActivityEvent.id.desc()).limit(limit)))


def diff_templates(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(previous, dict):
        return {"added": [], "removed": [], "changed": [], "defaults_changed": False, "unknown_previous": True}
    previous_events = previous.get("events") if isinstance(previous.get("events"), dict) else {}
    current_events = current.get("events", {})
    return {
        "added": sorted(set(current_events) - set(previous_events)),
        "removed": sorted(set(previous_events) - set(current_events)),
        "changed": sorted(
            code for code in set(current_events) & set(previous_events) if current_events[code] != previous_events[code]
        ),
        "defaults_changed": previous.get("defaults") != current.get("defaults"),
        "unknown_previous": False,
    }


def describe_diff(diff: dict[str, Any]) -> str:
    if diff.get("unknown_previous"):
        return "etat precedent inconnu"
    parts = []
    if diff["defaults_changed"]:
        parts.append("reglages generaux modifies")
    for key, label in (("changed", "modifie(s)"), ("added", "ajoute(s)"), ("removed", "supprime(s)")):
        codes = diff[key]
        if codes:
            shown = ", ".join(codes[:5]) + (" ..." if len(codes) > 5 else "")
            parts.append(f"{len(codes)} evenement(s) {label} : {shown}")
    return "; ".join(parts) if parts else "aucun changement"


def _call(action, client: HostAgentClient | None) -> dict[str, Any]:
    agent = client or get_host_agent_client()
    try:
        return action(agent).payload
    except HostAgentError as exc:
        raise _to_http_exception(exc) from exc


def _to_http_exception(exc: HostAgentError) -> HTTPException:
    payload = exc.payload or {}
    message = payload.get("message") or str(exc)
    errors = payload.get("errors")
    if exc.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY and isinstance(errors, list):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Validation refusee par l'agent hote : " + "; ".join(map(str, errors)), "errors": errors},
        )
    if exc.status_code == status.HTTP_404_NOT_FOUND and str(payload.get("command_summary") or "").startswith("notifications-"):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    if exc.status_code == status.HTTP_404_NOT_FOUND:
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="L'agent hote Proxmox ne connait pas les endpoints /notifications : mettez l'agent a jour.",
        )
    if exc.status_code == status.HTTP_403_FORBIDDEN:
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message)


def _detail_text(detail: Any) -> str:
    if isinstance(detail, dict):
        return str(detail.get("message") or detail)
    return str(detail)
