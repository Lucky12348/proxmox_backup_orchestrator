"""Management helpers for the host-local, file-driven ntfy notification engine.

The Proxmox host runs its own ntfy notification engine (not part of this repo):

- ``/etc/ntfy-notif/templates.json``      event templates (root:nut, 0664)
- ``/usr/local/bin/ntfy-send``            renders a template, queues and sends it
- ``/var/log/ntfy-notif/history.jsonl``   one JSON line per step (queued/sent/muted)
- ``/var/spool/ntfy-queue/*.json``        messages waiting for ntfy to be reachable
- ``/etc/ntfy-notif/ntfy.conf``           ntfy token -- NEVER read or exposed here

This module only reads/writes ``templates.json``, reads the history/queue and
invokes ``ntfy-send``. It deliberately has no code path that touches
``ntfy.conf``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse


EVENT_CODE_PATTERN = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")
EMOJI_PATTERN = re.compile(r"^[a-z0-9_+-]{1,40}$")
TOPIC_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
VAR_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")

EVENT_CODE_MAX_LENGTH = 64
TITLE_MAX_LENGTH = 60
MESSAGE_MAX_LENGTH = 200
URL_MAX_LENGTH = 500
LATE_AFTER_SEC_MAX = 86400
MAX_EVENTS = 200
TEST_VAR_VALUE_MAX_LENGTH = 100
TEST_MAX_VARS = 20
TEST_TIMEOUT_SECONDS = 30
HISTORY_DEFAULT_LIMIT = 200
HISTORY_MAX_LIMIT = 1000
HISTORY_STATUSES = {"queued", "sent", "muted"}
BACKUPS_KEEP = 10
TEMPLATES_OWNER_USER = "root"
TEMPLATES_OWNER_GROUP = "nut"
TEMPLATES_MODE = 0o664
OUTPUT_MAX_LENGTH = 4000

DEFAULTS_REQUIRED_KEYS = {"topic"}
DEFAULTS_ALLOWED_KEYS = {"topic", "click", "icon", "late_after_sec"}
EVENT_REQUIRED_KEYS = {"enabled", "priority", "emoji", "title", "message"}
EVENT_ALLOWED_KEYS = EVENT_REQUIRED_KEYS | {"topic", "click", "icon"}
TOP_LEVEL_KEYS = {"defaults", "events"}

# ntfy access tokens look like `tk_...`; also scrub Authorization/Bearer
# fragments in case ntfy-send ever echoes a failed curl command line.
_SECRET_PATTERNS = (
    re.compile(r"tk_[A-Za-z0-9]{8,}"),
    re.compile(r"(?i)(authorization:\s*)(bearer|basic)\s+\S+"),
    re.compile(r"(?i)\bbearer\s+\S+"),
)

_write_lock = threading.Lock()


class NtfyNotifValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("Invalid notification templates: " + "; ".join(errors))
        self.errors = errors


class NtfyNotifNotFoundError(FileNotFoundError):
    pass


class NtfyNotifPermissionError(PermissionError):
    pass


@dataclass(frozen=True)
class NtfyNotifSettings:
    templates_path: Path = Path(os.getenv("NTFY_NOTIF_TEMPLATES_PATH", "/etc/ntfy-notif/templates.json"))
    backups_dir: Path = Path(os.getenv("NTFY_NOTIF_BACKUPS_DIR", "/etc/ntfy-notif/backups"))
    history_path: Path = Path(os.getenv("NTFY_NOTIF_HISTORY_PATH", "/var/log/ntfy-notif/history.jsonl"))
    queue_dir: Path = Path(os.getenv("NTFY_NOTIF_QUEUE_DIR", "/var/spool/ntfy-queue"))
    send_command: str = os.getenv("NTFY_NOTIF_SEND_COMMAND", "/usr/local/bin/ntfy-send")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_templates(data: Any) -> dict[str, Any]:
    """Strictly validate a templates.json document.

    Returns the document unchanged (same key order) when valid, otherwise
    raises NtfyNotifValidationError listing every problem found.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        raise NtfyNotifValidationError(["root: must be a JSON object"])

    for key in sorted(set(data) - TOP_LEVEL_KEYS):
        errors.append(f"root: unknown key `{key}`")
    for key in sorted(TOP_LEVEL_KEYS - set(data)):
        errors.append(f"root: missing key `{key}`")

    defaults = data.get("defaults")
    if "defaults" in data:
        if not isinstance(defaults, dict):
            errors.append("defaults: must be an object")
        else:
            _validate_defaults(defaults, errors)

    events = data.get("events")
    if "events" in data:
        if not isinstance(events, dict):
            errors.append("events: must be an object")
        else:
            if len(events) > MAX_EVENTS:
                errors.append(f"events: at most {MAX_EVENTS} events are allowed")
            for code, event in events.items():
                _validate_event(code, event, errors)

    if errors:
        raise NtfyNotifValidationError(errors)
    return data


