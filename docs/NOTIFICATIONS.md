# Notifications ntfy

PBO sends best-effort notifications through ntfy. Delivery errors are logged without secrets and never stop backup, eject, sync, planning, or update workflows.

## Environment

Configure the App VM API environment:

```env
NOTIFICATIONS_ENABLED=true
NTFY_BASE_URL=https://ntfy.YOURDOMAINE.com
NTFY_TOPIC=replace-with-secret-topic
NTFY_USERNAME=pbo
NTFY_PASSWORD=replace-with-ntfy-password
NOTIFY_ON_BACKUP_SUCCESS=true
NOTIFY_ON_BACKUP_FAILURE=true
NOTIFY_ON_DISK_EJECT_READY=true
NOTIFY_ON_UPDATE_RESULT=true
NOTIFY_ON_AGENT_DEGRADED=true
NOTIFY_ON_LOW_COVERAGE=true
NOTIFY_ON_DISK_NEW_DETECTED=true
NOTIFY_ON_DISK_KNOWN_DETECTED=true
NOTIFY_ON_PLANNED_DISK_DETECTED=true
NOTIFY_ON_PLANNED_BACKUP_REMINDER=true
NOTIFY_ON_PLANNED_BACKUP_STARTED=true
NOTIFY_ON_PLANNED_CONFIRMATION_REQUIRED=true
NOTIFY_ON_PLANNED_BACKUP_MISSED=true
LOW_COVERAGE_THRESHOLD_PERCENT=100
DISK_DETECTION_NOTIFY_COOLDOWN_SECONDS=1800
```

`NTFY_TOPIC` should be treated as a secret. Use a long random topic name and do not publish it in documentation, screenshots, logs, or issue reports.

`NTFY_PASSWORD` is only used server-side for ntfy basic auth. The API status endpoint and UI never return or display it.

Provider configuration stays environment-only:

- `NTFY_BASE_URL`
- `NTFY_TOPIC`
- `NTFY_USERNAME`
- `NTFY_PASSWORD`

The Settings UI can edit only non-sensitive preferences. Those preferences are stored in the database and override the event toggles, low coverage threshold, and disk detection cooldown from the environment. If no database preference exists, PBO uses the environment defaults. If `NOTIFICATIONS_ENABLED=false`, the UI cannot force notifications on.

## ntfy Auth

The API posts to:

```text
{NTFY_BASE_URL}/{NTFY_TOPIC}
```

When `NTFY_USERNAME` or `NTFY_PASSWORD` is set, requests use HTTP basic authentication. The ntfy server should restrict publish access for the configured topic to this account.

## API

All notification settings endpoints are behind the normal admin JWT auth:

- `GET /api/v1/notifications/status`
- `GET /api/v1/notifications/preferences`
- `PATCH /api/v1/notifications/preferences`
- `POST /api/v1/notifications/preferences/reset`
- `POST /api/v1/notifications/test`

The status endpoint returns whether notifications are enabled, whether ntfy is configured, the base URL, a masked topic, the username, event toggles, and the low coverage threshold. It never returns the password.

## Events

PBO sends notifications for these events when enabled:

- External backup success.
- External backup failure, including disk, failed step, and a short error.
- Dedicated external disk safe eject success.
- Maintenance update success or failure.
- Host agent degraded or disconnected status, rate-limited to avoid repeated alerts.
- Low PBS backup coverage after a PBS sync when coverage is below `LOW_COVERAGE_THRESHOLD_PERCENT`.
- New USB disk first seen by the agent.
- Known USB disk changing from absent to present, rate-limited by `DISK_DETECTION_NOTIFY_COOLDOWN_SECONDS`.
- Expected disk detected for an active planned backup window.
- Planned backup reminders, auto-starts, confirmation requests, and missed windows.

Disk detection uses the exact disk serial reported by the agent. PBO stores `presence_state` as `present` or `absent` and only notifies on transitions into `present`.

## Troubleshooting

If the Settings test works but real events do not fire, check that the API container has the notification and planning env vars, then inspect API logs for `notification event=<name> sent=true|false`.

If disk detection notifications repeat, verify the agent is not reporting changing serial numbers and that `DISK_DETECTION_NOTIFY_COOLDOWN_SECONDS` is present inside the API container.

If planned disk detection does not trigger a backup, confirm the scheduled event uses the exact serial number shown in the Disks page and that the current time is inside the event window.

If a phone receives notifications only on Wi-Fi and not 5G, verify the public ntfy URL is reachable externally and that DNS does not resolve to a LAN-only address outside the network.

## Host notification engine (Proxmox host, file-driven)

Separate from the app's own ntfy sender above. The Proxmox host runs its own
file-driven ntfy engine (installed outside this repo) for host-level events
(boot, UPS, network, disk space, logins, fail2ban). The **Notifications** page
of the web UI edits it through the **Proxmox host agent** (port `8090`,
`X-Agent-Token`). No new port is exposed, and the app VM never talks to ntfy
for these events.

Host files (owned by the host engine; the agent only uses them):

| Path | Used by the agent for |
| --- | --- |
| `/etc/ntfy-notif/templates.json` (`root:nut`, `0664`) | read / validated atomic write |
| `/etc/ntfy-notif/backups/templates-<UTC timestamp>.json` | copy of the previous version on every save (10 most recent kept) |
| `/usr/local/bin/ntfy-send <code> [key=value ...]` | "Test" button (argument list, never a shell, 30 s timeout) |
| `/var/log/ntfy-notif/history.jsonl` | History tab (read backwards from the end of the file) |
| `/var/spool/ntfy-queue/*.json` | queue badge (count + age of the oldest message, payload never returned) |
| `/etc/ntfy-notif/ntfy.conf` | **never read**: it holds the ntfy token. No code path opens it. |

