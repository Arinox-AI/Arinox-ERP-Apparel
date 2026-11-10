"""Cortex Operations Control Tower — local database initializer.

This project reads **all** operational data LIVE from KOGO ERP at request time
(`backend/erp.py`). There is therefore **no synthetic seed data** — this module
inserts nothing. It only ensures the small local decision-state tables exist:

* ``risk_state``   — stable id + status per derived risk
* ``action_state`` — approval / modification / execution state per recommendation
* ``audit_log``    — local operator audit trail

Running it standalone is safe and idempotent (``create_all`` is a no-op when the
tables already exist).
"""

from database import init_db


def seed(db=None) -> dict:
    """No-op initializer: create the local tables, insert NO rows.

    Kept for API compatibility with the rest of the harness (`seed(db)`).
    """
    init_db()
    return {"seeded": 0, "synthetic": False,
            "note": "Live ERP integration — no synthetic rows are inserted."}


if __name__ == "__main__":
    init_db()
    print("✅ Local tables initialised — no synthetic rows inserted (data is live from KOGO ERP)")
