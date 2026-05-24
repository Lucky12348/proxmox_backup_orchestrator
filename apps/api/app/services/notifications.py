from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models import NotificationPreferences


logger = logging.getLogger(__name__)
_last_agent_degraded_sent_at: dict[str, float] = {}
_last_low_coverage_sent_at: float | None = None
_AGENT_DEGRADED_COOLDOWN_SECONDS = 3600
_LOW_COVERAGE_COOLDOWN_SECONDS = 3600
PREFERENCE_ID = 1
EVENT_FIELDS = {
    "backup_success": "notify_on_backup_success",
    "backup_failure": "notify_on_backup_failure",
    "disk_eject_ready": "notify_on_disk_eject_ready",
    "update_result": "notify_on_update_result",
    "agent_degraded": "notify_on_agent_degraded",
    "low_coverage": "notify_on_low_coverage",
    "disk_new_detected": "notify_on_disk_new_detected",
    "disk_known_detected": "notify_on_disk_known_detected",
    "planned_disk_detected": "notify_on_planned_disk_detected",
    "planned_backup_reminder": "notify_on_planned_backup_reminder",
    "planned_backup_started": "notify_on_planned_backup_started",
    "planned_confirmation_required": "notify_on_planned_confirmation_required",
    "planned_backup_missed": "notify_on_planned_backup_missed",
}


@dataclass(frozen=True)
class NotificationStatus:
    enabled: bool
    provider: str
    configured: bool
    base_url: str | None
    topic: str | None
    username: str | None
    events: dict[str, bool]
    low_coverage_threshold_percent: float
    environment_enabled: bool
    preferences_enabled: bool | None
    disk_detection_notify_cooldown_seconds: int


@dataclass(frozen=True)
class EffectiveNotificationPreferences:
    notifications_enabled_override: bool | None
    events: dict[str, bool]
    low_coverage_threshold_percent: float
    disk_detection_notify_cooldown_seconds: int
    updated_at: datetime | None = None

    def event_enabled(self, event_name: str) -> bool:
        return self.events.get(event_name, True)


class NotificationService:
    provider = "ntfy"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def send(
        self,
        title: str,
        message: str,
        priority: str = "default",
        tags: list[str] | tuple[str, ...] | str | None = None,
    ) -> bool:
        preferences = get_effective_notification_preferences()
        if not self.settings.notifications_enabled or preferences.notifications_enabled_override is False:
            return False
        if not self._configured:
            logger.warning("Notification skipped: ntfy is enabled but NTFY_BASE_URL or NTFY_TOPIC is missing.")
            return False

        headers = {
            "Title": title,
            "Priority": priority,
        }
        tag_header = _format_tags(tags)
        if tag_header:
            headers["Tags"] = tag_header

        auth = None
        if self.settings.ntfy_username or self.settings.ntfy_password:
            auth = (self.settings.ntfy_username, self.settings.ntfy_password)

        try:
            response = httpx.post(
                self._topic_url,
                content=message.encode("utf-8"),
                headers=headers,
                auth=auth,
                timeout=10,
            )
            response.raise_for_status()
            return True
        except Exception as exc:
            logger.warning("Notification send failed via ntfy: %s", _sanitize_error(exc, self.settings.ntfy_password))
            return False

    def status(self) -> NotificationStatus:
        preferences = get_effective_notification_preferences(self.settings)
        return NotificationStatus(
            enabled=self.settings.notifications_enabled and preferences.notifications_enabled_override is not False,
            provider=self.provider,
            configured=self._configured,
            base_url=self.settings.ntfy_base_url.rstrip("/") if self.settings.ntfy_base_url else None,
            topic=_mask_secret(self.settings.ntfy_topic),
            username=self.settings.ntfy_username or None,
            events=preferences.events,
            low_coverage_threshold_percent=preferences.low_coverage_threshold_percent,
            environment_enabled=self.settings.notifications_enabled,
            preferences_enabled=preferences.notifications_enabled_override,
            disk_detection_notify_cooldown_seconds=preferences.disk_detection_notify_cooldown_seconds,
        )

    @property
    def _configured(self) -> bool:
        return bool(self.settings.ntfy_base_url.strip() and self.settings.ntfy_topic.strip())

    @property
    def _topic_url(self) -> str:
        return f"{self.settings.ntfy_base_url.rstrip('/')}/{self.settings.ntfy_topic.strip()}"


