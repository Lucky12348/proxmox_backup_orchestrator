# Security

This project intentionally separates normal application logic from privileged host operations. The app VM runs Docker Compose without direct root access to Proxmox or PBS internals. Root-only operations are exposed by two narrow HTTP agents and must be protected by strong tokens and firewall rules.

Do not use `code_secret`.

## Authentication Variables

The Web UI and API use a single local admin account:

```env
AUTH_ENABLED=true
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=$$2b$$12$$...
AUTH_SECRET_KEY=<random>
AUTH_TOKEN_EXPIRE_MINUTES=480
```

Generate the password hash:

```bash
python scripts/generate_password_hash.py
```

Docker Compose `.env` files must escape every bcrypt `$` as `$$`.

Generate `AUTH_SECRET_KEY`:

```bash
openssl rand -hex 32
```

Keep `.env` out of git. The repository `.gitignore` excludes `.env` and `.env.*` except `.env.example`.

## Agent Tokens

Each root agent has its own shared bearer-style token sent in the `X-Agent-Token` header.

Generate separate tokens:

```bash
openssl rand -hex 32  # Proxmox host agent
openssl rand -hex 32  # PBS VM agent
```

App VM:

```env
HOST_AGENT_BASE_URL=http://<proxmox-host>:8090
HOST_AGENT_TOKEN=<host-agent-token>
PBS_AGENT_BASE_URL=http://<pbs-vm>:8091
PBS_AGENT_TOKEN=<pbs-agent-token>
```

Proxmox host agent:

```env
AGENT_SERVER_PORT=8090
AGENT_SERVER_TOKEN=<host-agent-token>
```

PBS VM agent:

```env
AGENT_SERVER_PORT=8091
AGENT_SERVER_TOKEN=<pbs-agent-token>
```

Never reuse these tokens for Proxmox API, PBS API, or the web login.

## Firewall Rules

Agent HTTP ports must only be reachable from the app VM IP.

Required exposure:

```text
Proxmox host agent: TCP 8090 from <app-vm-ip> only
PBS VM agent:       TCP 8091 from <app-vm-ip> only
```

No browser, LAN client, or internet host should be able to call the agent ports.

## Proxmox Firewall `host.fw` for Port 8090

The node-local host firewall file is:

```text
/etc/pve/nodes/<node-name>/host.fw
```

Example:

```text
/etc/pve/nodes/promox/host.fw
```

Cluster-wide firewall configuration is separate and lives in:

```text
/etc/pve/firewall/cluster.fw
```

Example host rule file:

```ini
[OPTIONS]
enable: 1

[RULES]
IN ACCEPT -source <app-vm-ip> -p tcp -dport 8090 -log nolog
IN DROP -p tcp -dport 8090 -log warning
```

Reload or verify the firewall from the Proxmox UI or CLI:

```bash
pve-firewall status
pve-firewall compile
```

Keep any existing management rules required for your environment.

## PBS `nftables` for Port 8091

Simple deployed variant with default accept policy:

```nft
table inet filter {
  chain input {
    type filter hook input priority 0;
    policy accept;

    ip saddr <app-vm-ip> tcp dport 8091 accept
    tcp dport 8091 drop
  }
}
```

This keeps the rest of the PBS VM networking unchanged while restricting the PBS agent port to the app VM.

Stricter default-drop example `/etc/nftables.conf`:

```nft
#!/usr/sbin/nft -f

flush ruleset

table inet filter {
  chain input {
    type filter hook input priority 0;
    policy drop;

    iif "lo" accept
    ct state established,related accept

    ip saddr <trusted-admin-subnet> tcp dport { 22, 8007 } accept
    ip saddr <app-vm-ip> tcp dport 8091 accept

    ip protocol icmp accept
    ip6 nexthdr icmpv6 accept

    counter drop
  }

  chain forward {
    type filter hook forward priority 0;
    policy drop;
  }

  chain output {
    type filter hook output priority 0;
    policy accept;
  }
}
```

Enable and validate:

```bash
nft -c -f /etc/nftables.conf
systemctl enable --now nftables
nft list ruleset
```

Adjust SSH and PBS UI/API access for your management network before enabling a default-drop policy.

## Secrets Backup

Back up these files securely:

- app VM `/opt/proxmox_backup_orchestrator/.env`
- Proxmox host `/opt/proxmox-backup-orchestrator-agent/.env`
- PBS VM `/opt/proxmox-backup-orchestrator-pbs-agent/.env`
- Proxmox and PBS API token records, if not recoverable from the UI

Recommended handling:

- store encrypted copies in a password manager or encrypted offline vault
- restrict file permissions to root or the deployment user
- avoid screenshots and chat logs containing secrets
- rotate secrets after any accidental disclosure

## Token Rotation

Rotate agent tokens one agent at a time.

Proxmox host agent:

1. Generate a new token with `openssl rand -hex 32`.
2. Update Proxmox agent `AGENT_SERVER_TOKEN`.
3. Update app VM `HOST_AGENT_TOKEN`.
4. Restart the Proxmox agent and API.
5. Verify `/health` with the new token.

PBS agent:

1. Generate a new token.
2. Update PBS agent `AGENT_SERVER_TOKEN`.
3. Update app VM `PBS_AGENT_TOKEN`.
4. Restart the PBS agent and API.
5. Verify `/health` with the new token.

JWT/login rotation:

1. Generate a new `AUTH_SECRET_KEY`.
2. Optionally regenerate `AUTH_PASSWORD_HASH`.
3. Restart the API.
4. Log in again.

Changing `AUTH_SECRET_KEY` invalidates existing sessions.

## Known Risks and Limits

- The root agents are powerful by design. If an agent token is stolen and the firewall allows access, an attacker can trigger privileged disk or QEMU operations.
- Agent authentication is a shared token, not per-user authorization.
- Dedicated disk preparation can format a disk after confirmation. Operational discipline is required when selecting disks.
- If `PVE_VERIFY_SSL=false` or `PBS_VERIFY_SSL=false`, API TLS certificates are not verified. Prefer trusted certificates or fingerprints where feasible.
- `.env` backup loss can make recovery harder because API and agent tokens may need to be recreated.
- The app database tracks activity, but PBS backup data lives in PBS datastores. Protect both.

## Troubleshooting

**Login is incorrect due to malformed `AUTH_PASSWORD_HASH`**

Check that the runtime value starts with `$2` inside the API container. The Compose file should contain `$$2b$$12$$...`; Compose converts that to `$2b$12$...` for the container.

**`code_secret` still works**

Search and remove legacy configuration:

```bash
grep -R "code_secret" -n /opt /etc/systemd /etc/default 2>/dev/null
```

Restart the affected services after removal.

**Agent health returns 401**

This means the agent is reachable but rejected the token. Verify the exact shared secret pair and avoid trailing spaces in `.env`.

**PBS disk visible but not mounted**

The firewall is not usually the cause if the disk is visible inside PBS. Check PBS agent logs and datastore preparation output. Reused disks should already contain the expected PBS datastore structure.

**USB passthrough still attached**

The host agent may have failed during the detach step or the app may be using the wrong `PBS_EXECUTION_VM_ID`. Verify `qm config <pbs-vm-id>` and host agent logs.

**External datastore reuse vs first format**

Destructive formatting should only be needed on first preparation or when force formatting is explicitly requested. Treat unexpected format prompts as a warning to stop and verify the physical disk identity.