def _validate_defaults(defaults: dict[str, Any], errors: list[str]) -> None:
    for key in sorted(set(defaults) - DEFAULTS_ALLOWED_KEYS):
        errors.append(f"defaults: unknown key `{key}`")
    for key in sorted(DEFAULTS_REQUIRED_KEYS - set(defaults)):
        errors.append(f"defaults: missing key `{key}`")

    if "topic" in defaults:
        _check_topic("defaults.topic", defaults["topic"], errors)
    for key in ("click", "icon"):
        if key in defaults:
            _check_optional_url(f"defaults.{key}", defaults[key], errors)
    if "late_after_sec" in defaults:
        value = defaults["late_after_sec"]
        if not _is_int(value) or not 0 <= value <= LATE_AFTER_SEC_MAX:
            errors.append(f"defaults.late_after_sec: must be an integer between 0 and {LATE_AFTER_SEC_MAX}")


def _validate_event(code: Any, event: Any, errors: list[str]) -> None:
    if not isinstance(code, str) or len(code) > EVENT_CODE_MAX_LENGTH or not EVENT_CODE_PATTERN.match(code):
        errors.append(
            f"events.{code}: invalid event code (expected ^[a-z0-9_]+(\\.[a-z0-9_]+)*$, max {EVENT_CODE_MAX_LENGTH} chars)"
        )
        return
    prefix = f"events.{code}"
    if not isinstance(event, dict):
        errors.append(f"{prefix}: must be an object")
        return

    for key in sorted(set(event) - EVENT_ALLOWED_KEYS):
        errors.append(f"{prefix}: unknown key `{key}`")
    for key in sorted(EVENT_REQUIRED_KEYS - set(event)):
        errors.append(f"{prefix}: missing key `{key}`")

    if "enabled" in event and not isinstance(event["enabled"], bool):
        errors.append(f"{prefix}.enabled: must be a boolean")
    if "priority" in event:
        value = event["priority"]
        if not _is_int(value) or not 1 <= value <= 5:
            errors.append(f"{prefix}.priority: must be an integer between 1 and 5")
    if "emoji" in event:
        value = event["emoji"]
        if not isinstance(value, str) or not EMOJI_PATTERN.match(value):
            errors.append(f"{prefix}.emoji: must match ^[a-z0-9_+-]{{1,40}}$ (ntfy shortcode)")
    if "title" in event:
        value = event["title"]
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{prefix}.title: must be a non-empty string")
        elif len(value) > TITLE_MAX_LENGTH:
            errors.append(f"{prefix}.title: at most {TITLE_MAX_LENGTH} characters ({len(value)} given)")
        elif _has_control_chars(value, allow_newline=False):
            errors.append(f"{prefix}.title: must not contain line breaks or control characters")
    if "message" in event:
        value = event["message"]
        if not isinstance(value, str):
            errors.append(f"{prefix}.message: must be a string")
        elif len(value) > MESSAGE_MAX_LENGTH:
            errors.append(f"{prefix}.message: at most {MESSAGE_MAX_LENGTH} characters ({len(value)} given)")
        elif _has_control_chars(value, allow_newline=True):
            errors.append(f"{prefix}.message: must not contain control characters")
    if "topic" in event:
        _check_topic(f"{prefix}.topic", event["topic"], errors)
    for key in ("click", "icon"):
        if key in event:
            _check_optional_url(f"{prefix}.{key}", event[key], errors)


