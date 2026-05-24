# Operations

Use this runbook for routine external backups and safe disk handling.

For asset ignore rules and existing Proxmox backup job selection management, see [Protection Management](PROTECTION.md).

## Login

Open the Web UI:

```text
http://<app-vm-ip>:5173
```

Log in with:

- username: `AUTH_USERNAME`
- password: the password used when generating `AUTH_PASSWORD_HASH`

If login fails after a fresh deploy, check the `AUTH_PASSWORD_HASH` troubleshooting section below before resetting anything.

## Run an External Backup

1. Plug the dedicated USB disk into the Proxmox host.
2. Open the Web UI.
3. Go to the disk or external backup workflow.
4. Select the detected external USB disk.
5. Confirm dedicated datastore preparation.
6. Start the external backup run.
7. Watch activity until the run completes.

The workflow does three privileged operations:

- Proxmox host agent passes the USB disk to the PBS VM.
- PBS agent prepares or reuses the external datastore.
- PBS sync copies snapshots from `PBS_DATASTORE` to the external dedicated datastore.

## Dedicated Datastore Reuse

Dedicated mode is designed for one external disk that belongs to this backup process.

On first preparation, the PBS agent may format the disk and create a PBS datastore on it. This is destructive for existing disk contents.

On later runs, the PBS agent should detect and reuse the existing filesystem and datastore. Reuse means the disk can be plugged in again, mounted in PBS, and synced without recreating the datastore.

Do not mix this disk with unrelated data. Treat it as a removable PBS datastore.

## Safe Eject

Use the UI safe eject action before unplugging the disk.

Safe eject performs:

1. PBS datastore unmount inside the PBS VM.
2. USB passthrough removal from the PBS VM on the Proxmox host.
3. UI confirmation that the disk can be physically unplugged.

Only unplug the disk after the UI reports that safe eject completed.

## Replug and Rerun Backup

For the next backup cycle:

1. Plug the same USB disk into the Proxmox host.
2. Wait for it to appear in the UI.
3. Start the external backup workflow.
4. Confirm that the UI reports reuse of the dedicated datastore, not first-time formatting.
5. Let the PBS sync finish.
6. Use safe eject before removal.

## Verify the Disk Can Be Removed

After safe eject:

On PBS:

```bash
findmnt | grep /mnt/pbo || true
proxmox-backup-manager datastore list
```

The external mount path should not appear in `findmnt`.

On Proxmox:

```bash
qm config <pbs-vm-id> | grep '^usb' || true
```

The USB passthrough entry used by the external disk should be absent.

## Cleanup Activity

Use activity cleanup from the UI when old preparation, backup, or handoff records are no longer useful. Cleanup removes application activity records; it does not delete PBS backup snapshots from the main datastore or the external datastore.

Keep recent failed activity until the cause is understood. Agent logs are often needed for root-cause analysis:

```bash
journalctl -u proxmox-backup-orchestrator-agent-http.service -n 200 --no-pager
journalctl -u proxmox-backup-orchestrator-pbs-agent-http.service -n 200 --no-pager
```

## Troubleshooting

**Login is incorrect due to malformed `AUTH_PASSWORD_HASH`**

In Docker Compose `.env` files, bcrypt `$` characters must be escaped as `$$`. A valid Compose value looks like:

```env
AUTH_PASSWORD_HASH=$$2b$$12$$...
```

Regenerate with:

```bash
python scripts/generate_password_hash.py
```

Paste the complete printed line into `.env`, then restart the API:

```bash
docker compose -f infra/docker/docker-compose.yml up -d api
```

**`code_secret` still works**

This is not expected in the hardened deployment. Remove `code_secret` from old `.env` files, service overrides, shell profiles, browser bookmarks, and reverse proxy snippets. Restart the app and agents.

**Agent health returns 401**

The app token and the agent token do not match. Check:

- `HOST_AGENT_TOKEN` equals Proxmox agent `AGENT_SERVER_TOKEN`
- `PBS_AGENT_TOKEN` equals PBS agent `AGENT_SERVER_TOKEN`
- health checks include `X-Agent-Token`

Example:

```bash
curl -H "X-Agent-Token: <token>" http://<agent-host>:8090/health
```

**PBS disk visible but not mounted**

Check that the USB device is attached to the PBS VM and inspect PBS agent logs:

```bash
lsblk -f
journalctl -u proxmox-backup-orchestrator-pbs-agent-http.service -n 200 --no-pager
```

If this is the first run for the disk, destructive preparation may still be required. If this is a reused disk, confirm the expected PBS datastore path exists on the disk.

**USB passthrough still attached**

Run safe eject again. If it still remains, inspect the Proxmox VM config:

```bash
qm config <pbs-vm-id> | grep '^usb'
```

Do not unplug until the PBS datastore is unmounted. Manual detach is a last resort:

```bash
qm set <pbs-vm-id> -delete usbX
```

Replace `usbX` with the slot shown by `qm config`.

**External datastore reuse vs first format**

First-time dedicated preparation can format the disk. Reuse should not format. If the UI asks for destructive confirmation for a disk that should already be prepared, stop and verify you selected the expected physical disk.
