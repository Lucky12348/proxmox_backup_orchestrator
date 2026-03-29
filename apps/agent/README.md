# Agent

Minimal Python scaffold intended to run on a Proxmox host.

## Current scope

This phase does not perform real USB detection yet. It provides:

- heartbeat reporting to the backend
- mock disk report submission
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
4. Send a mock disk report with `python -m agent.main report-disks`
