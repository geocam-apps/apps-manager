import os
import secrets
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select
from ..database import get_session
from ..models import User
from ..auth import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

MANAGER_API_URL = os.getenv("MANAGER_API_URL", "https://manager-api-app.geocam.io")


def _validate_geocam_pm(email: str, password: str) -> dict | None:
    """Validate against production.geocam.io via manager-api. Returns the
    upstream user dict on success, None on failure."""
    if not MANAGER_API_URL:
        return None
    try:
        r = httpx.post(
            f"{MANAGER_API_URL}/api/auth/login",
            json={"email": email, "password": password},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        return data.get("user") or data
    except Exception:
        return None


def _ensure_local_user(email: str, upstream: dict, session: Session) -> User:
    """Find or create a local user mirroring an upstream geocam-pm account."""
    user = session.exec(select(User).where(User.email == email)).first()
    if user:
        return user

    # Auto-provision. Username = upstream name or email local-part.
    base_username = (upstream.get("name") or email.split("@", 1)[0]).strip().lower()
    base_username = "".join(c for c in base_username if c.isalnum() or c in "-_") or "user"

    username = base_username
    suffix = 1
    while session.exec(select(User).where(User.username == username)).first():
        suffix += 1
        username = f"{base_username}{suffix}"

    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(secrets.token_urlsafe(32)),  # unusable local pw
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


@router.post("/register", response_model=TokenResponse)
def register(req: RegisterRequest, session: Session = Depends(get_session)):
    if session.exec(select(User).where(User.email == req.email)).first():
        raise HTTPException(400, "Email already registered")
    if session.exec(select(User).where(User.username == req.username)).first():
        raise HTTPException(400, "Username already taken")
    if len(req.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    user = User(
        username=req.username,
        email=req.email,
        hashed_password=hash_password(req.password),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    token = create_access_token(user.id)
    return {
        "access_token": token,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_admin": user.is_admin,
        },
    }


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == req.email)).first()

    # 1. Try local password first
    if user and verify_password(req.password, user.hashed_password):
        if not user.is_active:
            raise HTTPException(403, "Account disabled")
    else:
        # 2. Fall back to production.geocam.io (via manager-api)
        upstream = _validate_geocam_pm(req.email, req.password)
        if not upstream:
            raise HTTPException(401, "Invalid credentials")
        user = _ensure_local_user(req.email, upstream, session)
        if not user.is_active:
            raise HTTPException(403, "Account disabled")

    token = create_access_token(user.id)
    return {
        "access_token": token,
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_admin": user.is_admin,
        },
    }


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
    }
