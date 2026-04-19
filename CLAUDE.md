# apps-manager

## What This Is
A web application that manages geocam app containers on a DGX Spark server. It is the web UI equivalent of ansible playbooks. Users log in and create, manage, and destroy their own app containers.

## Architecture
- This app runs on port 8080 (0.0.0.0:8080) via start_webserver.sh
- It is served at https://apps-manager-app.geocam.io
- It has SSH access to the Spark host via `ssh spark` (key already configured)
- All container management is done by running `ssh spark "incus ..."` commands
- Credentials are in .env (Cloudflare, GitHub, Claude API keys)

## What It Must Do

### 1. User Management
- Simple user/password auth (store in a local SQLite DB or JSON file)
- Each user has a username, password, and can own multiple apps
- Admin user (username: admin, password: read from ADMIN_PASSWORD env or default sage-birch)

### 2. Create App
When a user clicks "Create App" and provides a name, the system must do ALL of the following in order:

#### a) Container Creation
```bash
ssh spark "incus launch images:ubuntu/22.04 <appname> --profile default --profile spark-gpu"
# Wait for it to be running and get its IP
ssh spark "incus exec <appname> -- ip -4 addr show eth0 | grep inet"
```

#### b) Container Provisioning
```bash
# DNS
ssh spark "incus exec <appname> -- bash -c \"echo 'nameserver 1.1.1.1' > /etc/resolv.conf\""

# Base packages
ssh spark "incus exec <appname> -- bash -c 'apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server sudo curl wget vim nano htop ca-certificates tmux bash-completion git python3 python3-pip python3-venv apache2-utils'"

# Create dev user with generated password
ssh spark "incus exec <appname> -- bash -c \"useradd -m -s /bin/bash -G sudo dev && echo 'dev:<password>' | chpasswd && echo 'dev ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/dev\""

# SSH setup (enable password auth)
ssh spark "incus exec <appname> -- bash -c \"sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config && systemctl enable ssh && systemctl restart ssh\""

# NVIDIA drivers
ssh spark "incus exec <appname> -- bash -c 'DEBIAN_FRONTEND=noninteractive apt-get install -y nvidia-utils-580 libnvidia-compute-580'"

# Claude Code
ssh spark "incus exec <appname> -- bash -c 'curl -fsSL https://claude.ai/install.sh | bash'"
ssh spark "incus exec <appname> -- su - dev -c 'curl -fsSL https://claude.ai/install.sh | bash'"

# Set ANTHROPIC_API_KEY
ssh spark "incus exec <appname> -- bash -c \"echo 'export ANTHROPIC_API_KEY=<key>' >> /home/dev/.bashrc\""

# Node.js (for claude-code-web)
ssh spark "incus exec <appname> -- bash -c 'curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && apt-get install -y nodejs'"
ssh spark "incus exec <appname> -- bash -c 'npm install -g claude-code-web'"

# DHCP fix
ssh spark "incus exec <appname> -- bash -c 'mkdir -p /etc/systemd/network/10-netplan-eth0.network.d && printf \"[Network]\nKeepConfiguration=dhcp\n\" > /etc/systemd/network/10-netplan-eth0.network.d/keep.conf && systemctl reload systemd-networkd'"
```

