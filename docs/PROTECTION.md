# Protection Management

PBO can centralize two routine protection tasks:

- mark assets as ignored for coverage calculations
- edit the selected VMID list of an existing Proxmox Datacenter backup job

PBO does not create or delete Proxmox backup jobs yet. Schedule, storage, retention, notification mode, and pruning remain managed in Proxmox.

## Ignored Assets

Ignored assets remain visible in the Assets page with an `Ignore` badge. They are muted visually, but last backup and runtime state stay visible.

Ignored assets are excluded from backup coverage:

```text
coverage = protected non-ignored assets / total non-ignored assets
```

Ignored assets do not count as unprotected, and low-coverage ntfy notifications use the same non-ignored total.

Use this for infrastructure VMs or containers that should be visible in inventory but should not affect backup coverage targets.

## Proxmox Backup Job Selection

The Assets page shows existing Proxmox backup jobs from Datacenter -> Backup.

Supported for editing:

- existing jobs only
- selection mode: include selected VMs
- selected VMID list only

Read-only in PBO:

- schedule
- storage
- retention
- node scope
- notification mode
- unsupported selection modes such as all VMs, pools, or exclude lists

When saving a selection change, PBO fetches the current job first, preserves existing fields, updates only `vmid`, and sends the update back to Proxmox. PBO logs before and after VMID lists without API tokens or secrets.

After a successful update, refresh Proxmox inventory and PBS inventory if protection state does not update immediately.

## Recommended Workflow

1. Open Assets.
2. Mark assets that should not affect coverage as ignored.
3. In Jobs de sauvegarde Proxmox, choose the existing PBS backup job.
4. Click Gerer la selection.
5. Add or remove VMIDs.
6. Save and confirm.
7. Verify in Proxmox Datacenter -> Backup that the selected VMIDs match.
8. Run Proxmox/PBS sync in PBO if needed.

## Troubleshooting

If a job is read-only in PBO, check its Proxmox selection mode. PBO currently supports only jobs that explicitly include selected VMIDs.

If a VM appears ignored but still shows as protected or unprotected, that is expected: ignored assets remain visible with their raw backup state. They are excluded only from coverage totals and low-coverage alerts.

If Proxmox rejects the selection update, review the error from the API response and verify the API token can modify Datacenter backup jobs.