def get_notification_service(settings: Settings | None = None) -> NotificationService:
    return NotificationService(settings)


def get_effective_notification_preferences(
    settings: Settings | None = None,
    db: Session | None = None,
) -> EffectiveNotificationPreferences:
    current_settings = settings or get_settings()
    defaults = _preferences_from_settings(current_settings)
    try:
        if db is not None:
            stored = db.get(NotificationPreferences, PREFERENCE_ID)
            return _merge_preferences(defaults, stored)
        with SessionLocal() as session:
            stored = session.get(NotificationPreferences, PREFERENCE_ID)
            return _merge_preferences(defaults, stored)
    except Exception as exc:
        logger.warning("Notification preferences unavailable, using environment defaults: %s", _sanitize_error(exc, current_settings.ntfy_password))
        return defaults


def get_notification_preferences(db: Session, settings: Settings | None = None) -> EffectiveNotificationPreferences:
    return get_effective_notification_preferences(settings, db)


def update_notification_preferences(
    db: Session,
    values: dict[str, object],
    settings: Settings | None = None,
) -> EffectiveNotificationPreferences:
    stored = db.get(NotificationPreferences, PREFERENCE_ID)
    if stored is None:
        stored = _model_from_effective(_preferences_from_settings(settings or get_settings()))
        db.add(stored)
    for field, value in values.items():
        if value is not None or field == "notifications_enabled_override":
            setattr(stored, field, value)
    stored.updated_at = datetime.utcnow()
    db.add(stored)
    db.commit()
    db.refresh(stored)
    return get_effective_notification_preferences(settings, db)


def reset_notification_preferences(db: Session, settings: Settings | None = None) -> EffectiveNotificationPreferences:
    stored = db.get(NotificationPreferences, PREFERENCE_ID)
    if stored is not None:
        db.delete(stored)
        db.commit()
    return get_effective_notification_preferences(settings, db)


def get_disk_detection_notify_cooldown_seconds() -> int:
    return get_effective_notification_preferences().disk_detection_notify_cooldown_seconds


def notify_backup_success(disk_label_or_serial: str) -> None:
    try:
        settings = get_settings()
        if not _event_enabled("backup_success", settings):
            _log_event("backup_success", False, reason="disabled")
            return
        sent = get_notification_service(settings).send(
            "PBO: Backup externe termine",
            f"Export PBS vers disque {disk_label_or_serial} termine avec succes.",
            tags=["white_check_mark", "floppy_disk"],
        )
        _log_event("backup_success", sent)
    except Exception as exc:
        _log_event_error("backup_success", exc)


def notify_backup_failure(disk_label_or_serial: str, step: str | None, error: str | None) -> None:
    try:
        settings = get_settings()
        if not _event_enabled("backup_failure", settings):
            _log_event("backup_failure", False, reason="disabled")
            return
        short_error = _shorten(error or "Erreur inconnue.")
        clean_step = step or "unknown"
        sent = get_notification_service(settings).send(
            "PBO: Backup externe echoue",
            f"Disque {disk_label_or_serial}. Etape {clean_step}. Erreur: {short_error}",
            priority="high",
            tags=["warning", "floppy_disk"],
        )
        _log_event("backup_failure", sent)
    except Exception as exc:
        _log_event_error("backup_failure", exc)


def notify_disk_eject_ready(serial: str) -> None:
    try:
        settings = get_settings()
        if not _event_enabled("disk_eject_ready", settings):
            _log_event("disk_eject_ready", False, reason="disabled")
            return
        sent = get_notification_service(settings).send(
            "PBO: Disque pret a retirer",
            f"Le disque externe {serial} peut etre retire.",
            tags=["eject", "white_check_mark"],
        )
        _log_event("disk_eject_ready", sent)
    except Exception as exc:
        _log_event_error("disk_eject_ready", exc)


def notify_update_result(component: str, success: bool, message: str | None = None) -> None:
    try:
        settings = get_settings()
        if not _event_enabled("update_result", settings):
            _log_event("update_result", False, reason="disabled")
            return
        if success:
            sent = get_notification_service(settings).send(
                "PBO: Mise a jour terminee",
                f"{component} est a jour.",
                tags=["arrow_up", "white_check_mark"],
            )
            _log_event("update_result", sent)
            return
        sent = get_notification_service(settings).send(
            "PBO: Mise a jour echouee",
            f"{component}: {_shorten(message or 'Erreur inconnue.')}",
            priority="high",
            tags=["arrow_up", "warning"],
        )
        _log_event("update_result", sent)
    except Exception as exc:
        _log_event_error("update_result", exc)


