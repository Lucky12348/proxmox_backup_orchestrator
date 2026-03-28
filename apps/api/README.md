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
