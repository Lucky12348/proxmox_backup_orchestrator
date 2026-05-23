# API

FastAPI backend for orchestration, state tracking, and integrations.

## Run locally

1. Create a virtual environment.
2. Install the package with `pip install -e .`
3. Start the server with `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

## Authentication

When `AUTH_ENABLED=true`, configure a single admin user:

```env
AUTH_ENABLED=true
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=$$2b$$12$$replace-with-generated-bcrypt-hash
AUTH_SECRET_KEY=replace-with-random-secret
AUTH_TOKEN_EXPIRE_MINUTES=180
```

Generate the hash from the repository root:

```powershell
py scripts/generate_password_hash.py
```

The script prints a Docker Compose-safe `AUTH_PASSWORD_HASH=<hash>` line. In a docker-compose `.env` file, bcrypt hashes must escape every `$` as `$$`; otherwise Compose interpolates the value and the API may receive a truncated hash such as `$2b$12`.

Bcrypt passwords are limited to 72 bytes after UTF-8 encoding. The API pins `bcrypt<5` because `passlib==1.7.4` is not compatible with bcrypt 5.x.

To debug hash verification inside the API environment:

```powershell
py -c "from passlib.hash import bcrypt; print(bcrypt.verify('your-password', '$2b$12$paste_the_runtime_hash_here'))"
```

## Current scope

- health endpoint
- environment-based configuration
- minimal package layout for future services, models, and schemas

## Agent Execution

Disk preparation calls the Proxmox host agent over HTTP.
PBS-native export execution calls a separate PBS-side agent over HTTP.
For PBS-native export, the backend also uses the Proxmox API to hand the selected USB disk through to the PBS VM before preparation/export.

- `HOST_AGENT_BASE_URL` points to the host agent API, for example `http://proxmox-host:8081`
- `HOST_AGENT_TOKEN` is sent as the shared `X-Agent-Token` header
- `HOST_AGENT_TIMEOUT_SECONDS` controls request timeout
- `PBS_AGENT_BASE_URL` points to the PBS execution agent API, for example `http://pbs-host:8081`
- `PBS_AGENT_TOKEN` is sent as the shared `X-Agent-Token` header
- `PBS_AGENT_TIMEOUT_SECONDS` controls request timeout
- `PBS_EXECUTION_VM_ID` identifies the PBS VM on Proxmox for USB handoff
- `PBS_EXECUTION_VM_NODE` identifies the Proxmox node hosting that PBS VM
