import asyncio
import os
import re
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

SPARK_HOST = os.getenv("SPARK_HOST", "spark")
SPARK_SSH_KEY = os.getenv("SPARK_SSH_KEY", "")

def _ssh_args() -> list[str]:
    args = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=15",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=20",
        "-o", "TCPKeepAlive=yes",
    ]
    if SPARK_SSH_KEY:
        expanded = os.path.expanduser(SPARK_SSH_KEY)
        if os.path.exists(expanded):
            args += ["-i", expanded]
    args.append(SPARK_HOST)
    return args


async def run_ssh(cmd: str, timeout: int = 300) -> str:
    """Run a command on the spark host via SSH."""
    proc = await asyncio.create_subprocess_exec(
        *_ssh_args(), cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"SSH timed out after {timeout}s running: {cmd[:200]}")
    if proc.returncode != 0:
        out = stdout.decode().strip()
        err = stderr.decode().strip()
        parts = []
        if err:
            parts.append(f"stderr: {err[:1000]}")
        if out:
            parts.append(f"stdout: {out[:500]}")
        detail = "\n".join(parts) or "(no output)"
        raise RuntimeError(
            f"SSH failed (rc={proc.returncode}) on: {cmd[:300]}\n{detail}"
        )
    return stdout.decode().strip()


async def create_container(name: str) -> None:
    await run_ssh(
        f'incus launch images:ubuntu/22.04 {name} --profile default --profile spark-gpu',
        timeout=120,
    )
    # Wait for running state
    for _ in range(30):
        await asyncio.sleep(2)
        try:
            state = await run_ssh(f'incus list {name} -f csv -c s')
            if 'RUNNING' in state:
                return
        except Exception:
            pass
    raise RuntimeError("Container never reached RUNNING state")


async def get_container_ip(name: str) -> Optional[str]:
    for _ in range(20):
        try:
            out = await run_ssh(f'incus exec {name} -- ip -4 addr show eth0 | grep inet')
            match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', out)
            if match:
                return match.group(1)
        except Exception:
            pass
        await asyncio.sleep(3)
    return None


async def provision_base(name: str, password: str, anthropic_key: str, admin_token: str = "") -> None:
    cmds = [
        f"incus exec {name} -- bash -c \"echo 'nameserver 1.1.1.1' > /etc/resolv.conf\"",
        f"incus exec {name} -- bash -c 'apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server sudo curl wget vim nano htop ca-certificates tmux bash-completion git python3 python3-pip python3-venv apache2-utils'",
        f"incus exec {name} -- bash -c \"useradd -m -s /bin/bash -G sudo dev && echo 'dev:{password}' | chpasswd && echo 'dev ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/dev\"",
        f"incus exec {name} -- bash -c \"sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config && systemctl enable ssh && systemctl restart ssh\"",
        f"incus exec {name} -- bash -c 'DEBIAN_FRONTEND=noninteractive apt-get install -y nvidia-utils-580 libnvidia-compute-580'",
        # Install Claude Code system-wide; dev-user install is best-effort (may fail on arm64)
        f"incus exec {name} -- bash -c 'curl -fsSL https://claude.ai/install.sh | bash'",
        f"incus exec {name} -- su - dev -c 'curl -fsSL https://claude.ai/install.sh | bash || true'",
        f"incus exec {name} -- bash -c \"echo 'export ANTHROPIC_API_KEY={anthropic_key}' >> /home/dev/.bashrc\"",
        f"incus exec {name} -- bash -c 'curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && apt-get install -y nodejs'",
        f"incus exec {name} -- bash -c 'npm install -g claude-code-web'",
        f"incus exec {name} -- bash -c 'mkdir -p /etc/systemd/network/10-netplan-eth0.network.d && printf \"[Network]\\nKeepConfiguration=dhcp\\n\" > /etc/systemd/network/10-netplan-eth0.network.d/keep.conf && systemctl reload systemd-networkd'",
    ]
    if admin_token:
        # Write admin token to a protected file readable only by root/dev
        cmds.append(
            f"incus exec {name} -- bash -c \"echo 'APP_ADMIN_TOKEN={admin_token}' > /etc/app-admin-token && chmod 640 /etc/app-admin-token\""
        )
        # Also set in /etc/environment so all processes can read it
        cmds.append(
            f"incus exec {name} -- bash -c \"echo 'APP_ADMIN_TOKEN={admin_token}' >> /etc/environment\""
        )
    for cmd in cmds:
        await run_ssh(cmd, timeout=600)


