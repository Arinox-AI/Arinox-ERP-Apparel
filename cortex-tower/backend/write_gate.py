"""The one write envelope — cap, audit, rollback — for every Tower → ERP write.

Created 2026-11-04 (D-124). Before this file there were **two** write envelopes
behind **one** mode gate:

* ``writes.py`` — sliced a run at ``MAX_PER_RUN = 60`` and wrote one ``audit_log``
  row per *action*, but no row per record;
* ``intake_exec.py`` — no cap at all (a 3-PO mail times N styles times 6 sizes went
  straight through), no per-record audit, and a ``rollback()`` that counted a 404 as
  *kept*, so ``rollback_intake`` could never clear the ledger it had written.

The create primitive was already shared (``intake_exec.create_checked`` — required
fields, then the duplicate check, then the create). What was not shared is the
envelope around it, and the envelope is where the bugs were. So:

* ``MAX_PER_RUN`` — one number, read from ``config.MAX_WRITES_PER_RUN``;
* :func:`audit` — the one place an ``audit_log`` row is written for a write;
* :class:`Batch` — used by both paths; counts, caps, audits and returns the refs;
* :func:`rollback_refs` / :func:`rollback_names` — one rollback, and it treats an
  already-absent record as *rolled back* rather than as a failure.

Nothing here decides *whether* a write is allowed — that is ``writes.mode_allows``.
This module only makes sure that when a write happens, it is capped, audited and
reversible in exactly one way.
"""

from __future__ import annotations

import json
from typing import Optional

import config
import erp
from models import AuditLogModel

#: The single cap. ``config.MAX_WRITES_PER_RUN`` is env-overridable and defaults to 60.
MAX_PER_RUN: int = int(getattr(config, "MAX_WRITES_PER_RUN", 60) or 60)


def audit(db, action_type: str, action_name: str, description: str,
          actor: str = "Ops Manager", risk_title: Optional[str] = None,
          approved: Optional[str] = None) -> None:
    """Write one ``audit_log`` row. Never raises — an audit failure must not lose a write."""
    if db is None:
        return
    try:
        db.add(AuditLogModel(action_type=action_type, action_name=action_name,
                             description=description[:4000], actor=actor or "Ops Manager",
                             risk_title=(risk_title or None), approved=approved))
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


class Batch:
    """One approval / one action execution. Caps, creates, audits, remembers refs.

    ``limit`` defaults to :data:`MAX_PER_RUN`. A create beyond the limit is refused
    with a note rather than silently truncated, because a truncated order book is a
    worse lie than a refused one.
    """

    def __init__(self, db=None, actor: str = "Ops Manager", label: str = "",
                 limit: Optional[int] = None, audit_records: bool = True):
        self.db = db
        self.actor = actor or "Ops Manager"
        self.label = label or "write"
        self.limit = int(limit if limit is not None else MAX_PER_RUN)
        self.audit_records = audit_records
        self.created: list[dict] = []
        self.errors: list[str] = []
        self.refused = 0

    # ── the one create ──────────────────────────────────────────────────────
    def can_create(self) -> bool:
        """False when this batch has reached the cap (the caller must refuse the write)."""
        if len(self.created) >= self.limit:
            self.refused += 1
            msg = (f"refused: {self.label} reached the cap of {self.limit} records — "
                   f"nothing further created")
            self.errors.append(msg)
            audit(self.db, "write", "cap_reached", msg, actor=self.actor, approved="refused")
            return False
        return True

    def register(self, doctype: str, name: str, step: Optional[str] = None,
                 existed: bool = False) -> None:
        """Record a create that was performed by the caller's own code path."""
        if not doctype or not name:
            return
        ref = {"doctype": doctype, "name": name}
        if step:
            ref["step"] = step
        if not any(r["doctype"] == doctype and r["name"] == name for r in self.created):
            self.created.append(ref)
        if self.audit_records and not existed:
            audit(self.db, "write", f"create:{doctype}",
                  f"{doctype} {name} created as a draft by {self.label}",
                  actor=self.actor, approved="created")

    def create(self, doctype: str, payload: dict, facts: Optional[dict] = None,
               matches: Optional[dict] = None, step: Optional[str] = None) -> tuple:
        """``(ok, doc, err, note)`` — same contract as ``intake_exec.create_checked``."""
        import intake_exec as _ix          # lazy: intake_exec imports this module

        if not self.can_create():
            return False, {}, self.errors[-1], ""

        ok, doc, err, note = _ix.create_checked(doctype, payload, facts, matches)
        if ok and (doc or {}).get("name"):
            self.register(doctype, doc["name"], step=step,
                          existed=bool((doc or {}).get("existing")))
        elif not ok:
            self.errors.append(f"{doctype}: {err}" if doctype else str(err))
        return ok, doc or {}, err, note

    # ── read-back ───────────────────────────────────────────────────────────
    def refs(self) -> list[dict]:
        return list(self.created)

    def names(self, doctype: str) -> list[str]:
        return [r["name"] for r in self.created if r["doctype"] == doctype]

    def summary(self) -> dict:
        return {"created": len(self.created), "errors": len(self.errors),
                "refused": self.refused, "cap": self.limit}


