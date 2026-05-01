# =============================================================
# database.py  –  Database engine & session factory
# =============================================================
# This file is the "plumbing" layer.  Every other file imports
# from here to talk to the database.
# =============================================================

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# SQLite stores everything in a single local file – no server needed.
# For production you'd swap this URL to PostgreSQL / MySQL.
SQLALCHEMY_DATABASE_URL = "sqlite:///./api/skillswap.db"

# create_engine:  SQLAlchemy's core object that knows HOW to talk
#   to the database (dialect, connection pool, etc.)
# connect_args:   SQLite-specific flag – allows the same connection
#   to be used across multiple threads (needed by FastAPI).
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False}
)

# sessionmaker:  A factory that produces Session objects.
#   autocommit=False  →  we control when changes are saved (safer).
#   autoflush=False   →  we control when pending changes are flushed.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base:  All ORM model classes inherit from this.  SQLAlchemy uses
#   it to track which Python classes map to which database tables.
Base = declarative_base()


# ── FastAPI Dependency ─────────────────────────────────────────
# This generator function is injected into every route that needs
# a database session.  "yield" gives the caller the session;
# the "finally" block guarantees the session is always closed,
# even if an exception is raised mid-request.
def get_db():
    db = SessionLocal()
    try:
        yield db          # ← route handler runs here
    finally:
        db.close()        # ← always runs, prevents connection leaks
