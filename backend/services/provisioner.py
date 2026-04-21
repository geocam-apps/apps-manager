import os
import asyncio
import random
import secrets
from sqlmodel import Session, select
from ..database import engine
from ..models import App, AppShare, JobLog
from . import container, cloudflare, github
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")

WORD_LIST = [
    "tiger", "castle", "forest", "river", "stone", "cloud", "eagle", "maple",
    "amber", "cedar", "coral", "crane", "daisy", "ember", "fjord", "globe",
    "haven", "ivory", "jade", "kite", "lemon", "moose", "noble", "ocean",
    "pearl", "quest", "raven", "solar", "torch", "ultra", "viper", "whale",
    "xenon", "yield", "zeal", "brave", "crisp", "drift", "flame", "grace",
    "heron", "indie", "joust", "knoll", "lunar", "mirth", "nexus", "orbit",
    "prism", "quill", "roast", "swift", "terra", "unity", "vivid", "wren",
]

# In-memory job queues: app_id -> asyncio.Queue
_job_queues: dict[int, asyncio.Queue] = {}


def generate_password() -> str:
    return f"{random.choice(WORD_LIST)}-{random.choice(WORD_LIST)}"


def get_or_create_queue(app_id: int) -> asyncio.Queue:
    if app_id not in _job_queues:
        _job_queues[app_id] = asyncio.Queue()
    return _job_queues[app_id]


def cleanup_queue(app_id: int) -> None:
    _job_queues.pop(app_id, None)


def _log(session: Session, app_id: int, step: str, status: str, message: str = "") -> None:
    log = JobLog(app_id=app_id, step=step, status=status, message=message)
    session.add(log)
    session.commit()


def _push_progress(app_id: int, step: str, status: str, message: str = "") -> None:
    q = _job_queues.get(app_id)
    if q:
        try:
            q.put_nowait({"step": step, "status": status, "message": message})
        except asyncio.QueueFull:
            pass


def generate_admin_token() -> str:
    return secrets.token_urlsafe(32)


async def provision_app(app_id: int) -> None:
    """Full provisioning pipeline for a new app."""
    with Session(engine) as session:
        app = session.get(App, app_id)
        if not app:
            return
        name = app.name
        password = app.password
        admin_token = app.admin_token or generate_admin_token()
        if not app.admin_token:
            app.admin_token = admin_token
            session.add(app)
            session.commit()

    async def log_step(step: str, status: str, msg: str = ""):
        _push_progress(app_id, step, status, msg)
        with Session(engine) as s:
            _log(s, app_id, step, status, msg)

    try:
        # Verify SSH connectivity before starting
        await log_step("container", "running", "Checking SSH connection to Spark host...")
        await container.run_ssh("echo ok", timeout=20)
        await log_step("container", "running", "Launching container...")
        await container.create_container(name)
        ip = await container.get_container_ip(name)
        with Session(engine) as s:
            app = s.get(App, app_id)
            app.container_ip = ip
            s.add(app)
            s.commit()
        await log_step("container", "done", f"Container running at {ip}")

        # Step 2: Base packages
        await log_step("base", "running", "Installing packages...")
        await container.provision_base(name, password, ANTHROPIC_KEY, admin_token)
        await log_step("base", "done", "Base packages installed")

        # Step 3: Desktop
        await log_step("desktop", "running", "Installing Selkies desktop...")
        await container.provision_desktop(name, password)
        await log_step("desktop", "done", "Desktop environment ready")

        # Step 4: Cloudflare
        await log_step("cloudflare", "running", "Creating tunnel...")
        tunnel_id, token = await cloudflare.create_tunnel(name)
        # Save tunnel_id immediately so destroy can clean it up even if next step fails
        with Session(engine) as s:
            app = s.get(App, app_id)
            app.tunnel_id = tunnel_id
            s.add(app)
            s.commit()
        await container.install_cloudflared(name, token)
        await log_step("cloudflare", "done", f"Tunnel {tunnel_id[:8]}... created")

        # Step 5: GitHub
        await log_step("github", "running", "Creating GitHub repo...")
        repo_url = await github.create_repo(name)
        await github.init_repo_in_container("spark", name, name)
        with Session(engine) as s:
            app = s.get(App, app_id)
            app.github_repo = repo_url
            s.add(app)
            s.commit()
        await log_step("github", "done", f"Repo: {repo_url}")

        # Step 6: Claude Code Web
        await log_step("claude_code_web", "running", "Starting Claude Code Web...")
        await container.setup_claude_code_web(name, password, ANTHROPIC_KEY)
        await log_step("claude_code_web", "done", "Claude Code Web running on port 8083")

        # Step 7: SSH + browser terminal
        await log_step("ssh_terminal", "running", "Setting up SSH access and browser terminal...")
        ssh_port = 22100 + app_id
        with Session(engine) as s:
            app = s.get(App, app_id)
            app.ssh_port = ssh_port
            s.add(app)
            s.commit()
        container_ip_val = None
        with Session(engine) as s:
            app = s.get(App, app_id)
            container_ip_val = app.container_ip
        await container.setup_ssh_forward(name, container_ip_val, ssh_port)
        await container.install_wetty(name)
        await log_step("ssh_terminal", "done", f"SSH via cloudflared tunnel, browser terminal ready")

        # Final: mark running
        with Session(engine) as s:
            app = s.get(App, app_id)
            app.status = "running"
            s.add(app)
            s.commit()
        await log_step("done", "done", "App is ready!")

    except Exception as e:
        import traceback
        error_msg = str(e)[:800]
        tb = traceback.format_exc()[-600:]
        full_error = f"{error_msg}\n\nTraceback:\n{tb}"
        with Session(engine) as s:
            app = s.get(App, app_id)
            app.status = "error"
            app.error_message = error_msg
            s.add(app)
            s.commit()
        _push_progress(app_id, "error", "error", error_msg)
        with Session(engine) as s:
            _log(s, app_id, "error", "error", full_error)
    finally:
        # Send sentinel to close SSE stream
        q = _job_queues.get(app_id)
        if q:
            await q.put(None)


