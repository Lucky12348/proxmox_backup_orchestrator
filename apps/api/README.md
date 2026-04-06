# API

FastAPI backend for orchestration, state tracking, and integrations.

## Run locally

1. Create a virtual environment.
2. Install the package with `pip install -e .`
3. Start the server with `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

## Current scope

- health endpoint
- environment-based configuration
- minimal package layout for future services, models, and schemas

## Agent Execution

Disk preparation calls the Proxmox host agent over HTTP.
PBS-native export execution calls a separate PBS-side agent over HTTP.

- `HOST_AGENT_BASE_URL` points to the host agent API, for example `http://proxmox-host:8081`
- `HOST_AGENT_TOKEN` is sent as the shared `X-Agent-Token` header
- `HOST_AGENT_TIMEOUT_SECONDS` controls request timeout
- `PBS_AGENT_BASE_URL` points to the PBS execution agent API, for example `http://pbs-host:8081`
- `PBS_AGENT_TOKEN` is sent as the shared `X-Agent-Token` header
- `PBS_AGENT_TIMEOUT_SECONDS` controls request timeout
