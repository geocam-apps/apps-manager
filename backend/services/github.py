import os
import httpx
from dotenv import load_dotenv

load_dotenv()

GITHUB_PAT = os.getenv("GITHUB_PAT")
GITHUB_ORG = os.getenv("GITHUB_ORG", "geocam-apps")
GITHUB_TEMPLATE_REPO = os.getenv("GITHUB_TEMPLATE_REPO", "geocam-apps/base_template")


def _headers():
    return {
        "Authorization": f"token {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json",
    }


async def create_repo(name: str) -> str:
    """Create a new GitHub repo and return its URL."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"https://api.github.com/orgs/{GITHUB_ORG}/repos",
            headers=_headers(),
            json={"name": name, "private": False, "auto_init": False},
        )
        if r.status_code not in (201, 422):  # 422 = already exists
            r.raise_for_status()
        return f"https://github.com/{GITHUB_ORG}/{name}"


async def init_repo_in_container(spark_host: str, container_name: str, repo_name: str) -> None:
    """Download template and push to new repo inside the container."""
    from .container import run_ssh

    cmds = [
        (
            f"incus exec {container_name} -- su - dev -c \""
            f"echo 'https://x-access-token:{GITHUB_PAT}@github.com' > ~/.git-credentials && "
            f"git config --global credential.helper store && "
            f"git config --global user.email 'dev@geocam.io' && "
            f"git config --global user.name 'dev'\""
        ),
        (
            f"incus exec {container_name} -- su - dev -c \""
            f"mkdir -p /home/dev/{repo_name} && "
            f"cd /home/dev/{repo_name} && "
            f"git init && "
            f"git remote add origin https://github.com/{GITHUB_ORG}/{repo_name}.git\""
        ),
        (
            f"incus exec {container_name} -- su - dev -c \""
            f"cd /home/dev/{repo_name} && "
            f"curl -L -H 'Authorization: token {GITHUB_PAT}' "
            f"https://api.github.com/repos/{GITHUB_TEMPLATE_REPO}/tarball/main "
            f"-o /tmp/template.tar.gz && "
            f"tar xzf /tmp/template.tar.gz --strip-components=1 && "
            f"rm /tmp/template.tar.gz && "
            f"git add -A && "
            f"git commit -m 'Initial commit from template' && "
            f"git branch -M main && "
            f"git push -u origin main\""
        ),
    ]
    for cmd in cmds:
        try:
            await run_ssh(cmd, timeout=120)
        except Exception:
            pass


async def delete_repo(name: str) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        await client.delete(
            f"https://api.github.com/repos/{GITHUB_ORG}/{name}",
            headers=_headers(),
        )
