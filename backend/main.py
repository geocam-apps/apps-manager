import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqladmin import Admin
from sqlmodel import Session, select
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
from .database import engine, create_db_and_tables
from .models import User
from .auth import hash_password
from .admin import UserAdmin, AppAdmin, AppShareAdmin, JobLogAdmin
from .routers import auth, apps

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    # Create default admin user
    with Session(engine) as session:
        admin_exists = session.exec(select(User).where(User.username == "admin")).first()
        if not admin_exists:
            admin_pass = os.getenv("ADMIN_PASSWORD", "sage-birch")
            admin_email = os.getenv("ADMIN_EMAIL", "admin@geocam.io")
            admin_user = User(
                username="admin",
                email=admin_email,
                hashed_password=hash_password(admin_pass),
                is_admin=True,
            )
            session.add(admin_user)
            session.commit()
            print(f"Created admin user (email: {admin_email}, password: {admin_pass})")
    yield


app = FastAPI(title="Apps Manager", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "session-secret-key"))

# SQLAdmin
admin = Admin(app, engine, title="Apps Manager Admin")
admin.add_view(UserAdmin)
admin.add_view(AppAdmin)
admin.add_view(AppShareAdmin)
admin.add_view(JobLogAdmin)

# API routers
app.include_router(auth.router)
app.include_router(apps.router)

# Serve frontend
FRONTEND_DIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.exists(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        index = os.path.join(FRONTEND_DIST, "index.html")
        return FileResponse(index)
else:
    @app.get("/")
    def root():
        return {"message": "Frontend not built. Run build.sh first.", "admin": "/admin"}
