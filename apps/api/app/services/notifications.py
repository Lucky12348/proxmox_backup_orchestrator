from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from app.core.config import Settings, get_settings


logger = logging.getLogger(__name__)
_last_agent_degraded_sent_at: dict[str, float] = {}
_AGENT_DEGRADED_COOLDOWN_SECONDS = 3600


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
    settings = get_settings()
    if not settings.notify_on_backup_success:
        return
    get_notification_service(settings).send(
        "PBO: Backup externe terminé",
        f"Export PBS vers disque {disk_label_or_serial} terminé avec succès.",
        tags=["white_check_mark", "floppy_disk"],
    )


def notify_backup_failure(disk_label_or_serial: str, step: str | None, error: str | None) -> None:
    settings = get_settings()
    if not settings.notify_on_backup_failure:
        return
    short_error = _shorten(error or "Erreur inconnue.")
    clean_step = step or "unknown"
    get_notification_service(settings).send(
        "PBO: Backup externe échoué",
        f"Disque {disk_label_or_serial}. Étape {clean_step}. Erreur: {short_error}",
        priority="high",
        tags=["warning", "floppy_disk"],
    )


def notify_disk_eject_ready(serial: str) -> None:
    settings = get_settings()
    if not settings.notify_on_disk_eject_ready:
        return
    get_notification_service(settings).send(
        "PBO: Disque prêt à retirer",
        f"Le disque externe {serial} peut être retiré.",
        tags=["eject", "white_check_mark"],
    )


def notify_update_result(component: str, success: bool, message: str | None = None) -> None:
    settings = get_settings()
    if not settings.notify_on_update_result:
        return
    if success:
        get_notification_service(settings).send(
            "PBO: Mise à jour terminée",
            f"{component} est à jour.",
            tags=["arrow_up", "white_check_mark"],
        )
        return
    get_notification_service(settings).send(
        "PBO: Mise à jour échouée",
        f"{component}: {_shorten(message or 'Erreur inconnue.')}",
        priority="high",
        tags=["arrow_up", "warning"],
    )


def notify_agent_degraded(status_payload: dict[str, object]) -> None:
    settings = get_settings()
    if not settings.notify_on_agent_degraded:
        return
    status = str(status_payload.get("status") or "")
    if status not in {"degraded", "disconnected"}:
        return

    hostname = str(status_payload.get("hostname") or "agent hote")
    key = f"{hostname}:{status}"
    now = time.monotonic()
    previous = _last_agent_degraded_sent_at.get(key)
    if previous is not None and now - previous < _AGENT_DEGRADED_COOLDOWN_SECONDS:
        return

    _last_agent_degraded_sent_at[key] = now
    age = status_payload.get("last_seen_age_seconds")
    age_message = f" Dernier heartbeat il y a {age}s." if isinstance(age, int) else ""
    get_notification_service(settings).send(
        "PBO: Agent dégradé",
        f"L'agent {hostname} est {status}.{age_message}",
        priority="high",
        tags=["warning", "satellite"],
    )


def notify_low_coverage(coverage_percent: float, protected_vms: int, total_vms: int) -> None:
    settings = get_settings()
    if not settings.notify_on_low_coverage:
        return
    threshold = settings.low_coverage_threshold_percent
    if total_vms <= 0 or coverage_percent >= threshold:
        return
    get_notification_service(settings).send(
        "PBO: Couverture backup incomplète",
        f"Couverture PBS {coverage_percent:g}% ({protected_vms}/{total_vms}) sous le seuil {threshold:g}%.",
        priority="high",
        tags=["warning", "bar_chart"],
    )


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
