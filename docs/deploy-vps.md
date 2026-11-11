# Deploy mindyard on a VPS for Claude.ai

This guide puts your wiki behind `https://wiki.example.org/mcp`, so that Claude.ai
(web and mobile) can read and edit it, signed in with your Google account. For local
use with Claude Desktop or Claude Code, you need none of this: see the quickstart in
the [README](../README.md).

You need:

- a Linux VPS with `sudo` (the commands below assume Debian or Ubuntu);
- a domain name whose DNS record points to the VPS (here `wiki.example.org`);
- a Google account, to create the OAuth client.

Python is not required on the VPS: `uv` installs the version mindyard needs.

## 1. Install mindyard under a dedicated user

```bash
sudo apt-get install -y git curl
sudo useradd --system --create-home --home-dir /var/lib/mindyard --shell /usr/sbin/nologin mindyard
sudo -u mindyard -H sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
sudo -u mindyard -H /var/lib/mindyard/.local/bin/uv tool install mindyard
```

Then create a vault (drop `--demo` for an empty one):

```bash
sudo -u mindyard -H /var/lib/mindyard/.local/bin/mindyard init /var/lib/mindyard/data/vaults/notes --demo
```

Every directory under `/var/lib/mindyard/data/vaults/` holding a `wiki.yaml` is served
as one wiki. Each vault is a git repository: every edit Claude makes is a commit.

## 2. Create a Google OAuth client

Claude.ai signs in through Google; mindyard checks the account against your allowlist.

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project
   (or pick one).
2. Under **Google Auth Platform**, configure the consent screen: audience **External**,
   and while the app is in **Testing**, add your own Google account as a test user.
   The scopes mindyard asks for are `openid`, `email` and `profile`.
3. Under **Clients**, create a client of type **Web application**, with this authorized
   redirect URI:

   ```text
   https://wiki.example.org/auth/callback
   ```

4. Keep the client ID and the client secret for the next step.

## 3. Configure and run the service

Secrets go in a file only root can read:

```bash
sudo install -d -m 755 /etc/mindyard
sudo install -m 600 /dev/null /etc/mindyard/mindyard.env
sudoedit /etc/mindyard/mindyard.env
```

```ini
MINDYARD_DATA_ROOT=/var/lib/mindyard/data
MINDYARD_AUTH=google
MINDYARD_BASE_URL=https://wiki.example.org
MINDYARD_GOOGLE_CLIENT_ID=1234567890-abc.apps.googleusercontent.com
MINDYARD_GOOGLE_CLIENT_SECRET=replace-me
# Comma-separated; only these verified Google accounts get in.
MINDYARD_ALLOWED_EMAILS=you@example.org
```

`MINDYARD_ALLOWED_EMAILS` is mandatory: without it, any Google account could sign in,
so mindyard refuses to start. The server listens on `127.0.0.1:8787` by default, behind
the reverse proxy of step 4.

Create `/etc/systemd/system/mindyard.service`:

```ini
[Unit]
Description=mindyard MCP server
After=network-online.target
Wants=network-online.target

[Service]
Type=exec
User=mindyard
Group=mindyard
EnvironmentFile=/etc/mindyard/mindyard.env
ExecStart=/var/lib/mindyard/.local/bin/mindyard serve
Restart=on-failure
RestartSec=5s
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mindyard
sudo systemctl status mindyard --no-pager
```

A configuration that would expose your vaults stops the service at startup, with the
reason in `journalctl -u mindyard`.

## 4. Put HTTPS in front

The reverse proxy must forward the **whole site**, not only `/mcp`: the server also
answers the OAuth discovery, authorization and callback routes. Do not add any
authentication at the proxy; mindyard enforces it.

**Caddy** (obtains the certificate itself), in `/etc/caddy/Caddyfile`:

```text
wiki.example.org {
    reverse_proxy 127.0.0.1:8787
}
```

**nginx**, in `/etc/nginx/sites-available/wiki.example.org`, then
`sudo certbot --nginx -d wiki.example.org` to add TLS:

```nginx
server {
    listen 80;
    server_name wiki.example.org;

    location / {
        proxy_pass http://127.0.0.1:8787;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # MCP streams responses: no buffering, long timeout.
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
```

Check: `curl https://wiki.example.org/.well-known/oauth-authorization-server` returns
JSON.

## 5. Connect Claude.ai

In Claude.ai, open **Settings**, then **Connectors**, add a custom connector with the URL:

```text
https://wiki.example.org/mcp
```

Claude.ai opens the Google sign-in. Once you are back, ask Claude to list your wikis.

## Operations

- **Upgrade:** `sudo -u mindyard -H /var/lib/mindyard/.local/bin/uv tool upgrade mindyard`,
  then `sudo systemctl restart mindyard`.
- **Backups:** the vaults are git repositories; push them to a private remote, or back
  up `/var/lib/mindyard/data`. Its `state/` directory holds OAuth registrations and
  tokens: it is not a cache, and deleting it signs every client out.
- **Lint:** `mindyard lint <vault>` writes the report that `get_lint_report` returns; run
  it from cron if you want it fresh.
- **Logs:** a few `400 Missing session ID` lines when Claude.ai connects are expected:
  the client probes before opening a session.
- **Docker** instead of systemd: `compose.example.yaml` in the repository runs the same
  server; the reverse proxy and Google steps are unchanged.