# ────────────────────────────────────────────────────────────────────────────
# One rollback
# ────────────────────────────────────────────────────────────────────────────

def rollback_names(doctype: str, names: list[str], op: str = "create") -> dict:
    """Undo one doctype's created records. Newest first, mint-order reversed.

    ``create`` → delete, ``submit`` → cancel. A record that is **already absent**
    counts as undone: after this change a rollback can clear a ledger written
    against records someone has since deleted in the ERP (2026-11-04).
    """
    done, already, failed = [], [], []
    for name in reversed(names or []):
        if op == "submit":
            ok, err = erp.erp_cancel(doctype, name)
            if ok:
                done.append(name)
            else:
                low = (err or "").lower()
                if "doesnotexist" in low or "not found" in low or "cancelled" in low:
                    already.append(name)
                else:
                    failed.append(f"{name}: {err}")
            continue
        ok, state, err = erp.erp_delete_checked(doctype, name)
        if ok and state == "deleted":
            done.append(name)
        elif ok:
            already.append(name)
        else:
            failed.append(f"{name}: {err}")
    return {"deleted": done, "already_missing": already, "failed": failed,
            "ok": not failed}


def rollback_refs(refs: list[dict]) -> dict:
    """Undo a list of ``{doctype, name, step?}`` refs, newest first.

    Returns ``{"ok", "deleted", "already_missing", "kept"}`` — ``kept`` is the old name
    for "could not remove", kept so existing callers keep their shape.
    """
    killed, already, kept = [], [], []
    for ref in reversed(list(refs or [])):
        if not isinstance(ref, dict):
            continue
        doctype, name = ref.get("doctype"), ref.get("name")
        if not doctype or not name:
            continue
        # undo the links this approval wrote, or the ERP refuses the delete
        # ("Sales Order … is linked with Client Purchase Order …")
        if doctype == "Sales Order":
            try:
                for cpo in (erp.erp_get("Client Purchase Order", fields=["name"],
                                        filters=[["linked_sales_order", "=", name]], limit=0) or []):
                    erp.erp_update("Client Purchase Order", cpo["name"],
                                   {"linked_sales_order": None, "intake_status": "Received"})
            except Exception:
                pass
        ok, state, err = erp.erp_delete_checked(doctype, name)
        if ok and state == "deleted":
            killed.append(f"{doctype} {name}")
        elif ok:
            already.append(f"{doctype} {name}")
        else:
            kept.append(f"{doctype} {name}: {err}")
    return {"ok": not kept, "deleted": killed, "already_missing": already, "kept": kept}


def refs_json(refs: list[dict]) -> str:
    return json.dumps(refs or [], default=str)