#### c) Desktop Environment (Selkies)
Install X11, Selkies, nginx with basic auth. Cached selkies assets are on Spark at /opt/geocam-apps-cache/:
```bash
ssh spark "incus exec <appname> -- bash -c 'DEBIAN_FRONTEND=noninteractive apt-get install -y xvfb openbox dbus dbus-x11 pulseaudio x11-common x11-utils x11-apps x11-xserver-utils xserver-xorg-core xclip nginx xterm build-essential python3-dev libffi-dev libpulse-dev portaudio19-dev libxkbcommon-dev libavcodec-dev libavformat-dev libavutil-dev libswscale-dev libswresample-dev pkg-config'"

# Push cached assets
ssh spark "incus file push /opt/geocam-apps-cache/xkbcommon.tar.gz <appname>/tmp/xkbcommon.tar.gz"
ssh spark "incus file push /opt/geocam-apps-cache/selkies-web.tar.gz <appname>/tmp/selkies-web.tar.gz"

# Install selkies in venv
ssh spark "incus exec <appname> -- bash -c '
python3 -m venv /opt/selkies-venv --system-site-packages
/opt/selkies-venv/bin/pip install --upgrade pip
tar xzf /tmp/xkbcommon.tar.gz -C /opt/selkies-venv/lib/python3.10/site-packages/
/opt/selkies-venv/bin/pip install cffi pixelflux==1.4.7 av aiofiles aiohttp aioice distro google-crc32c gputil msgpack pasimple pcmflux Pillow prometheus_client psutil pulsectl pyee pylibsrtp pynput pyopenssl python-xlib watchdog websockets
/opt/selkies-venv/bin/pip install --no-deps git+https://github.com/selkies-project/selkies.git
'"

# Create selkies entry point script
ssh spark "incus exec <appname> -- bash -c 'printf \"#!/opt/selkies-venv/bin/python3\nimport sys\nfrom selkies.__main__ import main\nif __name__ == \\\"__main__\\\":\n    sys.argv[0] = sys.argv[0].removesuffix(\\\".exe\\\")\n    sys.exit(main())\n\" > /opt/selkies-venv/bin/selkies && chmod +x /opt/selkies-venv/bin/selkies'"

# Extract web UI
ssh spark "incus exec <appname> -- bash -c 'tar xzf /tmp/selkies-web.tar.gz -C /usr/share/'"

# Runtime dir for dev user
ssh spark "incus exec <appname> -- bash -c 'mkdir -p /run/user/1000/pulse && chown -R dev:dev /run/user/1000'"

# Create htpasswd for nginx basic auth
ssh spark "incus exec <appname> -- bash -c 'htpasswd -bc /etc/nginx/.htpasswd dev <password>'"

# Create systemd services:
# - xvfb.service: Xvfb :1 -screen 0 1920x1080x24 (User=dev)
# - openbox.service: dbus-launch openbox-session (User=dev, DISPLAY=:1, After=xvfb)
# - pulseaudio-selkies.service: pulseaudio --exit-idle-time=-1 (User=dev, XDG_RUNTIME_DIR=/run/user/1000)
# - selkies.service: /opt/selkies-venv/bin/selkies --addr=localhost --port=8082 --control-port=8084 --mode=websockets (User=dev, DISPLAY=:1, PULSE_SERVER=unix:/run/user/1000/pulse/native, ExecStartPre=/bin/sleep 3, Requires=xvfb+openbox+pulseaudio)
# - nginx on port 8081 with basic auth, proxying /websocket(s) to localhost:8082

# claude-code-web systemd service:
# ExecStart: npx claude-code-web --port 8083 --auth <password> --no-open
# WorkingDirectory: /home/dev/<appname>
# Environment: ANTHROPIC_API_KEY=<key>

# app-webserver systemd service:
# ExecStart: /bin/bash /home/dev/<appname>/start_webserver.sh
# WorkingDirectory: /home/dev/<appname>
# Environment: PORT=8080
```

