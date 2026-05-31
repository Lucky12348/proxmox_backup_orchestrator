#!/usr/bin/env bash
set -euo pipefail

APP_REPO_PATH="${APP_REPO_PATH:-/opt/proxmox_backup_orchestrator}"
APP_COMPOSE_FILE="${APP_COMPOSE_FILE:-infra/docker/docker-compose.yml}"
APP_MAINTENANCE_AGENT_SERVICE="${APP_MAINTENANCE_AGENT_SERVICE:-proxmox-backup-orchestrator-app-maintenance-agent.service}"
PROXMOX_AGENT_VENV="${PROXMOX_AGENT_VENV:-/opt/proxmox-backup-orchestrator-agent/.venv}"
PROXMOX_AGENT_SERVICE="${PROXMOX_AGENT_SERVICE:-proxmox-backup-orchestrator-agent-api.service}"
PROXMOX_AGENT_URL="${PROXMOX_AGENT_URL:-http://127.0.0.1:8081}"
PBS_AGENT_VENV="${PBS_AGENT_VENV:-/opt/proxmox-backup-orchestrator-pbs-agent/.venv}"
PBS_AGENT_SERVICE="${PBS_AGENT_SERVICE:-proxmox-backup-orchestrator-pbs-agent-http.service}"
PBS_AGENT_URL="${PBS_AGENT_URL:-http://127.0.0.1:8091}"
AGENT_TOKEN="${AGENT_TOKEN:-${HOST_AGENT_TOKEN:-${PBS_AGENT_TOKEN:-}}}"

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
  if [[ -x "$PROXMOX_AGENT_VENV/bin/python" ]]; then
    "$PROXMOX_AGENT_VENV/bin/python" -m pip install -e apps/agent
    systemctl restart "$PROXMOX_AGENT_SERVICE"
  else
    echo "Warning: Proxmox agent venv not found at $PROXMOX_AGENT_VENV" >&2
  fi
  if [[ -x "$PBS_AGENT_VENV/bin/python" ]]; then
    "$PBS_AGENT_VENV/bin/python" -m pip install -e apps/agent
    systemctl restart "$PBS_AGENT_SERVICE"
  else
    echo "Warning: PBS agent venv not found at $PBS_AGENT_VENV" >&2
  fi
  systemctl restart "$APP_MAINTENANCE_AGENT_SERVICE"
else
  echo "systemctl not found; restart app and agent services manually" >&2
fi

if command -v docker-compose >/dev/null 2>&1; then
  docker-compose --env-file .env -f "$APP_COMPOSE_FILE" up --build -d
else
  docker compose --env-file .env -f "$APP_COMPOSE_FILE" up --build -d
fi

verify_agent() {
  local label="$1"
  local service="$2"
  local venv="$3"
  local url="$4"

  echo "== $label preflight =="
  echo "service=$service"
  echo "venv=$venv"
  if [[ -x "$venv/bin/python" ]]; then
    "$venv/bin/python" - <<'PY'
import agent.main
import sys
print(f"python={sys.executable}")
print(f"agent.main={agent.main.__file__}")
PY
  fi
  if command -v git >/dev/null 2>&1; then
    echo "git_sha=$(git rev-parse HEAD)"
  fi
  if command -v systemctl >/dev/null 2>&1; then
    systemctl is-active --quiet "$service"
    echo "service_status=active"
  fi
  if command -v curl >/dev/null 2>&1 && [[ -n "$AGENT_TOKEN" ]]; then
    curl -fsS -H "X-Agent-Token: $AGENT_TOKEN" "$url/version" | grep -E '"version-endpoint"|"inspect-disk-alias-resolution"|"qemu-usb-attach"' >/dev/null
    echo "capabilities=verified"
  else
    echo "capabilities=skipped (curl or AGENT_TOKEN missing)" >&2
  fi
}

verify_agent "Proxmox agent" "$PROXMOX_AGENT_SERVICE" "$PROXMOX_AGENT_VENV" "$PROXMOX_AGENT_URL"
verify_agent "PBS agent" "$PBS_AGENT_SERVICE" "$PBS_AGENT_VENV" "$PBS_AGENT_URL"