async def provision_desktop(name: str, password: str) -> None:
    # Install X11 and deps
    await run_ssh(
        f"incus exec {name} -- bash -c 'DEBIAN_FRONTEND=noninteractive apt-get install -y xvfb xfce4 xfce4-terminal xfce4-goodies dbus dbus-x11 pulseaudio x11-common x11-utils x11-apps x11-xserver-utils xserver-xorg-core xclip nginx build-essential python3-dev libffi-dev libpulse-dev portaudio19-dev libxkbcommon-dev libavcodec-dev libavformat-dev libavutil-dev libswscale-dev libswresample-dev pkg-config'",
        timeout=600,
    )
    # Push cached assets
    await run_ssh(
        f'incus file push /opt/geocam-apps-cache/xkbcommon.tar.gz {name}/tmp/xkbcommon.tar.gz',
        timeout=120,
    )
    await run_ssh(
        f'incus file push /opt/geocam-apps-cache/selkies-web.tar.gz {name}/tmp/selkies-web.tar.gz',
        timeout=120,
    )
    # Install selkies
    await run_ssh(
        f"incus exec {name} -- bash -c '"
        "python3 -m venv /opt/selkies-venv --system-site-packages && "
        "/opt/selkies-venv/bin/pip install --upgrade pip && "
        "tar xzf /tmp/xkbcommon.tar.gz -C /opt/selkies-venv/lib/python3.10/site-packages/ && "
        "/opt/selkies-venv/bin/pip install cffi pixelflux==1.4.7 av aiofiles aiohttp aioice distro google-crc32c gputil msgpack pasimple pcmflux Pillow prometheus_client psutil pulsectl pyee pylibsrtp pynput pyopenssl python-xlib watchdog websockets && "
        "/opt/selkies-venv/bin/pip install --no-deps git+https://github.com/selkies-project/selkies.git"
        "'",
        timeout=600,
    )
    await run_ssh(
        f"incus exec {name} -- bash -c 'printf \"#!/opt/selkies-venv/bin/python3\\nimport sys\\nfrom selkies.__main__ import main\\nif __name__ == \\\"__main__\\\":\\n    sys.argv[0] = sys.argv[0].removesuffix(\\\".exe\\\")\\n    sys.exit(main())\\n\" > /opt/selkies-venv/bin/selkies && chmod +x /opt/selkies-venv/bin/selkies'",
        timeout=30,
    )
    await run_ssh(
        f"incus exec {name} -- bash -c 'tar xzf /tmp/selkies-web.tar.gz -C /usr/share/'",
        timeout=60,
    )
    await run_ssh(
        f"incus exec {name} -- bash -c 'mkdir -p /run/user/1000/pulse && chown -R dev:dev /run/user/1000'",
        timeout=30,
    )
    await run_ssh(
        f"incus exec {name} -- bash -c 'htpasswd -bc /etc/nginx/.htpasswd dev {password}'",
        timeout=30,
    )
    await _create_systemd_services(name, password)