async def destroy_app(app_id: int) -> None:
    with Session(engine) as session:
        app = session.get(App, app_id)
        if not app:
            return
        name = app.name
        tunnel_id = app.tunnel_id
        app.status = "destroying"
        session.add(app)
        session.commit()

    get_or_create_queue(app_id)

    async def log_step(step: str, status: str, msg: str = ""):
        _push_progress(app_id, step, status, msg)
        with Session(engine) as s:
            _log(s, app_id, step, status, msg)

    try:
        await log_step("destroy_container", "running", f"Stopping and deleting container {name}...")
        try:
            await container.destroy_container(name)
            await log_step("destroy_container", "done", "Container removed")
        except Exception as e:
            await log_step("destroy_container", "done", f"Container not found or already gone ({e!s:.80})")

        try:
            await container.teardown_ssh_forward(name)
        except Exception:
            pass

        await log_step("destroy_cloudflare", "running", "Removing Cloudflare tunnel and DNS records...")
        try:
            if tunnel_id:
                await cloudflare.delete_tunnel(tunnel_id, name)
                await log_step("destroy_cloudflare", "done", "Tunnel and DNS records deleted")
            else:
                await log_step("destroy_cloudflare", "done", "No tunnel to delete")
        except Exception as e:
            await log_step("destroy_cloudflare", "error", f"CF cleanup failed (manual cleanup may be needed): {e!s:.120}")

        await log_step("destroy_github", "running", "Deleting GitHub repo...")
        try:
            await github.delete_repo(name)
            await log_step("destroy_github", "done", "GitHub repo deleted")
        except Exception as e:
            await log_step("destroy_github", "done", f"Repo not found or already gone ({e!s:.80})")

        await log_step("destroy_db", "running", "Removing app record...")
        with Session(engine) as s:
            for log in s.exec(select(JobLog).where(JobLog.app_id == app_id)).all():
                s.delete(log)
            for share in s.exec(select(AppShare).where(AppShare.app_id == app_id)).all():
                s.delete(share)
            app_rec = s.get(App, app_id)
            if app_rec:
                s.delete(app_rec)
            s.commit()
        # App is gone from DB — push done to SSE queue only
        _push_progress(app_id, "destroy_db", "done", "App fully destroyed")

    finally:
        q = _job_queues.get(app_id)
        if q:
            await q.put(None)
        cleanup_queue(app_id)