#### d) Cloudflare Tunnel (single tunnel, multiple ingress rules)
```python
import requests, secrets, base64

headers = {"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}", "Content-Type": "application/json"}
base = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}"

# 1. Create tunnel
tunnel_secret = base64.b64encode(secrets.token_bytes(32)).decode()
r = requests.post(f"{base}/cfd_tunnel", headers=headers, json={"name": appname, "tunnel_secret": tunnel_secret})
tunnel_id = r.json()["result"]["id"]

# 2. Configure ingress rules
requests.put(f"{base}/cfd_tunnel/{tunnel_id}/configurations", headers=headers, json={
    "config": {"ingress": [
        {"hostname": f"{appname}-app.geocam.io", "service": "http://localhost:8080"},
        {"hostname": f"{appname}-desktop.geocam.io", "service": "http://localhost:8081"},
        {"hostname": f"{appname}-code.geocam.io", "service": "http://localhost:8083"},
        {"hostname": f"{appname}-ssh.geocam.io", "service": "ssh://localhost:22"},
        {"service": "http_status:404"}
    ]}
})

# 3. Get tunnel token
r = requests.get(f"{base}/cfd_tunnel/{tunnel_id}/token", headers=headers)
token = r.json()["result"]

# 4. Create 4 DNS CNAME records (app, desktop, code, ssh)
zone_base = f"https://api.cloudflare.com/client/v4/zones/{CLOUDFLARE_ZONE_ID}"
for sub in [f"{appname}-app", f"{appname}-desktop", f"{appname}-code", f"{appname}-ssh"]:
    requests.post(f"{zone_base}/dns_records", headers=headers, json={
        "type": "CNAME", "name": f"{sub}.geocam.io",
        "content": f"{tunnel_id}.cfargotunnel.com", "proxied": True
    })

# 5. Install cloudflared in container and create systemd service
# Service runs: cloudflared tunnel run --token <TOKEN>
```

#### e) GitHub Repo
```python
headers = {"Authorization": f"token {GITHUB_PAT}", "Content-Type": "application/json"}

# Create repo in org
requests.post("https://api.github.com/orgs/geocam-apps/repos", headers=headers,
    json={"name": appname, "private": False, "auto_init": False})

# Inside container: download template, init repo, push
# Template: GET https://api.github.com/repos/geocam-apps/base_template/tarball/main (with auth header)
# Git credential store: echo "https://x-access-token:<PAT>@github.com" > ~/.git-credentials
```

#### f) Password Generation
Generate a memorable password from two random words joined by hyphen (e.g. "tiger-castle"). Use this for:
- dev user SSH password
- Selkies desktop nginx basic auth (htpasswd)
- claude-code-web --auth token

### 3. List Apps
- Query: `ssh spark "incus list -f csv -c ns4"`
- Cross-reference with local DB to show owner, password, creation date
- Show links to each app's services (app, desktop, code URLs)

### 4. Destroy App
Full cleanup in order:
1. `ssh spark "incus stop <name> --force && incus delete <name> --force"`
2. Find and delete Cloudflare tunnel by name via API
3. Delete 4 DNS records: <name>-app, <name>-desktop, <name>-code, <name>-ssh
4. Delete GitHub repo: `DELETE /repos/geocam-apps/<name>`
5. Remove from local DB

### 5. App Status/Details
- Show running services inside container via `ssh spark "incus exec <name> -- systemctl is-active <svc>"`
- Show container IP, all Cloudflare URLs, GitHub repo link
- Show the generated password
- Optionally show recent logs

### 6. Restart Services
- Restart individual services: `ssh spark "incus exec <name> -- systemctl restart <service>"`
- Services: xvfb, openbox, pulseaudio-selkies, selkies, nginx, cloudflared-tunnel, app-webserver, claude-code-web

## Technical Requirements
- **MANDATORY**: Web server MUST bind to 0.0.0.0:8080
- After editing start_webserver.sh: `sudo systemctl restart app-webserver`
- Use Python (Flask/FastAPI) or Node.js
- Store app metadata (owner, password, creation date, container name) in SQLite
- Clean, functional web UI
- All Cloudflare/GitHub API calls happen server-side
- All incus commands run via `ssh spark "..."`
- Long-running operations (create/destroy) should show progress or run async
- Commit and push to git frequently

## Credentials
All credentials are in .env file. Load with python-dotenv or equivalent.

## SSH to Spark
Pre-configured: just run `ssh spark` or use subprocess/paramiko with host="spark".
Test: `ssh spark "incus list -f csv -c n"`

## Environment
- Ubuntu 22.04 arm64 (DGX Spark)
- Python 3.10, Node.js 20
- Git configured with PAT credential store
