import hashlib
import hmac
import os
import secrets
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from ..auth import get_current_user
from ..database import get_session
from ..models import ApiToken, User

router = APIRouter(prefix="/api/tokens", tags=["tokens"])

INTROSPECT_SECRET = os.getenv("APPS_MANAGER_INTROSPECTION_SECRET", "")

# ---------------------------------------------------------------------------
# Simple in-memory sliding-window rate limiter (30 req / 10 s per IP)
# ---------------------------------------------------------------------------
_rate_buckets: dict = defaultdict(list)
RATE_LIMIT = 30
RATE_WINDOW = 10  # seconds


def _check_rate(ip: str) -> None:
    now = datetime.utcnow().timestamp()
    bucket = _rate_buckets[ip]
    _rate_buckets[ip] = [t for t in bucket if now - t < RATE_WINDOW]
    if len(_rate_buckets[ip]) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    _rate_buckets[ip].append(now)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _generate_token() -> str:
    return "gm_pat_" + secrets.token_urlsafe(32)


def _token_active(tok: ApiToken) -> bool:
    if tok.revoked_at:
        return False
    if tok.expires_at and tok.expires_at < datetime.utcnow():
        return False
    return True


# ---------------------------------------------------------------------------
# User-facing routes (require login)
# ---------------------------------------------------------------------------

class CreateTokenRequest(BaseModel):
    name: str
    expires_at: Optional[datetime] = None


@router.get("")
def list_tokens(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    tokens = session.exec(
        select(ApiToken).where(ApiToken.owner_id == user.id)
    ).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "display": f"{t.token_prefix}…{t.token_suffix}",
            "created_at": t.created_at.isoformat(),
            "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
            "expires_at": t.expires_at.isoformat() if t.expires_at else None,
            "revoked_at": t.revoked_at.isoformat() if t.revoked_at else None,
            "active": _token_active(t),
        }
        for t in tokens
    ]


@router.post("", status_code=201)
def create_token(
    req: CreateTokenRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if not req.name.strip():
        raise HTTPException(400, "Name is required")

    raw = _generate_token()
    tok = ApiToken(
        owner_id=user.id,
        name=req.name.strip(),
        token_hash=_hash_token(raw),
        token_prefix=raw[:14],   # "gm_pat_" + first 7 random chars
        token_suffix=raw[-4:],
        expires_at=req.expires_at,
    )
    session.add(tok)
    session.commit()
    session.refresh(tok)

    # Return the raw token exactly once — never stored or logged
    return {
        "id": tok.id,
        "name": tok.name,
        "token": raw,   # one-time display
        "display": f"{tok.token_prefix}…{tok.token_suffix}",
        "created_at": tok.created_at.isoformat(),
        "expires_at": tok.expires_at.isoformat() if tok.expires_at else None,
    }


@router.delete("/{token_id}")
def revoke_token(
    token_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    tok = session.get(ApiToken, token_id)
    if not tok or tok.owner_id != user.id:
        raise HTTPException(404, "Token not found")
    if tok.revoked_at:
        raise HTTPException(409, "Already revoked")
    tok.revoked_at = datetime.utcnow()
    session.add(tok)
    session.commit()
    return {"revoked": True}


# ---------------------------------------------------------------------------
# Introspection endpoint — called by manager-api, not by browser users
# ---------------------------------------------------------------------------

class IntrospectRequest(BaseModel):
    token: str


@router.post("/introspect")
def introspect(
    req: IntrospectRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    # 1. Authenticate the caller with constant-time comparison
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Unauthorized")
    caller_secret = auth_header[len("Bearer "):]
    if not INTROSPECT_SECRET or not hmac.compare_digest(caller_secret, INTROSPECT_SECRET):
        raise HTTPException(401, "Unauthorized")

    # 2. Rate limit
    client_ip = request.client.host if request.client else "unknown"
    _check_rate(client_ip)

    # 3. Validate token format
    raw = req.token
    if not raw.startswith("gm_pat_"):
        return {"valid": False, "reason": "unknown"}

    # 4. Look up by hash
    tok = session.exec(
        select(ApiToken).where(ApiToken.token_hash == _hash_token(raw))
    ).first()

    if not tok:
        return {"valid": False, "reason": "unknown"}

    if tok.revoked_at:
        return {"valid": False, "reason": "revoked"}

    if tok.expires_at and tok.expires_at < datetime.utcnow():
        return {"valid": False, "reason": "expired"}

    # 5. Touch last_used_at
    tok.last_used_at = datetime.utcnow()
    session.add(tok)
    session.commit()

    owner = session.get(User, tok.owner_id)

    return {
        "valid": True,
        "user": {
            "email": owner.email,
            "name": owner.username,
        },
        "token": {
            "name": tok.name,
            "created_at": tok.created_at.isoformat(),
            "expires_at": tok.expires_at.isoformat() if tok.expires_at else None,
        },
    }
