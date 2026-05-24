from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from app.core.config import Settings, get_settings


logger = logging.getLogger(__name__)
_last_agent_degraded_sent_at: dict[str, float] = {}
_last_low_coverage_sent_at: float | None = None
_AGENT_DEGRADED_COOLDOWN_SECONDS = 3600
_LOW_COVERAGE_COOLDOWN_SECONDS = 3600


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
        if not self.settings.notifications_enabled:
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
        return NotificationStatus(
            enabled=self.settings.notifications_enabled,
            provider=self.provider,
            configured=self._configured,
            base_url=self.settings.ntfy_base_url.rstrip("/") if self.settings.ntfy_base_url else None,
            topic=_mask_secret(self.settings.ntfy_topic),
            username=self.settings.ntfy_username or None,
            events={
                "backup_success": self.settings.notify_on_backup_success,
                "backup_failure": self.settings.notify_on_backup_failure,
                "disk_eject_ready": self.settings.notify_on_disk_eject_ready,
                "update_result": self.settings.notify_on_update_result,
                "agent_degraded": self.settings.notify_on_agent_degraded,
                "low_coverage": self.settings.notify_on_low_coverage,
            },
            low_coverage_threshold_percent=self.settings.low_coverage_threshold_percent,
        )

    @property
    def _configured(self) -> bool:
        return bool(self.settings.ntfy_base_url.strip() and self.settings.ntfy_topic.strip())

    @property
    def _topic_url(self) -> str:
        return f"{self.settings.ntfy_base_url.rstrip('/')}/{self.settings.ntfy_topic.strip()}"


def get_notification_service(settings: Settings | None = None) -> NotificationService:
    return NotificationService(settings)


def notify_backup_success(disk_label_or_serial: str) -> None:
    try:
        settings = get_settings()
        if not settings.notify_on_backup_success:
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
        if not settings.notify_on_backup_failure:
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
        if not settings.notify_on_disk_eject_ready:
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
        if not settings.notify_on_update_result:
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
        if not settings.notify_on_agent_degraded:
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
        if not settings.notify_on_low_coverage:
            _log_event("low_coverage", False, reason="disabled")
            return
        threshold = settings.low_coverage_threshold_percent
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
