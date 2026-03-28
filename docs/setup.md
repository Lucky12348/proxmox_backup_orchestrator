# Setup

## Local Prerequisites

- Python 3.11+
- Node.js 20+
- Docker and Docker Compose

## Initial Setup

1. Copy `.env.example` to `.env`
2. Review and adjust environment variables
3. Install API dependencies in `apps/api`
4. Install web dependencies in `apps/web`
5. Install agent dependencies in `apps/agent`

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
docker compose -f infra/docker/docker-compose.yml up --build
```