def _check_topic(field: str, value: Any, errors: list[str]) -> None:
    if not isinstance(value, str) or not TOPIC_PATTERN.match(value):
        errors.append(f"{field}: must match ^[A-Za-z0-9_-]{{1,64}}$")


def _check_optional_url(field: str, value: Any, errors: list[str]) -> None:
    if not isinstance(value, str):
        errors.append(f"{field}: must be a string (empty or http(s) URL)")
        return
    if value == "":
        return
    if not is_http_url(value):
        errors.append(f"{field}: must be empty or an http(s) URL (max {URL_MAX_LENGTH} chars)")


def is_http_url(value: str) -> bool:
    if len(value) > URL_MAX_LENGTH or any(ch.isspace() for ch in value) or _has_control_chars(value, allow_newline=False):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _has_control_chars(value: str, *, allow_newline: bool) -> bool:
    for ch in value:
        if ch == "\n" and allow_newline:
            continue
        if ord(ch) < 32 or ord(ch) == 127:
            return True
    return False


# ---------------------------------------------------------------------------
# Templates read / write
# ---------------------------------------------------------------------------


def read_templates_result(settings: NtfyNotifSettings | None = None) -> dict[str, Any]:
    settings = settings or NtfyNotifSettings()
    path = settings.templates_path
    if not path.exists():
        raise NtfyNotifNotFoundError(f"Notification templates file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        templates = json.load(handle)
    stat_result = path.stat()
    return {
        "ok": True,
        "message": "Notification templates loaded.",
        "path": str(path),
        "modified_at": datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc).isoformat(),
        "templates": templates,
    }


def write_templates_result(data: Any, settings: NtfyNotifSettings | None = None) -> dict[str, Any]:
    settings = settings or NtfyNotifSettings()
    validated = validate_templates(data)
    ensure_write_privileges(settings)

    path = settings.templates_path
    serialized = json.dumps(validated, ensure_ascii=False, indent=2) + "\n"

    with _write_lock:
        backup_path = _backup_current_templates(path, settings.backups_dir)
        uid, gid = _resolve_templates_owner(path)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            apply_owner_and_mode(tmp_path, uid, gid, TEMPLATES_MODE)
            os.replace(tmp_path, path)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
        _fsync_directory(path.parent)

    return {
        "ok": True,
        "message": "Notification templates saved.",
        "path": str(path),
        "backup_path": str(backup_path) if backup_path else None,
        "event_count": len(validated.get("events", {})),
        "templates": validated,
    }


def ensure_write_privileges(settings: NtfyNotifSettings) -> None:
    """Refuse to write unless the agent can keep root:nut / 0664 on templates.json.

    The agent is expected to run as root (see the agent systemd units). We do
    not try to work around a non-root agent: the caller gets an explicit list
    of the rights it would need instead.
    """
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None or geteuid() == 0:
        return
    raise NtfyNotifPermissionError(
        "The host agent is not running as root (euid="
        f"{geteuid()}). Editing {settings.templates_path} requires: write access to "
        f"{settings.templates_path.parent} (to create the temporary file and os.replace it), "
        f"write access to {settings.backups_dir}, and the right to chown the file to "
        f"{TEMPLATES_OWNER_USER}:{TEMPLATES_OWNER_GROUP} (CAP_CHOWN). Run the agent HTTP service "
        "as root (User=root, as shipped in apps/agent/deploy/systemd) instead of loosening "
        "these permissions."
    )


def apply_owner_and_mode(path: Path, uid: int | None, gid: int | None, mode: int) -> None:
    if uid is not None and gid is not None and hasattr(os, "chown"):
        os.chown(path, uid, gid)
    os.chmod(path, mode)


