"""Cortex TnA Calendar — database bootstrap.

Nothing to seed: the ERP is the master for the order, template and production
actuals, and the bundled JSON files ship the template + holiday calendars. This
script only creates the (empty) overlay tables so the app can start.
"""

import json

from .database import get_session, init_db


def seed(db):
    from .models import ActionLogModel, AuditLogModel, MilestoneOverlayModel
    counts = {
        "milestone_overlay": db.query(MilestoneOverlayModel).count(),
        "action_log": db.query(ActionLogModel).count(),
        "audit_log": db.query(AuditLogModel).count(),
    }
    return counts


if __name__ == "__main__":
    import database
    init_db()
    db = get_session()
    try:
        print(json.dumps({"initialized": True, "db": str(database.DB_PATH),
                          "counts": seed(db)}, indent=2))
    finally:
        db.close()
