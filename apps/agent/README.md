# Agent

Minimal Python scaffold intended to run on a Proxmox host.

## Current scope

This phase does not implement hotplug watching yet. It provides:

- heartbeat reporting to the backend
- real disk report submission using Linux host inspection
- one-shot state sync combining heartbeat and real disk report
- target-directory preparation for an external PBS export flow
- a stubbed external export command boundary for future PBS-native execution
- optional mock disk report submission for development
- a simple CLI contract for future host-side integration

## Environment

- `AGENT_API_BASE_URL`
- `AGENT_HOSTNAME`
- `AGENT_VERSION`
- `AGENT_TIMEOUT_SECONDS`

## Run locally

1. Create a virtual environment.
2. Install the package with `pip install -e .`
3. Send a heartbeat with `python -m agent.main heartbeat`
4. Send a real disk report with `python -m agent.main report-disks`
5. Send both heartbeat and disk report with `python -m agent.main sync-state`
6. Optionally send a mock disk report with `python -m agent.main report-mock-disks`
7. Prepare an external datastore target with `python -m agent.main prepare-external-datastore --mount-path /mnt/backup --target-path /mnt/backup/pbs-datastore`
8. Exercise the export boundary with `python -m agent.main run-external-export --target-path /mnt/backup/pbs-datastore --datastore-name backup`

## Systemd deployment

Deployable systemd examples are in `deploy/systemd/`.

The examples assume:

- the agent project is copied to `/opt/proxmox-backup-orchestrator-agent`
- the virtual environment lives at `/opt/proxmox-backup-orchestrator-agent/.venv`
- runtime environment variables are stored in `/opt/proxmox-backup-orchestrator-agent/.env`

The service runs `python -m agent.main sync-state`.
The timer triggers it every 2 minutes.

## Real discovery heuristics

The real disk report uses `lsblk -J` and optional `udevadm info`.

Current filtering is intentionally pragmatic:

- only `TYPE=disk`
- exclude `loop`, `dm-*`, `zd*`, and `sr*`
- exclude disks backing the host system and obvious Proxmox storage members
- allow clearly external USB disks
- also allow standalone physical disks with a usable serial number

If a filesystem or mount point exists on a partition, the agent derives it from child partitions instead of requiring it on the parent disk node.
