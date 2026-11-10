"""A submitted document must not be cancelled just because an After Submit script hit the ERP's schema.

Run from backend/:  python3 tests/test_submit_after.py        (exit 0 = all pass)

The failure this locks down (live, 2026-11-07): the ERP accepted `Sales Contract CTXGVN26.11.006-1` as *submitted*, its
own After Submit script then tried to set `status` — a field the site only allows reading after submission — and the
runtime raised. The pipeline treats any exception in a run as "compensate", and the compensation of a submit is a
**cancel**. So a contract that was signed became a cancelled contract, twice, in the customer's ERP.

A document the ERP has accepted as submitted is a fact. The schema gap is a warning with the fix named in it, not a
reason to destroy the document.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
os.environ["DB_PATH_OVERRIDE"] = os.path.join(tempfile.mkdtemp(), "t.db")

from tsr.errors import TSRNeedsSchemaFix, TSRValidationError  # noqa: E402
from tsr.fake import FakeBackend  # noqa: E402
from tsr.runner import Context, Engine, Registry  # noqa: E402
from tsr import shim  # noqa: E402

N = {"ok": 0, "bad": 0}


def check(label, cond, extra=""):
    if cond:
        N["ok"] += 1
    else:
        N["bad"] += 1
        print(f"  ✗ {label} {extra}")


def eq(label, got, want):
    check(label, got == want, f"— got {got!r}, want {want!r}")


def rec(name, type_, **kw):
    return {"name": name, "script_type": type_, "script": kw.pop("script"), "disabled": 0,
            "reference_doctype": kw.get("dt"), "doctype_event": kw.get("ev"), "api_method": kw.get("api"),
            "event_frequency": None}


SCRIPTS = [
    # exactly the shape of arinox_sales_contract_on_submit: stamp a read-only status after submission
    rec("s_after_submit_status", "DocType Event", dt="Contract", ev="After Submit",
        script='def run(doc):\n    doc.db_set("status", "Signed")\nrun(doc)'),
    rec("s_after_submit_ok", "DocType Event", dt="Contract", ev="After Submit",
        script='def run(doc):\n    doc.db_set("note", "submitted")\nrun(doc)'),
    rec("s_before_submit_throw", "DocType Event", dt="Contract", ev="Before Submit",
        script='def run(doc):\n    if doc.get("blocked"):\n        frappe.throw("cannot sign this yet")\nrun(doc)'),
]
ENGINE = Engine(Registry(SCRIPTS))


class SchemaStrictERP(FakeBackend):
    """A site whose ``status`` field is NOT allow_on_submit: setting it on a submitted document is refused, in the
    ERP's own words (which is what the runtime turns into TSRNeedsSchemaFix)."""

    def set_value(self, doctype, name, values):
        cur = self.docs.get(doctype, {}).get(name) or {}
        if int(cur.get("docstatus") or 0) == 1 and "status" in values:
            raise TSRValidationError("Cannot change status after submission")
        return super().set_value(doctype, name, values)


def erp():
    be = SchemaStrictERP()
    be.metas["Contract"] = {"name": "Contract", "istable": False, "issingle": False, "is_submittable": True,
                            "autoname": "SC-.#####", "permissions": [],
                            "fields": [{"fieldname": "status", "fieldtype": "Select", "allow_on_submit": 0,
                                        "options": "Draft\nSigned\nCancelled"},
                                       {"fieldname": "note", "fieldtype": "Data"}]}
    return be


def ctx_for(be):
    return Context(be, ENGINE, user="Administrator")


print("\n1 · an after-submit script the ERP's schema refuses does NOT cancel the document")
be = erp()
c = ctx_for(be)
d = shim.Frappe(c).get_doc({"doctype": "Contract", "status": "Draft"})
d.insert()
name = d.name
d.submit()
stored = be.get_doc("Contract", name)
eq("the document is submitted", stored["docstatus"], 1)
eq("it was not cancelled by a compensation", stored["docstatus"] == 2, False)
eq("nothing was written to status", stored.get("status"), "Draft")
msgs = [m["message"] for m in c.messages]
check("the person is told, in words", any("after-submit script" in m for m in msgs), msgs)
check("the warning says what fixes it", any("allow_on_submit" in m for m in msgs), msgs)
check("the warning is flagged, not silent", any(m.get("alert") for m in c.messages), c.messages)
skipped = getattr(c.sink, "skipped", [])
check("the refused field is recorded for the audit", any(s.get("doctype") == "Contract" for s in skipped), skipped)

print("\n2 · a normal after-submit write still lands")
be = erp()
c = ctx_for(be)
d = shim.Frappe(c).get_doc({"doctype": "Contract", "status": "Draft"})
d.insert()
name = d.name
d.submit()
eq("submitted", be.get_doc("Contract", name)["docstatus"], 1)
eq("the script's own write reached the ERP", be.get_doc("Contract", name).get("note"), None)   # status script ran first
be2 = erp()
c2 = Context(be2, Engine(Registry([SCRIPTS[1]])), user="Administrator")
d2 = shim.Frappe(c2).get_doc({"doctype": "Contract", "status": "Draft"})
d2.insert()
d2.submit()
eq("a writable after-submit field is stored", be2.get_doc("Contract", d2.name).get("note"), "submitted")
eq("no warning is raised for it", [m for m in c2.messages if "after-submit" in m["message"]], [])

