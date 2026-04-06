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

## Host Agent Execution

External backup execution calls the host agent with an explicit Python interpreter and working directory.

- `AGENT_EXEC_PYTHON_PATH` defaults to `/opt/proxmox-backup-orchestrator-agent/.venv/bin/python`
- `AGENT_EXEC_WORKDIR` defaults to `/opt/proxmox-backup-orchestrator-agent`
- `HOST_AGENT_TIMEOUT_SECONDS` controls command timeout