def notify_agent_degraded(status_payload: dict[str, object]) -> None:
    try:
        settings = get_settings()
        if not _event_enabled("agent_degraded", settings):
            _log_event("agent_degraded", False, reason="disabled")
            return
        status = str(status_payload.get("status") or "")
        if status not in {"degraded", "disconnected"}:
            return

        hostname = str(status_payload.get("hostname") or "agent hote")
        key = f"{hostname}:{status}"
        now = time.monotonic()
        previous = _last_agent_degraded_sent_at.get(key)
        if previous is not None and now - previous < _AGENT_DEGRADED_COOLDOWN_SECONDS:
            _log_event("agent_degraded", False, reason="cooldown")
            return

        _last_agent_degraded_sent_at[key] = now
        age = status_payload.get("last_seen_age_seconds")
        age_message = f" Dernier heartbeat il y a {age}s." if isinstance(age, int) else ""
        sent = get_notification_service(settings).send(
            "PBO: Agent degrade",
            f"L'agent {hostname} est {status}.{age_message}",
            priority="high",
            tags=["warning", "satellite"],
        )
        _log_event("agent_degraded", sent)
    except Exception as exc:
        _log_event_error("agent_degraded", exc)


def notify_low_coverage(coverage_percent: float, protected_vms: int, total_vms: int) -> None:
    global _last_low_coverage_sent_at
    try:
        settings = get_settings()
        preferences = get_effective_notification_preferences(settings)
        if not preferences.event_enabled("low_coverage"):
            _log_event("low_coverage", False, reason="disabled")
            return
        threshold = preferences.low_coverage_threshold_percent
        if total_vms <= 0 or coverage_percent >= threshold:
            return

        now = time.monotonic()
        if _last_low_coverage_sent_at is not None and now - _last_low_coverage_sent_at < _LOW_COVERAGE_COOLDOWN_SECONDS:
            _log_event("low_coverage", False, reason="cooldown")
            return
        _last_low_coverage_sent_at = now
        sent = get_notification_service(settings).send(
            "PBO: Couverture backup incomplete",
            f"Couverture PBS {coverage_percent:g}% ({protected_vms}/{total_vms}) sous le seuil {threshold:g}%.",
            priority="high",
            tags=["warning", "bar_chart"],
        )
        _log_event("low_coverage", sent)
    except Exception as exc:
        _log_event_error("low_coverage", exc)


def notify_new_disk_detected(description: str) -> None:
    _send_event_notification(
        "disk_new_detected",
        "PBO: Nouveau disque detecte",
        description,
        tags=["mag", "floppy_disk"],
    )


def notify_known_disk_detected(description: str) -> None:
    _send_event_notification(
        "disk_known_detected",
        "PBO: Disque connu detecte",
        description,
        tags=["floppy_disk", "white_check_mark"],
    )


def notify_expected_disk_detected(serial: str, event_title: str) -> None:
    _send_event_notification(
        "planned_disk_detected",
        "PBO: Disque attendu detecte",
        f"Le disque {serial} est branche pour {event_title}.",
        tags=["calendar", "floppy_disk", "white_check_mark"],
    )


def notify_planned_backup_reminder(serial: str, event_title: str, start: str, end: str) -> None:
    _send_event_notification(
        "planned_backup_reminder",
        "PBO: Backup planifie",
        f"Branche le disque {serial} pour {event_title}. Fenetre: {start} -> {end}.",
        tags=["calendar", "bell", "floppy_disk"],
    )


def notify_planned_backup_started(event_title: str) -> None:
    _send_event_notification(
        "planned_backup_started",
        "PBO: Backup planifie demarre",
        f"{event_title} demarre automatiquement.",
        tags=["calendar", "arrow_forward", "floppy_disk"],
    )


def notify_planned_confirmation_required(event_title: str) -> None:
    _send_event_notification(
        "planned_confirmation_required",
        "PBO: Confirmation requise",
        f"Le disque est branche pour {event_title}. Confirme le demarrage dans PBO.",
        priority="high",
        tags=["warning", "calendar"],
    )


def notify_planned_backup_missed(event_title: str) -> None:
    _send_event_notification(
        "planned_backup_missed",
        "PBO: Backup planifie manque",
        f"{event_title}: disque non detecte ou confirmation absente avant la fin de la fenetre.",
        priority="high",
        tags=["warning", "calendar"],
    )