async def _create_systemd_services(name: str, password: str) -> None:
    services = {
        "xvfb": (
            "[Unit]\nDescription=Xvfb\nAfter=network.target\n\n"
            "[Service]\nUser=dev\nExecStart=Xvfb :1 -screen 0 8192x4096x24\nRestart=always\n\n"
            "[Install]\nWantedBy=multi-user.target"
        ),
        "xfce": (
            "[Unit]\nDescription=XFCE Desktop\nAfter=xvfb.service\n\n"
            "[Service]\nUser=dev\nEnvironment=DISPLAY=:1\nEnvironment=HOME=/home/dev\n"
            "Environment=XDG_RUNTIME_DIR=/run/user/1000\nEnvironment=XDG_SESSION_TYPE=x11\n"
            "ExecStart=dbus-launch --exit-with-session xfce4-session\nRestart=on-failure\nRestartSec=3\n\n"
            "[Install]\nWantedBy=multi-user.target"
        ),
        "pulseaudio-selkies": (
            "[Unit]\nDescription=PulseAudio for Selkies\nAfter=network.target\n\n"
            "[Service]\nUser=dev\nEnvironment=XDG_RUNTIME_DIR=/run/user/1000\n"
            "ExecStart=pulseaudio --exit-idle-time=-1\nRestart=always\n\n"
            "[Install]\nWantedBy=multi-user.target"
        ),
        "selkies": (
            "[Unit]\nDescription=Selkies Streaming\n"
            "After=xvfb.service xfce.service pulseaudio-selkies.service\n"
            "Requires=xvfb.service xfce.service pulseaudio-selkies.service\n\n"
            "[Service]\nUser=dev\nEnvironment=DISPLAY=:1\n"
            "Environment=PULSE_SERVER=unix:/run/user/1000/pulse/native\n"
            "ExecStartPre=/bin/sleep 3\n"
            "ExecStart=/opt/selkies-venv/bin/selkies --addr=localhost --port=8082 --control-port=8084 --mode=websockets --encoder=jpeg --jpeg-quality=80\n"
            "Restart=always\n\n"
            "[Install]\nWantedBy=multi-user.target"
        ),
    }
    for svc_name, unit_content in services.items():
        escaped = unit_content.replace("\\", "\\\\").replace('"', '\\"').replace("'", "'\\''")
        await run_ssh(
            f"incus exec {name} -- bash -c 'printf \"{escaped}\" > /etc/systemd/system/{svc_name}.service'",
            timeout=30,
        )

    nginx_conf = (
        "server {\n"
        "    listen 8081;\n\n"
        '    auth_basic "Desktop";\n'
        "    auth_basic_user_file /etc/nginx/.htpasswd;\n\n"
        "    root /usr/share/selkies/web;\n"
        "    index index.html;\n\n"
        "    location / {\n"
        "        try_files $uri $uri/ /index.html;\n"
        "    }\n\n"
        "    location ~* ^/(ws|websocket|websockets) {\n"
        "        proxy_pass http://localhost:8082;\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Upgrade $http_upgrade;\n"
        '        proxy_set_header Connection "upgrade";\n'
        "        proxy_set_header Host $host;\n"
        "        proxy_read_timeout 3600;\n"
        "    }\n"
        "}\n"
    )
    import base64 as _b64nginx
    encoded_nginx = _b64nginx.b64encode(nginx_conf.encode()).decode()
    await run_ssh(
        f"incus exec {name} -- bash -c '"
        f"echo {encoded_nginx} | base64 -d > /etc/nginx/sites-available/{name} && "
        f"ln -sf /etc/nginx/sites-available/{name} /etc/nginx/sites-enabled/{name} && "
        f"rm -f /etc/nginx/sites-enabled/default'",
        timeout=30,
    )

    # Disable XFCE screensaver/lock screen and tint2 (installed via xfce4-goodies)
    await run_ssh(
        f"incus exec {name} -- bash -c '"
        "mkdir -p /home/dev/.config/autostart && "
        "printf \"[Desktop Entry]\\nHidden=true\\n\" > /home/dev/.config/autostart/xfce4-screensaver.desktop && "
        "printf \"[Desktop Entry]\\nHidden=true\\n\" > /home/dev/.config/autostart/tint2.desktop && "
        "rm -f /etc/xdg/autostart/tint2.desktop && "
        "chown -R dev:dev /home/dev/.config'",
        timeout=15,
    )

    await run_ssh(
        f"incus exec {name} -- systemctl daemon-reload && "
        f"incus exec {name} -- systemctl enable xvfb xfce pulseaudio-selkies selkies nginx && "
        f"incus exec {name} -- systemctl start xvfb xfce pulseaudio-selkies selkies nginx",
        timeout=60,
    )


async def install_cloudflared(name: str, token: str) -> None:
    await run_ssh(
        f"incus exec {name} -- bash -c '"
        "curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | gpg --dearmor -o /usr/share/keyrings/cloudflare-main.gpg && "
        "echo \"deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main\" > /etc/apt/sources.list.d/cloudflared.list && "
        "apt-get update && apt-get install -y cloudflared'",
        timeout=300,
    )
    service = (
        "[Unit]\nDescription=Cloudflare Tunnel\nAfter=network.target\n\n"
        f"[Service]\nExecStart=/usr/bin/cloudflared tunnel run --token {token}\nRestart=always\n\n"
        "[Install]\nWantedBy=multi-user.target"
    )
    escaped = service.replace("\\", "\\\\").replace('"', '\\"').replace("'", "'\\''")
    await run_ssh(
        f"incus exec {name} -- bash -c 'printf \"{escaped}\" > /etc/systemd/system/cloudflared-tunnel.service'",
        timeout=30,
    )
    await run_ssh(
        f"incus exec {name} -- systemctl daemon-reload && "
        f"incus exec {name} -- systemctl enable cloudflared-tunnel && "
        f"incus exec {name} -- systemctl start cloudflared-tunnel",
        timeout=60,
    )