Paths can be overridden in the agent `.env` for non-standard installs:
`NTFY_NOTIF_TEMPLATES_PATH`, `NTFY_NOTIF_BACKUPS_DIR`,
`NTFY_NOTIF_HISTORY_PATH`, `NTFY_NOTIF_QUEUE_DIR`, `NTFY_NOTIF_SEND_COMMAND`.

### Template format and validation

```json
{
  "defaults": {"topic": "pve-alerts", "click": "https://pve.lan:8006", "icon": "", "late_after_sec": 300},
  "events": {
    "ups.onbatt": {"enabled": true, "priority": 4, "emoji": "battery",
                   "title": "UPS on battery", "message": "Charge {charge}% - {runtime}s left"}
  }
}
```

The agent (`apps/agent/src/agent/ntfy_notif.py`) is the source of truth and
rejects the whole save if any rule fails. The API and the web page check the
same rules first so mistakes show up before anything reaches the host.

- Unknown keys are rejected at every level. `defaults.topic` and the event keys
  `enabled`, `priority`, `emoji`, `title`, `message` are required. `topic`,
  `click`, `icon` (event) and `click`, `icon`, `late_after_sec` (defaults) are optional.
- Event code `^[a-z0-9_]+(\.[a-z0-9_]+)*$` (max 64). Priority: integer 1–5
  (1 Min · 2 Low · 3 Default · 4 High · 5 Urgent). Emoji: ntfy shortcode
  `^[a-z0-9_+-]{1,40}$`. Topic `^[A-Za-z0-9_-]{1,64}$`.
- Title: not empty, max 60 characters, single line. Message: max 200 characters.
- `click` / `icon`: empty or an `http(s)` URL. `late_after_sec`: 0–86400.
- Variables are written `{name}` in title/message.

Writes are atomic: a temporary file in `/etc/ntfy-notif/`, `fsync`, `chown
root:nut`, `chmod 0664`, then `os.replace`. A failed validation leaves the
file and the backups untouched.

**Privileges.** The agent HTTP service must run as root (`User=root`, as in
`apps/agent/deploy/systemd/`). If it runs as another user, saving is refused
with HTTP 403 and an explicit message. It is not worked around. A non-root
agent would need write access to `/etc/ntfy-notif/` and
`/etc/ntfy-notif/backups/`, plus `CAP_CHOWN` to keep `root:nut`. Reading the
history and queue only needs read access to those paths.

### Built-in events and variables

These codes are produced by the host scripts. They can be edited or disabled
but not deleted from the UI. Custom events can be added and deleted.

| Code | Variables |
| --- | --- |
| `test` | `texte` |
| `system.boot`, `system.boot_unclean` | `kernel` |
| `system.shutdown` | none |
| `ups.onbatt` | `charge`, `runtime` |
| `ups.online`, `ups.lowbatt`, `ups.shutdown` | `charge` |
| `ups.fsd`, `ups.commbad`, `ups.commok`, `ups.replbatt` | none |
| `net.restored` | `debut`, `fin`, `duree` |
| `disk.space` | `details` |
| `auth.web_ok` | `user` |
| `auth.web_fail`, `auth.ssh_ok`, `auth.ssh_fail` | `user`, `ip` |
| `f2b.ban` | `ip`, `jail` |

The UI groups events by code prefix: system, ups, net, disk, auth, f2b, test,
and "other" for anything else. A disabled event is not sent: `ntfy-send` logs it
as `muted` in the history.

### HTTP surface

Proxmox host agent (`X-Agent-Token` required):

| Method | Path | Notes |
| --- | --- | --- |
| `GET` | `/notifications/templates` | `{templates, path, modified_at}`; 404 if the file is missing |
| `PUT` | `/notifications/templates` | body = whole document; 422 `{errors: [...]}` on validation failure, 403 if the agent is not root |
| `POST` | `/notifications/test` | `{"event": code, "vars": {key: value}}`; keys `^[A-Za-z0-9_]+$`, values ≤ 100 chars, no line break; returns `return_code` |
| `GET` | `/notifications/history?limit=200&event=&status=` | most recent first, `limit` 1–1000, `status` ∈ `queued`/`sent`/`muted` |
| `GET` | `/notifications/queue` | `{count, oldest_ts, oldest_age_seconds}` |

The agent advertises the `ntfy-notifications` capability in `/version`.

App API (logged-in operator), relaying to the host agent:
`GET|PUT /api/v1/notifications/host/templates`,
`POST /api/v1/notifications/host/test`,
`GET /api/v1/notifications/host/history`,
`GET /api/v1/notifications/host/queue`.
Every save and every test, successful or not, adds a line to the
**Operations journal** (`GET /api/v1/activity-events`, shown on the Activity
page). The line lists which events were added, changed or removed. This is a new
`activity_events` table, created automatically at API startup. It is kept apart
from `backup_runs` so the dashboard's "latest backup" status is not affected.

### Troubleshooting

- *"The Proxmox host agent does not know the /notifications endpoints"*: the
  host agent still runs older code. Update it (see `docs/MAINTENANCE.md`) and
  check that `AGENT_HTTP_SERVICE_NAME` is set so it restarts.
- *403 "not running as root"* on save: see **Privileges** above.
- *404 templates file not found*: the host engine is not installed, or
  `NTFY_NOTIF_TEMPLATES_PATH` points elsewhere.
- The "Test" button sends the version **saved on the host**. Save first, then test.
