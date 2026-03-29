# Agent

Minimal Python scaffold intended to run on a Proxmox host.

## Current scope

This phase does not implement hotplug watching yet. It provides:

- heartbeat reporting to the backend
- real disk report submission using Linux host inspection
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
5. Optionally send a mock disk report with `python -m agent.main report-mock-disks`

## Real discovery heuristics

The real disk report uses `lsblk -J` and optional `udevadm info`.

Current filtering is intentionally pragmatic:

- only `TYPE=disk`
- exclude `loop`, `dm-*`, `zd*`, and `sr*`
- require removable/external heuristics such as `TRAN=usb`, `RM=1`, `HOTPLUG=1`, or USB-related udev properties

If a filesystem or mount point exists on a partition, the agent derives it from child partitions instead of requiring it on the parent disk node.