def _send_event_notification(
    event_name: str,
    title: str,
    message: str,
    priority: str = "default",
    tags: list[str] | tuple[str, ...] | str | None = None,
) -> None:
    try:
        if not _event_enabled(event_name):
            _log_event(event_name, False, reason="disabled")
            return
        service = get_notification_service()
        sent = service.send(title, message, priority=priority, tags=tags)
        _log_event(event_name, sent)
    except Exception as exc:
        _log_event_error(event_name, exc)


def _format_tags(tags: list[str] | tuple[str, ...] | str | None) -> str | None:
    if tags is None:
        return None
    if isinstance(tags, str):
        return tags
    return ",".join(tag for tag in tags if tag)


def _event_enabled(event_name: str, settings: Settings | None = None) -> bool:
    return get_effective_notification_preferences(settings).event_enabled(event_name)


def _preferences_from_settings(settings: Settings) -> EffectiveNotificationPreferences:
    return EffectiveNotificationPreferences(
        notifications_enabled_override=None,
        events={
            "backup_success": settings.notify_on_backup_success,
            "backup_failure": settings.notify_on_backup_failure,
            "disk_eject_ready": settings.notify_on_disk_eject_ready,
            "update_result": settings.notify_on_update_result,
            "agent_degraded": settings.notify_on_agent_degraded,
            "low_coverage": settings.notify_on_low_coverage,
            "disk_new_detected": settings.notify_on_disk_new_detected,
            "disk_known_detected": settings.notify_on_disk_known_detected,
            "planned_disk_detected": settings.notify_on_planned_disk_detected,
            "planned_backup_reminder": settings.notify_on_planned_backup_reminder,
            "planned_backup_started": settings.notify_on_planned_backup_started,
            "planned_confirmation_required": settings.notify_on_planned_confirmation_required,
            "planned_backup_missed": settings.notify_on_planned_backup_missed,
        },
        low_coverage_threshold_percent=settings.low_coverage_threshold_percent,
        disk_detection_notify_cooldown_seconds=settings.disk_detection_notify_cooldown_seconds,
    )


def _merge_preferences(
    defaults: EffectiveNotificationPreferences,
    stored: NotificationPreferences | None,
) -> EffectiveNotificationPreferences:
    if stored is None:
        return defaults
    return EffectiveNotificationPreferences(
        notifications_enabled_override=stored.notifications_enabled_override,
        events={event: bool(getattr(stored, field)) for event, field in EVENT_FIELDS.items()},
        low_coverage_threshold_percent=stored.low_coverage_threshold_percent,
        disk_detection_notify_cooldown_seconds=stored.disk_detection_notify_cooldown_seconds,
        updated_at=stored.updated_at,
    )


def _model_from_effective(preferences: EffectiveNotificationPreferences) -> NotificationPreferences:
    values = {
        "id": PREFERENCE_ID,
        "notifications_enabled_override": preferences.notifications_enabled_override,
        "low_coverage_threshold_percent": preferences.low_coverage_threshold_percent,
        "disk_detection_notify_cooldown_seconds": preferences.disk_detection_notify_cooldown_seconds,
    }
    for event, field in EVENT_FIELDS.items():
        values[field] = preferences.events[event]
    return NotificationPreferences(**values)


def _mask_secret(value: str) -> str | None:
    clean = value.strip()
    if not clean:
        return None
    if len(clean) <= 8:
        return "***"
    return f"{clean[:4]}...{clean[-4:]}"


def _shorten(value: str, limit: int = 220) -> str:
    clean = " ".join(value.split())
    if len(clean) <= limit:
        return clean
    return f"{clean[: limit - 3]}..."


def _sanitize_error(exc: Exception, password: str | None = None) -> str:
    message = str(exc)
    if password:
        message = message.replace(password, "***")
    return _shorten(message)


def _log_event(event_name: str, sent: bool, reason: str | None = None) -> None:
    if reason:
        logger.info("notification event=%s sent=%s reason=%s", event_name, sent, reason)
        return
    logger.info("notification event=%s sent=%s", event_name, sent)


def _log_event_error(event_name: str, exc: Exception) -> None:
    try:
        password = get_settings().ntfy_password
    except Exception:
        password = None
    logger.warning("notification event=%s sent=false error=%s", event_name, _sanitize_error(exc, password))
