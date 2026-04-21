import asyncio
import json
import os
import re
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select
from ..database import get_session
from ..models import App, AppShare, User, JobLog
from ..auth import get_current_user, get_current_user_sse, require_admin
from ..services.provisioner import (
    provision_app, destroy_app, generate_password, generate_admin_token,
    get_or_create_queue, cleanup_queue,
)
from ..services.container import get_service_statuses, restart_service, change_password, get_container_stats

router = APIRouter(prefix="/api/apps", tags=["apps"])

ZONE_NAME = os.getenv("CLOUDFLARE_ZONE_NAME", "geocam.io")


def app_urls(name: str) -> dict:
    return {
        "app": f"https://{name}-app.{ZONE_NAME}",
        "desktop": f"https://{name}-desktop.{ZONE_NAME}",
        "code": f"https://{name}-code.{ZONE_NAME}",
        "terminal": f"https://{name}-terminal.{ZONE_NAME}",
        "ssh": f"{name}-ssh.{ZONE_NAME}",
    }


def app_to_dict(app: App, current_user: User) -> dict:
    is_privileged = (
        app.owner_id == current_user.id
        or current_user.is_admin
        or any(s.user_id == current_user.id or s.user_id is None for s in app.shares)
    )
    return {
        "id": app.id,
        "name": app.name,
        "status": app.status,
        "password": app.password if is_privileged else None,
        "admin_token": app.admin_token if is_privileged else None,
        "container_ip": app.container_ip,
        "tunnel_id": app.tunnel_id,
        "github_repo": app.github_repo,
        "error_message": app.error_message,
        "ssh_port": app.ssh_port,
        "ssh_command": f'ssh -o ProxyCommand="cloudflared access ssh --hostname {app.name}-ssh.{ZONE_NAME}" dev@{app.name}-ssh.{ZONE_NAME}',
        "created_at": app.created_at.isoformat(),
        "owner_id": app.owner_id,
        "owner_username": app.owner.username if app.owner else None,
        "urls": app_urls(app.name),
    }


def _get_accessible_apps(session: Session, user: User):
    if user.is_admin:
        return session.exec(select(App)).all()

    owned = session.exec(select(App).where(App.owner_id == user.id)).all()

    # Shared specifically with this user
    shared_ids = session.exec(
        select(AppShare.app_id).where(AppShare.user_id == user.id)
    ).all()

    # Shared with everyone
    public_ids = session.exec(
        select(AppShare.app_id).where(AppShare.user_id == None)  # noqa: E711
    ).all()

    apps = []
    seen = set()
    for app in owned:
        if app.id not in seen:
            apps.append(app)
            seen.add(app.id)
    for app_id in set(shared_ids) | set(public_ids):
        if app_id not in seen:
            app = session.get(App, app_id)
            if app:
                apps.append(app)
                seen.add(app_id)
    return apps


