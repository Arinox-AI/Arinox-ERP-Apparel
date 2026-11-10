"""Cortex TnA Calendar — Database setup.

Local SQLite holds **only the human overlay** (see ``models.py``). The ERP is
always the master for the order, template and production actuals.

``DB_PATH_OVERRIDE`` is injected by the platform when the project runs as an
installed AI Software (tenant-isolated path); otherwise the DB lives next to the
bundled data files, ``backend/data/{PROJECT_SLUG}.db``.
"""

import os as _os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import PROJECT_SLUG

DB_DIR = Path(__file__).resolve().parent / "data"
DB_DIR.mkdir(exist_ok=True)

_db_override = _os.environ.get("DB_PATH_OVERRIDE")
if _db_override:
    # The TnA store is merged into the Control Tower project, which also injects
    # DB_PATH_OVERRIDE for its own SQLite file. Use a DISTINCT sibling file so the
    # two schemas never share one database (both define an ``audit_log`` table).
    _p = Path(_db_override)
    DB_PATH = _p.with_name("tna_app_" + _p.name)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
else:
    DB_PATH = DB_DIR / f"{PROJECT_SLUG}.db"

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_session() -> Session:
    return SessionLocal()


def _migrate():
    """Idempotent lightweight migrations for SQLite (create_all never adds columns)."""
    from sqlalchemy import text
    with engine.begin() as conn:
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(milestone_overlay)")}
        if "revised_finish" not in existing:
            conn.exec_driver_sql("ALTER TABLE milestone_overlay ADD COLUMN revised_finish VARCHAR(10)")


def init_db():
    from .models import Base
    Base.metadata.create_all(bind=engine)
    _migrate()


if __name__ == "__main__":
    init_db()
    print(f"✅ Database initialized at {DB_PATH}")