def _resolve_templates_owner(path: Path) -> tuple[int | None, int | None]:
    """Target owner is root:nut; fall back to the current file's ids if `nut` is unknown."""
    try:
        import grp
        import pwd
    except ImportError:  # non-POSIX (dev machines / tests)
        return None, None

    uid: int | None
    gid: int | None
    try:
        uid = pwd.getpwnam(TEMPLATES_OWNER_USER).pw_uid
    except KeyError:
        uid = None
    try:
        gid = grp.getgrnam(TEMPLATES_OWNER_GROUP).gr_gid
    except KeyError:
        gid = None

    if (uid is None or gid is None) and path.exists():
        stat_result = path.stat()
        uid = stat_result.st_uid if uid is None else uid
        gid = stat_result.st_gid if gid is None else gid
    return uid, gid


def _backup_current_templates(path: Path, backups_dir: Path) -> Path | None:
    if not path.exists():
        return None
    backups_dir.mkdir(mode=0o750, parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backups_dir / f"templates-{stamp}.json"
    shutil.copy2(path, backup_path)
    prune_backups(backups_dir, BACKUPS_KEEP)
    return backup_path


def prune_backups(backups_dir: Path, keep: int) -> list[Path]:
    # Timestamped names sort chronologically, so lexical order == age order.
    backups = sorted(backups_dir.glob("templates-*.json"))
    removed: list[Path] = []
    for old in backups[:-keep] if keep > 0 else backups:
        old.unlink(missing_ok=True)
        removed.append(old)
    return removed


def _fsync_directory(directory: Path) -> None:
    if not hasattr(os, "O_DIRECTORY"):
        return
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# Test send
# ---------------------------------------------------------------------------


def validate_test_request(event: Any, variables: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(event, str) or len(event) > EVENT_CODE_MAX_LENGTH or not EVENT_CODE_PATTERN.match(event):
        errors.append("event: invalid event code")
    if not isinstance(variables, dict):
        errors.append("vars: must be an object")
        return errors
    if len(variables) > TEST_MAX_VARS:
        errors.append(f"vars: at most {TEST_MAX_VARS} variables are allowed")
    for key, value in variables.items():
        if not isinstance(key, str) or not VAR_KEY_PATTERN.match(key):
            errors.append(f"vars.{key}: invalid key (expected ^[A-Za-z0-9_]+$)")
            continue
        if not isinstance(value, str):
            errors.append(f"vars.{key}: must be a string")
        elif len(value) > TEST_VAR_VALUE_MAX_LENGTH:
            errors.append(f"vars.{key}: at most {TEST_VAR_VALUE_MAX_LENGTH} characters")
        elif "\n" in value or "\r" in value or _has_control_chars(value, allow_newline=False):
            errors.append(f"vars.{key}: must not contain line breaks or control characters")
    return errors


def build_test_command(send_command: str, event: str, variables: dict[str, str]) -> list[str]:
    return [send_command, event, *[f"{key}={value}" for key, value in variables.items()]]


def send_test_result(event: Any, variables: Any, settings: NtfyNotifSettings | None = None) -> dict[str, Any]:
    settings = settings or NtfyNotifSettings()
    variables = {} if variables is None else variables
    errors = validate_test_request(event, variables)
    if errors:
        raise NtfyNotifValidationError(errors)

    command = build_test_command(settings.send_command, event, variables)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise NtfyNotifNotFoundError(f"ntfy-send not found at {settings.send_command}") from exc
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "message": f"ntfy-send timed out after {TEST_TIMEOUT_SECONDS} seconds.",
            "event": event,
            "return_code": None,
            "stdout_log": None,
            "stderr_log": None,
            "command_summary": f"ntfy-send {event}",
        }

    ok = completed.returncode == 0
    return {
        "ok": ok,
        "message": "ntfy-send completed." if ok else f"ntfy-send exited with code {completed.returncode}.",
        "event": event,
        "return_code": completed.returncode,
        "stdout_log": _sanitize_output(completed.stdout),
        "stderr_log": _sanitize_output(completed.stderr),
        # Only the event code: var values are user-provided and already echoed back to the caller.
        "command_summary": f"ntfy-send {event}",
    }


def _sanitize_output(value: str | None) -> str | None:
    if not value:
        return None
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub(lambda match: (match.group(1) if match.lastindex else "") + "[redacted]", value)
    if len(value) > OUTPUT_MAX_LENGTH:
        value = value[-OUTPUT_MAX_LENGTH:]
    return value


# ---------------------------------------------------------------------------
# History / queue
# ---------------------------------------------------------------------------


def iter_lines_reverse(path: Path, chunk_size: int = 64 * 1024) -> Iterator[str]:
    """Yield the lines of a file from last to first, reading fixed-size chunks from the end."""
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        remainder = b""
        while position > 0:
            read_size = min(chunk_size, position)
            position -= read_size
            handle.seek(position)
            chunk = handle.read(read_size) + remainder
            lines = chunk.split(b"\n")
            # The first piece may be a partial line: keep it for the next chunk.
            remainder = lines.pop(0)
            for line in reversed(lines):
                if line.strip():
                    yield line.rstrip(b"\r").decode("utf-8", errors="replace")
        if remainder.strip():
            yield remainder.rstrip(b"\r").decode("utf-8", errors="replace")


def read_history_result(
    limit: int = HISTORY_DEFAULT_LIMIT,
    event: str | None = None,
    status: str | None = None,
    settings: NtfyNotifSettings | None = None,
) -> dict[str, Any]:
    settings = settings or NtfyNotifSettings()
    limit = max(1, min(int(limit), HISTORY_MAX_LIMIT))
    event = event or None
    status = status or None
    if event is not None and not EVENT_CODE_PATTERN.match(event):
        raise NtfyNotifValidationError(["event: invalid event code"])
    if status is not None and status not in HISTORY_STATUSES:
        raise NtfyNotifValidationError([f"status: must be one of {', '.join(sorted(HISTORY_STATUSES))}"])

    path = settings.history_path
    entries: list[dict[str, Any]] = []
    skipped = 0
    if path.exists():
        for line in iter_lines_reverse(path):
            try:
                raw = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            if not isinstance(raw, dict):
                skipped += 1
                continue
            entry = _history_entry(raw)
            if event is not None and entry["event"] != event:
                continue
            if status is not None and entry["status"] != status:
                continue
            entries.append(entry)
            if len(entries) >= limit:
                break

    return {
        "ok": True,
        "message": "Notification history loaded." if path.exists() else f"History file not found: {path}",
        "path": str(path),
        "entries": entries,
        "skipped_lines": skipped,
    }


def _history_entry(raw: dict[str, Any]) -> dict[str, Any]:
    ts = raw.get("ts")
    return {
        "ts": ts if isinstance(ts, (int, float)) and not isinstance(ts, bool) else None,
        "event": str(raw.get("event") or ""),
        "status": str(raw.get("status") or ""),
        "title": raw.get("title") if isinstance(raw.get("title"), str) else None,
        "message": raw.get("message") if isinstance(raw.get("message"), str) else None,
    }


def read_queue_result(settings: NtfyNotifSettings | None = None, now: float | None = None) -> dict[str, Any]:
    settings = settings or NtfyNotifSettings()
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    queue_dir = settings.queue_dir
    if not queue_dir.is_dir():
        return {
            "ok": True,
            "message": f"Queue directory not found: {queue_dir}",
            "count": 0,
            "oldest_ts": None,
            "oldest_age_seconds": None,
        }

    count = 0
    oldest: float | None = None
    for item in queue_dir.glob("*.json"):
        if not item.is_file():
            continue
        count += 1
        ts = _queued_message_ts(item)
        if ts is not None and (oldest is None or ts < oldest):
            oldest = ts

    return {
        "ok": True,
        "message": "Notification queue inspected.",
        "count": count,
        "oldest_ts": oldest,
        "oldest_age_seconds": max(0, int(now - oldest)) if oldest is not None else None,
    }


def _queued_message_ts(path: Path) -> float | None:
    # Only the `ts` field is used; the queued ntfy payload itself is never returned.
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        ts = payload.get("ts") if isinstance(payload, dict) else None
        if isinstance(ts, (int, float)) and not isinstance(ts, bool):
            return float(ts)
    except (OSError, ValueError):
        pass
    try:
        return path.stat().st_mtime
    except OSError:
        return None