@router.get("")
def list_apps(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    apps = _get_accessible_apps(session, user)
    result: dict = {"my_apps": [], "shared_with_me": [], "shared_with_everyone": []}

    # Public app IDs
    public_ids = set(
        session.exec(select(AppShare.app_id).where(AppShare.user_id == None)).all()  # noqa: E711
    )
    # Specifically shared with user
    my_shared_ids = set(
        session.exec(select(AppShare.app_id).where(AppShare.user_id == user.id)).all()
    )

    for app in apps:
        d = app_to_dict(app, user)
        if app.owner_id == user.id:
            result["my_apps"].append(d)
        elif app.id in public_ids:
            result["shared_with_everyone"].append(d)
        else:
            result["shared_with_me"].append(d)

    return result


class CreateAppRequest(BaseModel):
    name: str


@router.post("")
def create_app(
    req: CreateAppRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if not re.match(r'^[a-z0-9][a-z0-9-]{2,29}$', req.name):
        raise HTTPException(
            400,
            "Name must be 3-30 chars, lowercase alphanumeric and hyphens, starting with a letter/digit",
        )
    existing = session.exec(select(App).where(App.name == req.name)).first()
    if existing:
        raise HTTPException(409, "App name already exists")

    password = generate_password()
    admin_token = generate_admin_token()
    app = App(name=req.name, owner_id=user.id, password=password, admin_token=admin_token, status="creating")
    session.add(app)
    session.commit()
    session.refresh(app)

    get_or_create_queue(app.id)
    background_tasks.add_task(provision_app, app.id)

    return app_to_dict(app, user)


@router.get("/{app_id}")
def get_app(
    app_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    app = session.get(App, app_id)
    if not app:
        raise HTTPException(404, "App not found")
    accessible = _get_accessible_apps(session, user)
    if app not in accessible:
        raise HTTPException(403, "Access denied")
    return app_to_dict(app, user)


@router.delete("/{app_id}")
def delete_app(
    app_id: int,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    app = session.get(App, app_id)
    if not app:
        raise HTTPException(404, "App not found")
    if app.owner_id != user.id and not user.is_admin:
        raise HTTPException(403, "Only owner or admin can delete")
    background_tasks.add_task(destroy_app, app_id)
    return {"message": "Deletion started"}


class ChangePasswordRequest(BaseModel):
    new_password: Optional[str] = None


@router.patch("/{app_id}/password")
async def change_app_password(
    app_id: int,
    req: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    app = session.get(App, app_id)
    if not app:
        raise HTTPException(404, "App not found")
    if app.owner_id != user.id and not user.is_admin:
        raise HTTPException(403, "Only owner or admin can change password")

    new_pw = req.new_password or generate_password()
    await change_password(app.name, new_pw)
    app.password = new_pw
    session.add(app)
    session.commit()
    return {"password": new_pw}


@router.get("/{app_id}/stats")
async def get_app_stats(
    app_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    app = session.get(App, app_id)
    if not app:
        raise HTTPException(404, "App not found")
    accessible = _get_accessible_apps(session, user)
    if app not in accessible:
        raise HTTPException(403, "Access denied")
    if app.status not in ("running", "stopped"):
        return {"error": "Container not running"}
    return await get_container_stats(app.name)


@router.get("/{app_id}/status")
async def get_app_status(
    app_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    app = session.get(App, app_id)
    if not app:
        raise HTTPException(404, "App not found")
    accessible = _get_accessible_apps(session, user)
    if app not in accessible:
        raise HTTPException(403, "Access denied")
    statuses = await get_service_statuses(app.name)
    return {"services": statuses}


@router.post("/{app_id}/restart/{service}")
async def restart_app_service(
    app_id: int,
    service: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    app = session.get(App, app_id)
    if not app:
        raise HTTPException(404, "App not found")
    if app.owner_id != user.id and not user.is_admin:
        raise HTTPException(403, "Only owner or admin can restart services")
    allowed = [
        "xvfb", "openbox", "pulseaudio-selkies", "selkies",
        "nginx", "cloudflared-tunnel", "app-webserver", "claude-code-web",
    ]
    if service not in allowed:
        raise HTTPException(400, f"Unknown service. Allowed: {allowed}")
    await restart_service(app.name, service)
    return {"message": f"Restarted {service}"}


@router.api_route("/{app_id}/admin-proxy/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def admin_proxy(
    app_id: int,
    path: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Forward requests to the container's app-webserver with the admin token header."""
    import httpx
    from fastapi import Request
    app = session.get(App, app_id)
    if not app:
        raise HTTPException(404, "App not found")
    if app.owner_id != user.id and not user.is_admin:
        raise HTTPException(403, "Only owner or admin can use admin proxy")
    if not app.admin_token:
        raise HTTPException(400, "No admin token set for this app")
    if app.status != "running":
        raise HTTPException(400, "App is not running")
    target_url = f"https://{app.name}-app.{ZONE_NAME}/{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.get(target_url, headers={"X-Admin-Token": app.admin_token})
            return {"status_code": r.status_code, "body": r.text[:4096]}
        except Exception as e:
            raise HTTPException(502, f"Proxy error: {e}")


@router.get("/{app_id}/progress")
async def app_progress(
    app_id: int,
    user: User = Depends(get_current_user_sse),
    session: Session = Depends(get_session),
):
    app = session.get(App, app_id)
    if not app:
        raise HTTPException(404, "App not found")
    accessible = _get_accessible_apps(session, user)
    if app not in accessible:
        raise HTTPException(403, "Access denied")

    # Stream existing logs first, then live updates
    logs = session.exec(
        select(JobLog).where(JobLog.app_id == app_id).order_by(JobLog.created_at)
    ).all()

    async def event_stream():
        # Replay existing logs
        for log in logs:
            data = json.dumps({"step": log.step, "status": log.status, "message": log.message})
            yield f"data: {data}\n\n"

        # Stream live updates for active operations
        if app.status in ("creating", "destroying"):
            q = get_or_create_queue(app_id)
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=30)
                    if msg is None:  # sentinel = done
                        break
                    data = json.dumps(msg)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield 'data: {"step":"heartbeat","status":"running","message":"..."}\n\n'

        yield 'data: {"step":"stream_end","status":"done"}\n\n'

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{app_id}/logs")
def get_app_logs(
    app_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    app = session.get(App, app_id)
    if not app:
        raise HTTPException(404, "App not found")
    accessible = _get_accessible_apps(session, user)
    if app not in accessible:
        raise HTTPException(403, "Access denied")
    logs = session.exec(
        select(JobLog).where(JobLog.app_id == app_id).order_by(JobLog.created_at)
    ).all()
    return [
        {
            "step": l.step,
            "status": l.status,
            "message": l.message,
            "created_at": l.created_at.isoformat(),
        }
        for l in logs
    ]


class ShareRequest(BaseModel):
    username: Optional[str] = None  # None = share with everyone


@router.post("/{app_id}/shares")
def add_share(
    app_id: int,
    req: ShareRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    app = session.get(App, app_id)
    if not app:
        raise HTTPException(404, "App not found")
    if app.owner_id != user.id and not user.is_admin:
        raise HTTPException(403, "Only owner or admin can share")

    target_user_id = None
    if req.username:
        target = session.exec(select(User).where(User.username == req.username)).first()
        if not target:
            raise HTTPException(404, f"User '{req.username}' not found")
        target_user_id = target.id

    # Check not already shared
    existing = session.exec(
        select(AppShare).where(AppShare.app_id == app_id, AppShare.user_id == target_user_id)
    ).first()
    if existing:
        raise HTTPException(409, "Already shared")

    share = AppShare(app_id=app_id, user_id=target_user_id)
    session.add(share)
    session.commit()
    session.refresh(share)
    return {"id": share.id, "app_id": app_id, "user_id": target_user_id, "username": req.username}


@router.delete("/{app_id}/shares/{share_id}")
def remove_share(
    app_id: int,
    share_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    share = session.get(AppShare, share_id)
    if not share or share.app_id != app_id:
        raise HTTPException(404, "Share not found")
    app = session.get(App, app_id)
    if app.owner_id != user.id and not user.is_admin:
        raise HTTPException(403, "Only owner or admin can remove shares")
    session.delete(share)
    session.commit()
    return {"message": "Share removed"}


@router.get("/{app_id}/shares")
def list_shares(
    app_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    app = session.get(App, app_id)
    if not app:
        raise HTTPException(404, "App not found")
    if app.owner_id != user.id and not user.is_admin:
        raise HTTPException(403, "Only owner or admin can view shares")
    shares = session.exec(select(AppShare).where(AppShare.app_id == app_id)).all()
    result = []
    for s in shares:
        result.append({
            "id": s.id,
            "user_id": s.user_id,
            "username": s.user.username if s.user else None,
            "type": "everyone" if s.user_id is None else "user",
        })
    return result


# Admin endpoints
@router.get("/admin/all")
def admin_list_all(
    session: Session = Depends(get_session),
    user: User = Depends(require_admin),
):
    apps = session.exec(select(App)).all()
    return [app_to_dict(a, user) for a in apps]


@router.get("/admin/users")
def admin_list_users(
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    users = session.exec(select(User)).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "is_admin": u.is_admin,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]


class UpdateUserRequest(BaseModel):
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None


@router.patch("/admin/users/{user_id}")
def admin_update_user(
    user_id: int,
    req: UpdateUserRequest,
    session: Session = Depends(get_session),
    _: User = Depends(require_admin),
):
    target = session.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    if req.is_admin is not None:
        target.is_admin = req.is_admin
    if req.is_active is not None:
        target.is_active = req.is_active
    session.add(target)
    session.commit()
    return {
        "id": target.id,
        "username": target.username,
        "is_admin": target.is_admin,
        "is_active": target.is_active,
    }
