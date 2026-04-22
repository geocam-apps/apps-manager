from typing import Optional, List
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    is_admin: bool = False
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

    apps: List["App"] = Relationship(back_populates="owner")
    received_shares: List["AppShare"] = Relationship(back_populates="user")
    api_tokens: List["ApiToken"] = Relationship(back_populates="owner")


class App(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    owner_id: int = Field(foreign_key="user.id")
    password: str
    admin_token: Optional[str] = None  # backchannel token for manager→container admin calls
    status: str = "creating"  # creating, running, stopped, error, destroying
    container_ip: Optional[str] = None
    tunnel_id: Optional[str] = None
    github_repo: Optional[str] = None
    error_message: Optional[str] = None
    ssh_port: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    owner: Optional[User] = Relationship(back_populates="apps")
    shares: List["AppShare"] = Relationship(back_populates="app")
    logs: List["JobLog"] = Relationship(back_populates="app")


class AppShare(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    app_id: int = Field(foreign_key="app.id")
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")  # None = everyone
    created_at: datetime = Field(default_factory=datetime.utcnow)

    app: Optional[App] = Relationship(back_populates="shares")
    user: Optional[User] = Relationship(back_populates="received_shares")


class ApiToken(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id")
    name: str
    token_hash: str = Field(index=True)   # SHA-256 hex — never the raw value
    token_prefix: str                      # "gm_pat_" + first 7 random chars
    token_suffix: str                      # last 4 chars
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None

    owner: Optional[User] = Relationship(back_populates="api_tokens")


class JobLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    app_id: int = Field(foreign_key="app.id")
    step: str
    status: str = "running"  # running, done, error
    message: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)

    app: Optional[App] = Relationship(back_populates="logs")
