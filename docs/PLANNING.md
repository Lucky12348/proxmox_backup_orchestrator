# Scheduled External Backups

PBO planning schedules external PBS exports against one exact removable disk serial number. The scheduler runs in the API process and is controlled by:

```env
PLANNING_SCHEDULER_ENABLED=true
PLANNING_SCHEDULER_INTERVAL_SECONDS=60
DISK_DETECTION_NOTIFY_COOLDOWN_SECONDS=1800
```

All planning endpoints require the normal admin authentication.

## Events

A scheduled backup event defines:

- title and enabled state
- exact `disk_serial`
- PBS datastore
- recurrence: `once`, `daily`, `weekly`, or `monthly`
- timezone label
- window start and duration
- reminder lead time, default 60 minutes
- start mode: `auto_on_disk_detected` or `manual_confirmation`
- optional auto-eject after successful backup

The scheduler creates one run per due occurrence. Runs are idempotent: the same event and scheduled time are not created twice.

## Run States

Runs move through these states:

- `pending`
- `waiting_for_disk`
- `waiting_for_confirmation`
- `running`
- `success`
- `failure`
- `missed`
- `cancelled`

PBO will not start a scheduled backup outside its planned window unless an admin clicks `Run now`.

## Disk Matching

Scheduled backups match disks by exact serial only. Display names and models are shown for operators, but they are not used to start a backup.

When the agent reports a disk changing from absent to present, PBO checks active planning windows for that serial. If the disk is expected:

- automatic mode starts the external backup immediately if no other external backup is running
- manual mode sends a confirmation notification and waits for the admin to confirm in PBO

PBO does not start more than one external backup at the same time.

## Notifications

Planning notifications include:

- reminder before the window starts
- expected disk detected
- automatic backup started
- manual confirmation required
- missed window

External backup success and failure reuse the normal backup notifications and include the planned event context when startup fails.

## Auto-Eject

If `auto_eject_after_success=true`, the scheduler attempts the same safe eject workflow after the linked external backup succeeds. The existing disk-ready notification is sent by the eject workflow.

If auto-eject is disabled, PBO only reports backup success; the operator should eject manually from the Disks page.

## Troubleshooting

If a disk is detected but a backup does not start:

- confirm the event uses the exact serial from the Disks page
- confirm the event is enabled
- confirm the current time is inside the planned window
- check whether the run is waiting for manual confirmation
- check whether another external backup is already pending or running
- inspect API logs for `notification event=planned_disk_detected` and scheduler warnings

If reminders do not appear, verify `PLANNING_SCHEDULER_ENABLED=true` and that the env var is visible inside the API container.
