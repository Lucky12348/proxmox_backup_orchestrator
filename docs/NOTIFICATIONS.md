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