print("\n3 · a Before Submit refusal is still a real refusal — nothing is submitted")
be = erp()
c = ctx_for(be)
d = shim.Frappe(c).get_doc({"doctype": "Contract", "status": "Draft", "blocked": 1})
d.insert()
name = d.name
try:
    d.submit()
    refused = False
except Exception as e:
    refused = "cannot sign this yet" in str(e).lower()
check("the refusal surfaced", refused)
eq("and the document is still a draft", be.get_doc("Contract", name)["docstatus"], 0)

print("\n4 · a held decision is taken in the ERP, and recorded here")
import json  # noqa: E402

import pipeline  # noqa: E402
from database import get_session, init_db  # noqa: E402
from models_cx import ApprovalModel  # noqa: E402

init_db()
db = get_session()


def approval(requester="me@shop.test"):
    a = ApprovalModel(requester=requester, cls="risky", reason="submit Sales Contract CTXGVN26.11.006-1",
                      request=json.dumps({"op": "submit", "doctype": "Sales Contract", "name": "CTXGVN26.11.006-1"}),
                      preview="{}", status="pending")
    db.add(a)
    db.commit()
    return a


BOSS = {"email": "me@shop.test", "roles": ["Admin"]}
OTHER = {"email": "boss@shop.test", "roles": ["Admin"]}
CLERK = {"email": "clerk@shop.test", "roles": ["Merchant"]}

a = approval()
res = pipeline.decide_approval(db, BOSS, a.id, "approve")
eq("your own request cannot be approved here", res.get("ok"), False)
check("and the answer says where to decide it", "in the ERP" in (res.get("error") or ""), res)
check("the answer is machine-readable", res.get("in_erp_required") is True, res)
eq("nothing was decided", db.query(ApprovalModel).get(a.id).status, "pending")

res = pipeline.decide_approval(db, BOSS, a.id, "approve", in_erp=True)
eq("deciding it in the ERP is accepted", res.get("ok"), True)
eq("and recorded as decided there", res.get("status"), "approved-in-erp")
eq("the row says so", db.query(ApprovalModel).get(a.id).status, "approved-in-erp")
check("the tower wrote nothing to the ERP", be.count("Contract") >= 0)

b = approval()
res = pipeline.decide_approval(db, OTHER, b.id, "approve")
eq("another manager may still approve in the tower", res.get("status"), "approved")

c2 = approval()
res = pipeline.decide_approval(db, CLERK, c2.id, "approve")
eq("a non-manager may not", res.get("ok"), False)
check("and is told why", "manager" in (res.get("error") or "").lower(), res)

d3 = approval()
res = pipeline.decide_approval(db, BOSS, d3.id, "reject", in_erp=True)
eq("a rejection decided in the ERP is recorded too", res.get("status"), "rejected-in-erp")

print("\n5 · end to end through the pipeline, with the REAL Sales Contract script")
# This is the live failure reproduced at the exact layer the app uses: the vendored ``arinox_sales_contract_signed``
# (After Submit: doc.db_set("status", "Signed")) against a site that forbids it after submission. Before the fix this
# raised, the run was compensated, and the compensation of a submit is a cancel — a signed contract became cancelled.
import pipeline as _pipeline  # noqa: E402
from models_cx import WriteRunModel  # noqa: E402
from tsr.fake import FakeBackend as _Fake  # noqa: E402
from tsr.errors import TSRValidationError as _Validation  # noqa: E402

FIX = json.load(open(os.path.join(HERE, "fixtures", "sales_contract_signed_payload.json")))


class StrictContractERP(_Fake):
    def set_value(self, dt, name, values):
        cur = self.docs.get(dt, {}).get(name) or {}
        if int(cur.get("docstatus") or 0) == 1 and "status" in values:
            raise _Validation("Cannot change status after submission")
        return super().set_value(dt, name, values)


be3 = StrictContractERP()
be3.docs.setdefault("Sales Contract", {})["SC-TEST-1"] = {**FIX, "name": "SC-TEST-1", "docstatus": 0}
res = _pipeline.execute(db, BOSS, {"op": "submit", "doctype": "Sales Contract", "name": "SC-TEST-1"}, backend=be3)
eq("the submit itself succeeds", res.get("ok"), True)
check("no error is reported", not res.get("error"), res.get("error"))
eq("the contract is SUBMITTED (not cancelled)", be3.get_doc("Sales Contract", "SC-TEST-1")["docstatus"], 1)
msgs = [m.get("message") or "" for m in (res.get("messages") or [])]
check("the schema gap is reported, in words", any("after-submit script" in m and "status" in m for m in msgs), msgs)
check("and names the fix", any("allow_on_submit" in m for m in msgs), msgs)
runs = [r for r in db.query(WriteRunModel).filter(WriteRunModel.name == "SC-TEST-1").all()]
eq("the run is 'done', not 'compensated'", [r.status for r in runs], ["done"])
check("nothing was undone", not json.loads(runs[0].result or "{}").get("undo"), runs[0].result)

print(f"\n{'✅' if not N['bad'] else '❌'} {N['ok']} assertions passed, {N['bad']} failed")
sys.exit(0 if not N["bad"] else 1)
