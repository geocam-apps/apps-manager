import os
from sqlmodel import create_engine, Session, SQLModel
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./apps_manager.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    _migrate()

def _migrate():
    """Add columns that may be missing from existing DB (non-destructive)."""
    import sqlite3
    db_path = DATABASE_URL.replace("sqlite:///", "").lstrip("./")
    if not db_path or not __import__("os").path.exists(db_path):
        db_path = DATABASE_URL.replace("sqlite:///./", "")
    try:
        conn = sqlite3.connect(db_path)
        for stmt in [
            "ALTER TABLE app ADD COLUMN admin_token TEXT",
            "ALTER TABLE app ADD COLUMN ssh_port INTEGER",
        ]:
            try:
                conn.execute(stmt)
                conn.commit()
            except Exception:
                pass
        conn.close()
    except Exception:
        pass

def get_session():
    with Session(engine) as session:
        yield session
