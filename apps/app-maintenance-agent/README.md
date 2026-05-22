# App Maintenance Agent

Local-only maintenance API for the App VM.

It binds to `127.0.0.1:8092` by default and exposes:

- `GET /health`
- `POST /maintenance/check`
- `POST /maintenance/update`

All endpoints require `X-Agent-Token`.