async def setup_claude_code_web(name: str, password: str, anthropic_key: str) -> None:
    service = (
        "[Unit]\nDescription=Claude Code Web\nAfter=network.target\n\n"
        f"[Service]\nUser=dev\nWorkingDirectory=/home/dev/{name}\n"
        f"Environment=ANTHROPIC_API_KEY={anthropic_key}\n"
        f"ExecStart=/usr/bin/npx claude-code-web --port 8083 --auth {password} --no-open\n"
        "Restart=always\n\n"
        "[Install]\nWantedBy=multi-user.target"
    )
    escaped = service.replace("\\", "\\\\").replace('"', '\\"').replace("'", "'\\''")
    await run_ssh(
        f"incus exec {name} -- bash -c '"
        f"mkdir -p /home/dev/{name} && chown dev:dev /home/dev/{name} && "
        f"printf \"{escaped}\" > /etc/systemd/system/claude-code-web.service && "
        f"systemctl daemon-reload && systemctl enable claude-code-web && systemctl start claude-code-web'",
        timeout=60,
    )


async def get_spark_public_ipv6() -> str:
    """Return the first globally-scoped IPv6 address on the Spark host."""
    out = await run_ssh(
        "ip -6 addr show scope global | grep 'inet6' | awk '{print $2}' | cut -d/ -f1 | head -1",
        timeout=15,
    )
    return out.strip()


async def get_spark_public_ipv4() -> str:
    """Return the public IPv4 address of the Spark host."""
    out = await run_ssh(
        "curl -4 -s --max-time 5 ifconfig.me || ip -4 addr show scope global | grep 'inet ' | awk '{print $2}' | cut -d/ -f1 | head -1",
        timeout=15,
    )
    return out.strip()


async def setup_ssh_forward(name: str, container_ip: str, ssh_port: int) -> None:
    """Install socat on Spark and create a systemd service forwarding ssh_port → container:22."""
    await run_ssh("which socat > /dev/null 2>&1 || sudo apt-get install -y socat", timeout=120)
    service = (
        f"[Unit]\nDescription=SSH forward for {name}\nAfter=network.target\n\n"
        f"[Service]\nExecStart=/usr/bin/socat TCP6-LISTEN:{ssh_port},fork,reuseaddr,ipv6only=0 "
        f"TCP:{container_ip}:22\nRestart=always\n\n"
        f"[Install]\nWantedBy=multi-user.target"
    )
    # Use base64 to avoid shell escaping issues when writing the service file
    import base64 as _b64
    encoded = _b64.b64encode(service.encode()).decode()
    await run_ssh(
        f"echo '{encoded}' | base64 -d | sudo tee /etc/systemd/system/ssh-forward-{name}.service > /dev/null"
        f" && sudo systemctl daemon-reload && sudo systemctl enable --now ssh-forward-{name}",
        timeout=30,
    )


async def teardown_ssh_forward(name: str) -> None:
    """Stop and remove the socat SSH-forward systemd service for this app."""
    await run_ssh(
        f"sudo systemctl stop ssh-forward-{name} 2>/dev/null || true"
        f" && sudo systemctl disable ssh-forward-{name} 2>/dev/null || true"
        f" && sudo rm -f /etc/systemd/system/ssh-forward-{name}.service"
        f" && sudo systemctl daemon-reload",
        timeout=30,
    )


async def install_wetty(name: str) -> None:
    """Install ttyd (apt) and expose a web terminal on port 8085 via nginx."""
    await run_ssh(
        f"incus exec {name} -- bash -c 'DEBIAN_FRONTEND=noninteractive apt-get install -y ttyd'",
        timeout=60,
    )
    service = (
        "[Unit]\nDescription=Web Terminal (ttyd)\nAfter=network.target ssh.service\n\n"
        "[Service]\n"
        "ExecStart=/usr/bin/ttyd -p 7681 -i lo -O -W"
        " -t backgroundColor=#1e1e2e -t foregroundColor=#cdd6f4"
        " -t selectionBackground=#45475a -t cursorColor=#f5e0dc login\n"
        "Restart=always\nRestartSec=5\n\n"
        "[Install]\nWantedBy=multi-user.target"
    )
    import base64 as _b64
    encoded = _b64.b64encode(service.encode()).decode()
    await run_ssh(
        f"incus exec {name} -- bash -c '"
        f"echo {encoded} | base64 -d > /etc/systemd/system/ttyd.service"
        f" && systemctl daemon-reload && systemctl enable --now ttyd'",
        timeout=30,
    )
    # Add nginx vhost proxying port 8085 → ttyd on 8086 with WebSocket support
    nginx_conf = (
        "server {\n"
        "    listen 8085;\n"
        "    location / {\n"
        "        proxy_pass http://127.0.0.1:7681;\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_set_header Upgrade $http_upgrade;\n"
        '        proxy_set_header Connection "upgrade";\n'
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Real-IP $remote_addr;\n"
        "        proxy_read_timeout 3600;\n"
        "    }\n"
        "}\n"
    )
    encoded_nginx = _b64.b64encode(nginx_conf.encode()).decode()
    await run_ssh(
        f"incus exec {name} -- bash -c '"
        f"echo {encoded_nginx} | base64 -d > /etc/nginx/sites-available/ttyd"
        f" && ln -sf /etc/nginx/sites-available/ttyd /etc/nginx/sites-enabled/ttyd"
        f" && nginx -t && systemctl reload nginx'",
        timeout=30,
    )


