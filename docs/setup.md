# Setup

## Local Prerequisites

- Python 3.11+
- Node.js 20+
- Docker and Docker Compose

## Initial Setup

1. Copy `.env.example` to `.env`
2. Review and adjust environment variables
3. Run `make bootstrap` to verify the local URLs and environment file
4. Start the local stack with `docker compose -f infra/docker/docker-compose.yml up --build`
5. Open the web dashboard and API docs in the browser
6. Install local app dependencies only if you want to run API or web outside Docker

Use `postgresql+psycopg://...` for `DATABASE_URL`. The backend also rewrites plain
`postgresql://...` URLs to psycopg3 automatically for local compatibility.

For POSIX shells, a matching helper is available at `infra/scripts/bootstrap.sh`.

## Local URLs

- Web dashboard: `http://localhost:5173`
- API docs: `http://localhost:8000/docs`
- API health: `http://localhost:8000/health`
- API overview: `http://localhost:8000/api/v1/overview`

## Seed Data

In development, the API creates tables automatically and seeds a small demo dataset on startup if the database is empty.

The seeded data currently includes:

- 4 example workloads: 2 VMs and 2 containers
- 3 example external disks with different connection states
- disk assignment examples
- 2 backup run history entries

The seed routine is idempotent for an empty database and will not duplicate rows on restart.

## Example Commands

### API

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload
```

### Web

```bash
cd apps/web
npm install
npm run dev
```

### Agent

```bash
cd apps/agent
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m agent.main
```

### Docker

```bash
cp .env.example .env
make bootstrap
docker compose -f infra/docker/docker-compose.yml up --build
```

Once the stack is running, open `http://localhost:5173`.
