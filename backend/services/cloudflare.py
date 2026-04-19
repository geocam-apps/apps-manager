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
    """Returns (tunnel_id, tunnel_token)."""
    tunnel_secret = base64.b64encode(secrets.token_bytes(32)).decode()
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{ACCOUNT_BASE}/cfd_tunnel",
            headers=_headers(),
            json={"name": name, "tunnel_secret": tunnel_secret},
        )
        r.raise_for_status()
        tunnel_id = r.json()["result"]["id"]

        # Configure ingress
        await client.put(
            f"{ACCOUNT_BASE}/cfd_tunnel/{tunnel_id}/configurations",
            headers=_headers(),
            json={"config": {"ingress": [
                {"hostname": f"{name}-app.{ZONE_NAME}", "service": "http://localhost:8080"},
                {"hostname": f"{name}-desktop.{ZONE_NAME}", "service": "http://localhost:8081"},
                {"hostname": f"{name}-code.{ZONE_NAME}", "service": "http://localhost:8083"},
                {"hostname": f"{name}-ssh.{ZONE_NAME}", "service": "ssh://localhost:22"},
                {"service": "http_status:404"},
            ]}},
        )

        # Get token
        r = await client.get(
            f"{ACCOUNT_BASE}/cfd_tunnel/{tunnel_id}/token",
            headers=_headers(),
        )
        r.raise_for_status()
        token = r.json()["result"]

        # Create DNS records
        for sub in [f"{name}-app", f"{name}-desktop", f"{name}-code", f"{name}-ssh"]:
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


async def delete_tunnel(tunnel_id: str, name: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        # Delete DNS records
        for sub in [f"{name}-app", f"{name}-desktop", f"{name}-code", f"{name}-ssh"]:
            r = await client.get(
                f"{ZONE_BASE}/dns_records",
                headers=_headers(),
                params={"name": f"{sub}.{ZONE_NAME}"},
            )
            records = r.json().get("result", [])
            for rec in records:
                await client.delete(
                    f"{ZONE_BASE}/dns_records/{rec['id']}",
                    headers=_headers(),
                )

        # Delete tunnel
        await client.delete(
            f"{ACCOUNT_BASE}/cfd_tunnel/{tunnel_id}",
            headers=_headers(),
        )
