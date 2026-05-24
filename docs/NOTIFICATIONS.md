# Notifications ntfy

PBO can send production notifications to a self-hosted ntfy server. Notification delivery is best-effort: ntfy errors are logged and never stop backup, eject, sync, or update workflows.

## Environment

Configure the App VM API environment:

```env
NOTIFICATIONS_ENABLED=true
NTFY_BASE_URL=https://ntfy.sofianechaoui.fr
NTFY_TOPIC=replace-with-secret-topic
NTFY_USERNAME=pbo
NTFY_PASSWORD=replace-with-ntfy-password
NOTIFY_ON_BACKUP_SUCCESS=true
NOTIFY_ON_BACKUP_FAILURE=true
NOTIFY_ON_DISK_EJECT_READY=true
NOTIFY_ON_UPDATE_RESULT=true
NOTIFY_ON_AGENT_DEGRADED=true
NOTIFY_ON_LOW_COVERAGE=true
LOW_COVERAGE_THRESHOLD_PERCENT=100
```

`NTFY_TOPIC` should be treated as a secret. Use a long random topic name and do not publish it in documentation, screenshots, logs, or issue reports.

`NTFY_PASSWORD` is only used server-side for ntfy basic auth. The API status endpoint and UI never return or display it.

## ntfy Auth

The API posts to:

```text
{NTFY_BASE_URL}/{NTFY_TOPIC}
```

When `NTFY_USERNAME` or `NTFY_PASSWORD` is set, requests use HTTP basic authentication. The ntfy server should restrict publish access for the configured topic to this account.

## API

All notification settings endpoints are behind the normal admin JWT auth:

- `GET /api/v1/notifications/status`
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
