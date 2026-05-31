# App Maintenance Agent

Local-only maintenance API for the App VM.

It binds to `127.0.0.1:8092` by default and exposes:

- `GET /health`
- `POST /maintenance/check`
- `POST /maintenance/update`

All endpoints require `X-Agent-Token`.

App updates run from `APP_REPO_PATH`. If `APP_REPO_PATH/.env` already exists,
it is preserved exactly; if it is missing, the agent creates it once from
`.env.example`. Docker Compose is always called with `--env-file .env` so
recreated containers receive production settings. The preflight and
post-update checks print only non-secret notification state; secrets are not
printed. After a successful update, the agent schedules a delayed restart of
its own systemd service so future Settings updates use the newly pulled agent
code.
