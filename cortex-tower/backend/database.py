"""Cortex Operations Control Tower — Database setup."""

import os as _os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from pathlib import Path
from config import PROJECT_SLUG

DB_DIR = Path(__file__).resolve().parent / "data"
DB_DIR.mkdir(exist_ok=True)

_db_override = _os.environ.get("DB_PATH_OVERRIDE")
if _db_override:
    DB_PATH = Path(_db_override)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
else:
    DB_PATH = DB_DIR / f"{PROJECT_SLUG}.db"

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_session() -> Session:
    return SessionLocal()


def init_db():
    from models import Base
    import models_cx    # noqa: F401  (tables of the Arinox layer)
    import models_deal  # noqa: F401  (deals: inquiry → order)
    import models_costing  # noqa: F401  (the costing sheet the app owns)
    import models_tna  # noqa: F401  (T&A baselines and revisions)
    Base.metadata.create_all(bind=engine)
    _migrate()
    _seal_secrets()


def _seal_secrets():
    """Seal any secret still stored in the clear, on every start (idempotent).

    2026-11-04 (D-125): the ERP key/secret cache and the SMTP password used to be
    plaintext on disk. ``secret_store.migrate`` seals both and is a no-op afterwards.
    """
    try:
        import secret_store
        session = get_session()
        try:
            res = secret_store.migrate(session)
            if "sealed" in (res.get("creds") or "") or "sealed" in (res.get("mail_password") or ""):
                print(f"secrets sealed: {res}", file=__import__("sys").stderr)
        finally:
            session.close()
    except Exception as e:                                   # noqa: BLE001
        print(f"secret migration skipped: {type(e).__name__}", file=__import__("sys").stderr)


def _migrate():
    """Lightweight additive migration.

    ``create_all`` never alters an existing table, so columns added to the models
    after the DB was first created are added here with ``ALTER TABLE ADD COLUMN``.
    Safe to run on every start.
    """
    from sqlalchemy import text
    wanted = {
        "action_state": {
            "result_doctype": "VARCHAR(80)",
            "result_doc": "VARCHAR(140)",
            "result_docs": "TEXT",
            "write_op": "VARCHAR(20)",
            "write_status": "VARCHAR(30)",
            "write_error": "TEXT",
        },
        "order_change": {
            # every record the approval created (JSON list) so it can be rolled back
            "result_refs": "TEXT",
        },
        "mail_attachment": {
            "layout": "TEXT",
        },
        "mail_message": {
            # intake (2026-11-03): the route this mail starts and what was read from it
            "route": "VARCHAR(30)",
            "intake_status": "VARCHAR(20)",
            "needs_ocr": "INTEGER DEFAULT 0",
            "parse_ok": "INTEGER DEFAULT 0",
            # the conversation this mail belongs to (2026-11-03, the chain)
            "chain_id": "INTEGER",
            # how many intake runs one mail opened — it can carry several documents
            "document_count": "INTEGER DEFAULT 0",
            # threads + deals (2026-11-07)
            "thread_key": "VARCHAR(320)",
            "gm_thrid": "VARCHAR(40)",
            "in_reply_to": "VARCHAR(300)",
            "cc_addr": "VARCHAR(600)",
            "direction": "VARCHAR(4) DEFAULT 'in'",
            "deal_id": "INTEGER",
            "label": "VARCHAR(30)",
        },
        "intake_run": {
            "chain_id": "INTEGER",
        },
        "buyer_inquiry": {
            # how the quote-by date was written, and the reading that was used
            "quote_due_raw": "VARCHAR(60)",
            "quote_due_note": "VARCHAR(200)",
        },
        "email_draft": {
            # reply headers — the message this answers, and the thread it must stay in
            "chain_id": "INTEGER",
            "in_reply_to": "VARCHAR(300) DEFAULT ''",
            "references": "TEXT",
            "thread_key": "VARCHAR(320)",
            "deal_id": "INTEGER",
            "cc": "VARCHAR(600)",
        },
        "costing_sheet": {
            # the workbook's header block (2026-11-07: APPAREL_COSTING_DETAILED_REVISED)
            "buyer": "VARCHAR(120)",
            "season": "VARCHAR(60)",
            "factory": "VARCHAR(80)",
            "costing_date": "VARCHAR(20)",
            "vnd_per_usd": "FLOAT",
            "signoffs": "TEXT DEFAULT '{}'",
        },
        "costing_line": {
            # the template slot a line belongs to, and the rule that works its usage out
            "tpl": "VARCHAR(40)",
            "rule": "VARCHAR(20)",
            # the BOM item the line is, so its price is stored against that item (2026-11-07)
            "item_code": "VARCHAR(80)",
            "item_desc": "VARCHAR(200)",
        },
    }
    with engine.begin() as conn:
        for table, cols in wanted.items():
            try:
                existing = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
            except Exception:
                continue
            for col, decl in cols.items():
                if col not in existing:
                    try:
                        # the column name may be an SQL keyword — `references` is, and an
                        # unquoted ALTER failed silently, leaving the thread headers unwritable
                        conn.execute(text(f'ALTER TABLE {table} ADD COLUMN "{col}" {decl}'))
                    except Exception as ex:                            # noqa: BLE001
                        print(f"migrate {table}.{col}: {type(ex).__name__}: {ex}", file=__import__("sys").stderr)


if __name__ == "__main__":
    init_db()
    print(f"✅ Database initialized at {DB_PATH}", file=__import__("sys").stderr)
