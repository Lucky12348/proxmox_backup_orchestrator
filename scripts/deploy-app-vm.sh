#!/usr/bin/env bash
set -euo pipefail

APP_REPO_PATH="${APP_REPO_PATH:-/opt/proxmox_backup_orchestrator}"
APP_COMPOSE_FILE="${APP_COMPOSE_FILE:-infra/docker/docker-compose.yml}"
APP_MAINTENANCE_AGENT_SERVICE="${APP_MAINTENANCE_AGENT_SERVICE:-proxmox-backup-orchestrator-app-maintenance-agent.service}"

cd "$APP_REPO_PATH"

if [[ ! -f .env ]]; then
  echo ".env not found at APP_REPO_PATH" >&2
  exit 1
fi

git pull --ff-only

if command -v systemctl >/dev/null 2>&1; then
  systemctl restart "$APP_MAINTENANCE_AGENT_SERVICE"
else
  echo "systemctl not found; restart $APP_MAINTENANCE_AGENT_SERVICE manually" >&2
fi

if command -v docker-compose >/dev/null 2>&1; then
  docker-compose --env-file .env -f "$APP_COMPOSE_FILE" up --build -d
else
  docker compose --env-file .env -f "$APP_COMPOSE_FILE" up --build -d
fi
