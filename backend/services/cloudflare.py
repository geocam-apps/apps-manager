import os
import secrets
import base64
import httpx
from dotenv import load_dotenv

load_dotenv()

API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")
ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
ZONE_ID = os.getenv("CLOUDFLARE_ZONE_ID")
ZONE_NAME = os.getenv("CLOUDFLARE_ZONE_NAME", "geocam.io")

BASE = "https://api.cloudflare.com/client/v4"
ACCOUNT_BASE = f"{BASE}/accounts/{ACCOUNT_ID}"
ZONE_BASE = f"{BASE}/zones/{ZONE_ID}"


def _headers():
    return {"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"}


async def create_tunnel(name: str) -> tuple[str, str]:
    """Returns (tunnel_id, tunnel_token). Terminal ingress included; SSH handled separately."""
    tunnel_secret = base64.b64encode(secrets.token_bytes(32)).decode()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{ACCOUNT_BASE}/cfd_tunnel",
            headers=_headers(),
            json={"name": name, "tunnel_secret": tunnel_secret},
        )
        if r.status_code == 409:
            # Tunnel already exists (left over from a previous failed attempt) — reuse it
            existing = await client.get(
                f"{ACCOUNT_BASE}/cfd_tunnel",
                headers=_headers(),
                params={"name": name, "is_deleted": "false"},
            )
            existing.raise_for_status()
            tunnel_id = existing.json()["result"][0]["id"]
        else:
            r.raise_for_status()
            tunnel_id = r.json()["result"]["id"]

        await client.put(
            f"{ACCOUNT_BASE}/cfd_tunnel/{tunnel_id}/configurations",
            headers=_headers(),
            json={"config": {"ingress": [
                {"hostname": f"{name}-app.{ZONE_NAME}", "service": "http://localhost:8080"},
                {"hostname": f"{name}-desktop.{ZONE_NAME}", "service": "http://localhost:8081", "originRequest": {"noTLSVerify": True, "http2Origins": False}},
                {"hostname": f"{name}-code.{ZONE_NAME}", "service": "http://localhost:8083"},
                {"hostname": f"{name}-terminal.{ZONE_NAME}", "service": "http://localhost:8085", "originRequest": {"noTLSVerify": True, "http2Origins": False}},
                {"hostname": f"{name}-ssh.{ZONE_NAME}", "service": "ssh://localhost:22"},
                {"service": "http_status:404"},
            ]}},
        )

        r = await client.get(f"{ACCOUNT_BASE}/cfd_tunnel/{tunnel_id}/token", headers=_headers())
        r.raise_for_status()
        token = r.json()["result"]

        for sub in [f"{name}-app", f"{name}-desktop", f"{name}-code", f"{name}-terminal"]:
            await client.post(
                f"{ZONE_BASE}/dns_records",
                headers=_headers(),
                json={
                    "type": "CNAME",
                    "name": f"{sub}.{ZONE_NAME}",
                    "content": f"{tunnel_id}.cfargotunnel.com",
                    "proxied": True,
                },
            )

        return tunnel_id, token


async def create_ssh_dns(name: str, spark_ipv6: str, spark_ipv4: str = "") -> None:
    """Create non-proxied A+AAAA records for direct SSH access via socat port forward."""
    async with httpx.AsyncClient(timeout=30) as client:
        # Remove any existing records for this name first
        r = await client.get(
            f"{ZONE_BASE}/dns_records",
            headers=_headers(),
            params={"name": f"{name}-ssh.{ZONE_NAME}"},
        )
        for rec in r.json().get("result", []):
            await client.delete(f"{ZONE_BASE}/dns_records/{rec['id']}", headers=_headers())

        await client.post(
            f"{ZONE_BASE}/dns_records",
            headers=_headers(),
            json={
                "type": "AAAA",
                "name": f"{name}-ssh.{ZONE_NAME}",
                "content": spark_ipv6,
                "proxied": False,
            },
        )
        if spark_ipv4:
            await client.post(
                f"{ZONE_BASE}/dns_records",
                headers=_headers(),
                json={
                    "type": "A",
                    "name": f"{name}-ssh.{ZONE_NAME}",
                    "content": spark_ipv4,
                    "proxied": False,
                },
            )


async def create_spectrum_app(name: str, ssh_port: int, spark_ipv6: str) -> str:
    """Create a Cloudflare Spectrum TCP proxy so SSH works on port 22. Requires Pro+ plan.
    Returns the Spectrum app ID, or raises if the plan doesn't support it."""
    async with httpx.AsyncClient(timeout=30) as client:
        # Remove existing direct AAAA record (Spectrum manages its own DNS)
        r = await client.get(
            f"{ZONE_BASE}/dns_records",
            headers=_headers(),
            params={"name": f"{name}-ssh.{ZONE_NAME}"},
        )
        for rec in r.json().get("result", []):
            await client.delete(f"{ZONE_BASE}/dns_records/{rec['id']}", headers=_headers())

        r = await client.post(
            f"{ZONE_BASE}/spectrum/apps",
            headers=_headers(),
            json={
                "protocol": "tcp/22",
                "dns": {"type": "ADDRESS", "name": f"{name}-ssh.{ZONE_NAME}"},
                "origin_direct": [f"tcp://[{spark_ipv6}]:{ssh_port}"],
                "proxy_protocol": "off",
                "tls": "off",
                "ip_firewall": True,
                "traffic_type": "direct",
            },
        )
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(f"Spectrum not available: {data.get('errors')}")
        return data["result"]["id"]


async def delete_spectrum_app(name: str) -> None:
    """Delete the Spectrum app for the given app name."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{ZONE_BASE}/spectrum/apps", headers=_headers())
        if not r.json().get("success"):
            return
        for app in r.json().get("result", []):
            if app.get("dns", {}).get("name", "").startswith(f"{name}-ssh."):
                await client.delete(f"{ZONE_BASE}/spectrum/apps/{app['id']}", headers=_headers())


async def delete_tunnel(tunnel_id: str, name: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        # Delete tunnel DNS records (app, desktop, code, terminal) + SSH (AAAA or Spectrum)
        for sub in [f"{name}-app", f"{name}-desktop", f"{name}-code", f"{name}-terminal", f"{name}-ssh"]:
            r = await client.get(
                f"{ZONE_BASE}/dns_records",
                headers=_headers(),
                params={"name": f"{sub}.{ZONE_NAME}"},
            )
            for rec in r.json().get("result", []):
                await client.delete(f"{ZONE_BASE}/dns_records/{rec['id']}", headers=_headers())

        # Also try to delete Spectrum app if one exists
        try:
            await delete_spectrum_app(name)
        except Exception:
            pass

        await client.delete(
            f"{ACCOUNT_BASE}/cfd_tunnel/{tunnel_id}",
            headers=_headers(),
            params={"force": "true"},
        )
