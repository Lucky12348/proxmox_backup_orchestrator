#!/usr/bin/env bash
set -euo pipefail

APP_REPO_PATH="${APP_REPO_PATH:-/opt/proxmox_backup_orchestrator}"
APP_COMPOSE_FILE="${APP_COMPOSE_FILE:-infra/docker/docker-compose.yml}"
APP_MAINTENANCE_AGENT_SERVICE="${APP_MAINTENANCE_AGENT_SERVICE:-proxmox-backup-orchestrator-app-maintenance-agent.service}"

cd "$APP_REPO_PATH"

if [[ ! -f .env ]]; then
  if [[ ! -f .env.example ]]; then
    echo ".env not found and .env.example template is missing" >&2
    exit 1
  fi
  cp .env.example .env
  echo ".env created from template"
else
  echo ".env preserved"
fi

git pull --ff-only

notification_env_value() {
  local key="$1"
  (grep -E "^[[:space:]]*${key}=" .env || true) | tail -n 1 | cut -d= -f2- | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

notifications_enabled="$(notification_env_value NOTIFICATIONS_ENABLED)"
ntfy_base_url="$(notification_env_value NTFY_BASE_URL)"
if [[ "${notifications_enabled,,}" != "true" && "${notifications_enabled}" != "1" && "${notifications_enabled,,}" != "yes" && "${notifications_enabled,,}" != "on" ]]; then
  echo "Warning: NOTIFICATIONS_ENABLED=false; notification delivery is disabled." >&2
fi
if [[ "${ntfy_base_url%/}" == "https://ntfy.sh" ]]; then
  echo "Warning: NTFY_BASE_URL=https://ntfy.sh; configure your own ntfy server for production." >&2
fi
if [[ "${notifications_enabled,,}" == "true" || "${notifications_enabled}" == "1" || "${notifications_enabled,,}" == "yes" || "${notifications_enabled,,}" == "on" ]]; then
  missing=()
  for key in NTFY_BASE_URL NTFY_TOPIC NTFY_USERNAME NTFY_PASSWORD; do
    if [[ -z "$(notification_env_value "$key")" ]]; then
      missing+=("$key")
    fi
  done
  if [[ "${ntfy_base_url%/}" == "https://ntfy.sh" ]]; then
    echo "NTFY_BASE_URL must not use the public default when notifications are enabled." >&2
    exit 1
  fi
  if [[ ${#missing[@]} -gt 0 ]]; then
    printf 'Missing required notification environment values: %s\n' "${missing[*]}" >&2
    exit 1
  fi
fi

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
