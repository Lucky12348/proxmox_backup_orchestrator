from __future__ import annotations

import re
from dataclasses import dataclass, field


_FOUND_GROUPS_RE = re.compile(r"\bfound\s+(?P<total>\d+)\s+groups?\s+to\s+sync\b", re.IGNORECASE)
_PERCENT_RE = re.compile(
    r"\bpercentage\s+done:\s+(?P<percent>\d+(?:\.\d+)?)%\s+\((?P<done>\d+)/(?P<total>\d+)\s+groups?",
    re.IGNORECASE,
)
_GROUP_FAILED_RE = re.compile(r"\bsync\s+group\s+(?P<group>\S+)\s+failed\s+-\s+(?P<reason>.+)$", re.IGNORECASE)
_GROUP_RE = re.compile(r"\b(?:re-)?sync\s+group\s+(?P<group>\S+)", re.IGNORECASE)
_SNAPSHOT_RE = re.compile(r"\b(?:re-)?sync\s+snapshot\s+(?P<snapshot>\S+)", re.IGNORECASE)
_ARCHIVE_RE = re.compile(r"\bsync\s+archive\s+(?P<archive>\S+)", re.IGNORECASE)
_DOWNLOADED_RE = re.compile(
    r"\bdownloaded\s+(?P<amount>\d+(?:\.\d+)?)\s+(?P<unit>[KMGT]?i?B)\s+\((?P<speed>[^)]+)\)",
    re.IGNORECASE,
)
_JOB_RE = re.compile(r"\b(?P<job>pbo-export-sync-[A-Za-z0-9_-]+)\b")
_REMOTE_RE = re.compile(r"\b(?P<remote>pbo-export-remote-[A-Za-z0-9_-]+)\b")
_UPID_RE = re.compile(r"\b(?P<upid>UPID:[^\s]+)")


@dataclass
class PbsProgressUpdate:
    progress_percent: float | None = None
    total_groups: int | None = None
    completed_groups: int | None = None
    current_group: str | None = None
    current_snapshot: str | None = None
    current_archive: str | None = None
    downloaded_bytes: int | None = None
    current_speed: str | None = None
    pbs_sync_job_id: str | None = None
    pbs_remote_id: str | None = None
    pbs_task_upid: str | None = None
    warnings: list[str] = field(default_factory=list)
    failed_groups: list[dict[str, str]] = field(default_factory=list)
    task_ok: bool = False
    task_error: bool = False
    partial_failure: bool = False

    @property
    def has_progress(self) -> bool:
        return any(
            value is not None
            for value in (
                self.progress_percent,
                self.total_groups,
                self.completed_groups,
                self.current_group,
                self.current_snapshot,
                self.current_archive,
                self.downloaded_bytes,
            )
        )


def parse_pbs_progress_line(line: str | None) -> PbsProgressUpdate:
    text = (line or "").strip()
    update = PbsProgressUpdate()
    if not text:
        return update

    if match := _FOUND_GROUPS_RE.search(text):
        update.total_groups = int(match.group("total"))

    if match := _PERCENT_RE.search(text):
        update.progress_percent = float(match.group("percent"))
        update.completed_groups = int(match.group("done"))
        update.total_groups = int(match.group("total"))

    if match := _GROUP_FAILED_RE.search(text):
        reason = match.group("reason").strip()
        update.failed_groups.append({"group": match.group("group"), "reason": reason})
        if "group lock failed" in reason.casefold():
            update.warnings.append(_group_lock_warning())

    if match := _GROUP_RE.search(text):
        update.current_group = match.group("group")

    if match := _SNAPSHOT_RE.search(text):
        update.current_snapshot = match.group("snapshot")
        group_parts = update.current_snapshot.split("/")
        if len(group_parts) >= 2:
            update.current_group = "/".join(group_parts[:2])

    if match := _ARCHIVE_RE.search(text):
        update.current_archive = match.group("archive")

    if match := _DOWNLOADED_RE.search(text):
        update.downloaded_bytes = _bytes_from_amount(float(match.group("amount")), match.group("unit"))
        update.current_speed = match.group("speed").strip()

    if match := _JOB_RE.search(text):
        update.pbs_sync_job_id = match.group("job")
    if match := _REMOTE_RE.search(text):
        update.pbs_remote_id = match.group("remote")
    if match := _UPID_RE.search(text):
        update.pbs_task_upid = match.group("upid")

    lowered = text.casefold()
    if "group lock failed" in lowered or "create_locked_backup_group failed" in lowered:
        update.warnings.append(_group_lock_warning())
    if "task ok" in lowered:
        update.task_ok = True
    if "task error" in lowered:
        update.task_error = True
    if "sync failed with some errors" in lowered:
        update.partial_failure = True
    if "no data changes" in lowered:
        update.warnings.append("Aucun changement de donnees detecte pour l'element courant.")

    return update


def summarize_pbs_failure(message: str | None, failed_groups: list[dict[str, str]] | None) -> str | None:
    text = (message or "").casefold()
    if "sync failed with some errors" in text or failed_groups:
        if failed_groups:
            details = ", ".join(
                f"{item.get('group')}: {item.get('reason')}"
                for item in failed_groups
                if item.get("group") and item.get("reason")
            )
            return f"Synchronisation terminee avec erreurs: {details}" if details else "Synchronisation terminee avec erreurs"
        return "Synchronisation terminee avec erreurs"
    return None


def _bytes_from_amount(amount: float, unit: str) -> int:
    normalized = unit.casefold()
    factors = {
        "b": 1,
        "kb": 1000,
        "kib": 1024,
        "mb": 1000**2,
        "mib": 1024**2,
        "gb": 1000**3,
        "gib": 1024**3,
        "tb": 1000**4,
        "tib": 1024**4,
    }
    return int(amount * factors.get(normalized, 1))


def _group_lock_warning() -> str:
    return (
        "Un groupe PBS est verrouille, probablement suite a une precedente execution interrompue. "
        "Verifiez qu'aucun job PBS n'est actif, puis utilisez le nettoyage des jobs temporaires PBO."
    )