async def run_ssh_raw(cmd: str, timeout: int = 30) -> tuple[int, str]:
    """Run SSH, returning (returncode, stdout) without raising on non-zero exit."""
    proc = await asyncio.create_subprocess_exec(
        *_ssh_args(), cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, ""
    return proc.returncode or 0, stdout.decode().strip()


async def get_service_statuses(name: str) -> dict:
    services = [
        "xvfb", "xfce", "pulseaudio-selkies", "selkies",
        "nginx", "cloudflared-tunnel", "app-webserver", "claude-code-web", "ttyd",
    ]
    result = {}
    for svc in services:
        try:
            # systemctl is-active: rc=0 active, rc=3 inactive/failed, rc=4 not found
            rc, out = await run_ssh_raw(f'incus exec {name} -- systemctl is-active {svc}')
            if rc == -1:
                result[svc] = "timeout"
            else:
                result[svc] = out or ("active" if rc == 0 else "inactive")
        except Exception:
            result[svc] = "unknown"
    return result


async def restart_service(name: str, service: str) -> None:
    await run_ssh(f'incus exec {name} -- systemctl restart {service}', timeout=60)


async def get_container_stats(name: str) -> dict:
    """Collect basic resource stats from the container via SSH."""
    stats: dict = {}
    try:
        mem = await run_ssh(f"incus exec {name} -- bash -c \"free -m | awk '/^Mem/{{print $2, $3, $4}}'\"", timeout=10)
        parts = mem.split()
        if len(parts) == 3:
            total, used, free = int(parts[0]), int(parts[1]), int(parts[2])
            stats["memory"] = {"total_mb": total, "used_mb": used, "free_mb": free, "pct": round(used / total * 100)}
    except Exception:
        pass
    try:
        cpu = await run_ssh(f"incus exec {name} -- bash -c \"top -bn1 | grep 'Cpu(s)' | awk '{{print $2}}'\"", timeout=10)
        stats["cpu_pct"] = float(cpu.replace("%us,", "").strip()) if cpu else None
    except Exception:
        pass
    try:
        disk = await run_ssh(f"incus exec {name} -- bash -c \"df -m / | awk 'NR==2{{print $2, $3, $5}}'\"", timeout=10)
        parts = disk.split()
        if len(parts) == 3:
            stats["disk"] = {"total_mb": int(parts[0]), "used_mb": int(parts[1]), "pct": parts[2]}
    except Exception:
        pass
    try:
        uptime = await run_ssh(f"incus exec {name} -- uptime -p", timeout=10)
        stats["uptime"] = uptime
    except Exception:
        pass
    try:
        gpu = await run_ssh(f"incus exec {name} -- nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits", timeout=10)
        if gpu:
            rows = []
            for line in gpu.strip().splitlines():
                p = [x.strip() for x in line.split(",")]
                if len(p) == 4:
                    rows.append({"name": p[0], "mem_used_mb": int(p[1]), "mem_total_mb": int(p[2]), "gpu_pct": int(p[3])})
            stats["gpu"] = rows
    except Exception:
        pass
    return stats


async def destroy_container(name: str) -> None:
    await run_ssh(f'incus stop {name} --force && incus delete {name} --force', timeout=120)


async def change_password(name: str, new_password: str) -> None:
    cmds = [
        f"incus exec {name} -- bash -c \"echo 'dev:{new_password}' | chpasswd\"",
        f"incus exec {name} -- bash -c 'htpasswd -bc /etc/nginx/.htpasswd dev {new_password}'",
        f"incus exec {name} -- systemctl restart nginx",
        f"incus exec {name} -- bash -c \"sed -i 's/--auth [^ ]*/--auth {new_password}/' /etc/systemd/system/claude-code-web.service && systemctl daemon-reload && systemctl restart claude-code-web\"",
    ]
    for cmd in cmds:
        await run_ssh(cmd, timeout=60)
