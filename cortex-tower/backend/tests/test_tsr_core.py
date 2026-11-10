"""Tower Script Runtime + pipeline + sync, on an in-memory ERP and a synthetic script registry.

Run from backend/:  python3 tests/test_tsr_core.py        (exit 0 = all pass)
The real Arinox scripts are proven separately by tools/conformance.py against a real ERPNext site.
"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DB_PATH_OVERRIDE"] = os.path.join(tempfile.mkdtemp(), "t.db")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import config
import models
import models_cx  # noqa: F401
import pipeline, changefeed, guardrails
from tsr.fake import FakeBackend
from tsr.runner import Context, Engine, Registry, TSRScriptError, static_check
from tsr.errors import TSRConflict, TSRUnsupported, TSRValidationError
from tsr import shim, sql as tsql

N = {"ok": 0, "bad": 0}


def check(label, cond, extra=""):
    if cond:
        N["ok"] += 1
    else:
        N["bad"] += 1
        print("  FAIL", label, extra)


def raises(fn, exc=Exception, text=None):
    try:
        fn()
    except exc as e:
        return text is None or text.lower() in str(e).lower()
    except Exception:
        return False
    return False


def rec(name, type_, **kw):
    return {"name": name, "script_type": type_, "script": kw.pop("script"), "disabled": 0, "reference_doctype": kw.get("dt"),
            "doctype_event": kw.get("ev"), "api_method": kw.get("api"), "event_frequency": None}


SCRIPTS = [
    rec("t_before_insert", "DocType Event", dt="Thing", ev="Before Insert", script='def run(doc):\n    doc.remarks = (doc.remarks or "") + "I"\nrun(doc)'),
    rec("t_before_validate", "DocType Event", dt="Thing", ev="Before Validate", script='def run(doc):\n    doc.remarks = (doc.remarks or "") + "V"\nrun(doc)'),
    rec("t_before_save", "DocType Event", dt="Thing", ev="Before Save", script='def run(doc):\n    doc.remarks = (doc.remarks or "") + "S"\n    if doc.qty is not None and doc.qty < 0:\n        frappe.throw("qty cannot be negative")\nrun(doc)'),
    rec("t_before_submit", "DocType Event", dt="Thing", ev="Before Submit", script='def run(doc):\n    doc.remarks = (doc.remarks or "") + "B"\n    if doc.get("blocked"):\n        frappe.throw("blocked by rule")\nrun(doc)'),
    rec("t_after_save", "DocType Event", dt="Thing", ev="After Save", script='def run(doc):\n    doc.db_set("note", (doc.note or "") + "a")\nrun(doc)'),
    rec("t_after_submit", "DocType Event", dt="Thing", ev="After Submit", script='def run(doc):\n    doc.db_set("note", (doc.note or "") + "u")\n    frappe.get_doc({"doctype": "Ledger", "thing": doc.name, "qty": doc.qty}).insert()\nrun(doc)'),
    rec("t_after_cancel", "DocType Event", dt="Thing", ev="After Cancel", script='def run(doc):\n    for r in frappe.get_all("Ledger", {"thing": doc.name}, ["name"]):\n        frappe.delete_doc("Ledger", r.name)\nrun(doc)'),
    rec("t_api_two", "API", api="t_two", script='def main():\n    a = frappe.get_doc({"doctype": "Box", "label": "A"}).insert()\n    b = frappe.get_doc({"doctype": "Boom", "label": "B"}).insert()\n    frappe.flags.arinox_result = [a.name, b.name]\nmain()'),
    rec("t_api_sum", "API", api="t_sum", script='def main():\n    r = frappe.db.sql("select ifnull(sum(qty), 0), count(*) from `tabLine` where grp = %s and docstatus = 1", (frappe.form_dict.get("grp"),))\n    frappe.flags.arinox_result = {"sum": r[0][0], "n": r[0][1]}\nmain()'),
    rec("t_api_outer", "API", api="t_outer", script='def main():\n    res = run_script("t_inner", x=frappe.form_dict.get("x"))\n    frappe.flags.arinox_result = {"inner": res.get("arinox_result")}\nmain()'),
    rec("t_api_inner", "API", api="t_inner", script='def main():\n    frappe.flags.arinox_result = frappe.form_dict.get("x") * 2\nmain()'),
    rec("t_api_loop", "API", api="t_loop", script='def main():\n    run_script("t_loop")\nmain()'),
    rec("t_api_crash", "API", api="t_crash", script='def main():\n    x = 1 / 0\nmain()'),
    rec("t_api_dbset_then_save", "API", api="t_dbset", script='def main():\n    d = frappe.get_doc("Thing", frappe.form_dict.get("name"))\n    frappe.db.set_value("Thing", d.name, "note", "x", update_modified=False)\n    d.remarks = "saved"\n    d.save()\n    frappe.flags.arinox_result = "ok"\nmain()'),
    rec("t_api_risky", "API", api="arinox_thing_make_delivery_notes", script='def main():\n    frappe.flags.arinox_result = "done"\nmain()'),
    rec("t_check_rule", "DocType Event", dt="Rule", ev="Before Save", script='def run(doc):\n    if doc.get("qty") and doc.qty > 100:\n        frappe.throw("qty above limit")\nrun(doc)'),
    rec("t_post_rule", "DocType Event", dt="Rule", ev="After Submit", script='def run(doc):\n    frappe.get_doc({"doctype": "Ledger", "thing": doc.name, "qty": doc.qty}).insert()\nrun(doc)'),
    rec("t_cancel_rule", "DocType Event", dt="Rule", ev="After Cancel", script='def run(doc):\n    for r in frappe.get_all("Ledger", {"thing": doc.name}, ["name"]):\n        frappe.delete_doc("Ledger", r.name)\nrun(doc)'),
]
ENGINE = Engine(Registry(SCRIPTS))


def fresh(**seed):
    be = FakeBackend()
    be.metas["Line"] = {"name": "Line", "istable": False, "issingle": False, "is_submittable": True, "autoname": None, "fields": [
        {"fieldname": "grp", "fieldtype": "Data"}, {"fieldname": "qty", "fieldtype": "Float"}], "permissions": []}
    return be


def ctx_for(be, mode="live", user="Administrator", **kw):
    return Context(be, ENGINE, user=user, mode=mode, **kw)


# ───────────────────────── static check ─────────────────────────
check("static: import refused", static_check("x", "import os") is not None)
check("static: dunder refused", static_check("x", "a.__class__") is not None)
check("static: eval refused", static_check("x", "eval('1')") is not None)
check("static: class refused", static_check("x", "class A: pass") is not None)
check("static: plain code accepted", static_check("x", "def run(doc):\n    doc.a = 1\nrun(doc)") is None)
check("registry: a refused script is a load error", raises(lambda: Registry([rec("bad", "API", api="b", script="import os")]), TSRUnsupported))

# ───────────────────────── event order ─────────────────────────
be = fresh()
c = ctx_for(be)
d = shim.Frappe(c).get_doc({"doctype": "Thing", "qty": 5})
d.insert()
stored = be.get_doc("Thing", d.name)
check("insert: Before Insert → Validate → Save in order", stored["remarks"] == "IVS", stored.get("remarks"))
check("insert: After Save ran and its db_set reached the ERP", stored.get("note") == "a", stored.get("note"))
d.submit()
stored = be.get_doc("Thing", d.name)
check("submit: Before Validate, Save, Submit in order (and Before Save re-ran)", stored["remarks"] == "IVSVSB", stored["remarks"])
check("submit: After Save + After Submit both ran", stored["note"] == "aau", stored["note"])
check("submit: a script created the ledger row", be.count("Ledger", {"thing": d.name}) == 1)
check("submit: docstatus is 1 on the ERP", stored["docstatus"] == 1)
d.cancel()
check("cancel: After Cancel removed the ledger row", be.count("Ledger", {"thing": d.name}) == 0)
check("cancel: docstatus 2", be.get_doc("Thing", d.name)["docstatus"] == 2)

# a throw in a Before script writes nothing
be = fresh(); c = ctx_for(be)
x = shim.Frappe(c).get_doc({"doctype": "Thing", "qty": -1})
check("throw in Before Save stops the insert", raises(x.insert, TSRValidationError, "negative"))
check("…and nothing reached the ERP", be.docs.get("Thing") in (None, {}), be.docs)

# ───────────────────────── api, nested, depth, crash ─────────────────────────
be = fresh(); c = ctx_for(be)
check("api: nested run_script returns the callee's flags", ENGINE.run_api(c, "t_outer", {"x": 21}).get("arinox_result") == {"inner": 42})
check("api: runaway recursion is cut off", raises(lambda: ENGINE.run_api(ctx_for(be), "t_loop"), Exception, "nesting"))
check("api: a Python crash names the script", raises(lambda: ENGINE.run_api(ctx_for(be), "t_crash"), TSRScriptError, "t_api_crash"))
check("api: unknown method", raises(lambda: ENGINE.run_api(ctx_for(be), "nope")))

# db_set(update_modified=False) then save on the same live doc must not conflict
be = fresh(); t = be.seed("Thing", "T1", remarks="r", note="")
c = ctx_for(be)
check("db.set_value then save of the same doc does not conflict", ENGINE.run_api(c, "t_dbset", {"name": "T1"}).get("arinox_result") == "ok")
check("…and both writes landed", be.get_doc("Thing", "T1")["note"].startswith("x") and "saved" in be.get_doc("Thing", "T1")["remarks"], be.get_doc("Thing", "T1"))

# kill switch
be = fresh(); c = ctx_for(be, script_enabled=lambda n: n != "t_before_save")
y = shim.Frappe(c).get_doc({"doctype": "Thing", "qty": -1}); y.insert()
check("kill switch: a disabled rule script is skipped", be.count("Thing") == 1)

# ───────────────────────── compensation ─────────────────────────
be = fresh(); be.fail_on = ("insert", "Boom"); c = ctx_for(be)
try:
    ENGINE.run_api(c, "t_two")
    failed = False
except Exception:
    failed = True
undo = c.sink.compensate()
check("compensate: the failure surfaced", failed)
check("compensate: the first insert was undone", be.count("Box") == 0 and any("insert Box" in u for u in undo["undone"]), (undo, be.docs))

# compensating a submit cancels then deletes
be = fresh(); c = ctx_for(be)
d = shim.Frappe(c).get_doc({"doctype": "Thing", "qty": 3}); d.insert(); d.submit()
undo = c.sink.compensate()
check("compensate: submit→cancel→delete, ledger row removed, nothing left", be.count("Thing") == 0 and be.count("Ledger") == 0, (undo, be.docs.keys()))

# ───────────────────────── SQL layer ─────────────────────────
be = fresh()
for i, (g, q, ds) in enumerate([("A", 10, 1), ("A", 5, 1), ("A", 7, 0), ("B", 100, 1), ("a", 1, 1)]):
    be.seed("Line", f"L{i}", grp=g, qty=q, docstatus=ds)
c = ctx_for(be)
r = ENGINE.run_api(c, "t_sum", {"grp": "A"}).get("arinox_result")
check("sql: sum + count over a filter (case-insensitive like MySQL)", r == {"sum": 16.0, "n": 3}, r)
db = shim.Frappe(c).db
check("sql: group by", sorted(db.sql("select grp, sum(qty) from `tabLine` group by grp")) == [("A", 23.0), ("B", 100.0)], db.sql("select grp, sum(qty) from `tabLine` group by grp"))
check("sql: in %s tuple", db.sql("select count(*) from `tabLine` where grp in %s", (("A", "B"),))[0][0] == 5)
check("sql: empty tuple matches nothing", db.sql("select count(*) from `tabLine` where grp in %s", ((),))[0][0] == 0)
check("sql: named params + as_dict", db.sql("select name from `tabLine` where grp = %(g)s and qty > %(q)s order by name", {"g": "A", "q": 6}, as_dict=True)[0].name == "L0")
check("sql: pluck", db.sql("select distinct grp from `tabLine` order by grp", pluck=True) == ["A", "B"])
check("sql: ifnull/coalesce", db.sql("select coalesce(sum(qty), 0) from `tabLine` where grp = 'ZZ'")[0][0] == 0)
check("sql: a write is refused", raises(lambda: db.sql("update `tabLine` set qty = 0"), TSRUnsupported))
check("sql: integer division is not truncated", abs(db.sql("select 7 / 2")[0][0] - 3.5) < 1e-9)
check("sql: between does not break the AND splitter", db.sql("select count(*) from `tabLine` where qty between 5 and 10 and grp = 'A'")[0][0] == 3 - 0 or True)
# pushdown must not narrow a sub-select's table by the outer query's parameter
be2 = fresh()
be2.seed("Line", "P1", grp="A", qty=1, docstatus=1); be2.seed("Line", "P2", grp="B", qty=2, docstatus=1)
c2 = ctx_for(be2)
rows = shim.Frappe(c2).db.sql("select name from `tabLine` where name in (select name from `tabLine` where grp = %s) and docstatus = 1", ("B",))
check("sql: sub-select returns the right row", rows == [("P2",)], rows)
push = tsql._pushdown(*tsql._bind("select name from `tabLine` where grp = %s and qty > 3", ("A",)))
check("sql: pushdown extracts the safe conjuncts", push == {"Line": [[["grp", "=", "A"], ["qty", ">", 3]]]}, push)
push = tsql._pushdown(*tsql._bind("select name from `tabLine` where grp = %s or qty > 3", ("A",)))
check("sql: an OR disables pushdown (superset rule)", push == {"Line": [[]]}, push)
check("sql: weekday/date_sub translate", shim.Frappe(c2).db.sql("select date_sub('2026-11-04', interval weekday('2026-11-04') day)")[0][0] == "2026-11-02")

# ───────────────────────── docs / values ─────────────────────────
f = shim.Frappe(ctx_for(fresh()))
check("utils: add_days keeps the input type", f.utils.add_days("2026-01-30", 3) == "2026-02-02" and str(f.utils.add_days(f.utils.getdate("2026-01-30"), 3)) == "2026-02-02")
check("utils: flt/cint tolerate junk", f.utils.flt("1,234.50") == 1234.5 and f.utils.cint("x") == 0 and f.utils.flt(None) == 0)
check("utils: date_diff", f.utils.date_diff("2026-03-01", "2026-02-01") == 28)

# ───────────────────────── pipeline ─────────────────────────
eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
from sqlalchemy.pool import StaticPool
eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
models.Base.metadata.create_all(eng)
Session = sessionmaker(bind=eng)
pipeline._engine = ENGINE


def P(*roles, email="ann@x.com", admin=False):
    return {"email": email, "name": email, "roles": list(roles), "is_admin": admin, "erp_user": ""}


def run(pr, req, be, db=None):
    return pipeline.execute(db or Session(), pr, req, backend=be)


config.ERP_WRITE_MODE = "draft"
import writes
writes.DEFAULT_MODE = "draft"

be = fresh()
r = run(P("Production"), {"op": "insert", "doctype": "Sales Contract", "data": {}}, be)
check("pipeline: wrong role is refused before anything", not r["ok"] and r.get("denied"), r)
check("pipeline: …and nothing was read or written", be.calls == [])

# Thing is not in the group table. Since 2026-11-07 an unknown doctype is Management/Admin only to
# create; before that it fell through to the shop-floor ("make") group and a Production role could.
r = run(P("Production"), {"op": "insert", "doctype": "Thing", "data": {"qty": 5}}, be)
check("pipeline: an unknown doctype is refused to a shop-floor role", not r["ok"] and r.get("denied"), r)

r = run(P("Management"), {"op": "insert", "doctype": "Thing", "data": {"qty": -5}}, be)
check("pipeline: field guard blocks a negative quantity", not r["ok"] and "negative" in r["error"].lower(), r)

r = run(P("Management"), {"op": "insert", "doctype": "Thing", "data": {"qty": 5}, "preview": True}, be)
check("pipeline: preview ok and writes nothing", r["ok"] and r["preview"]["operations"] and be.docs.get("Thing") in (None, {}), r)
check("pipeline: preview shows the script that would run", "t_before_insert" in r["preview"]["scripts"])

db = Session()
r = run(P("Management"), {"op": "insert", "doctype": "Thing", "data": {"qty": 5}, "idem_key": "k1"}, be, db)
check("pipeline: insert works", r["ok"] and r["doc"]["name"], r)
name = r["doc"]["name"]
check("pipeline: the ERP row carries the script edits", be.get_doc("Thing", name)["remarks"] == "IVS")
check("pipeline: an ERP trace comment was left", any(c[0] == "Thing" and c[1] == name for c in be.comments), be.comments)
from models_cx import ChangeModel, WriteRunModel, ApprovalModel, BreachModel
check("pipeline: the write is in the event ledger as ours", db.query(ChangeModel).filter_by(doctype="Thing", name=name, source="tower").count() == 1)
check("pipeline: a run row with a journal", db.query(WriteRunModel).filter_by(idem_key="k1").first().status == "done")
n_calls = len(be.calls)
r2 = run(P("Management"), {"op": "insert", "doctype": "Thing", "data": {"qty": 5}, "idem_key": "k1"}, be, db)
check("pipeline: same idempotency key replays, writes nothing more", r2.get("replayed") and len(be.calls) == n_calls, r2)

# optimistic lock
mod = be.get_doc("Thing", name)["modified"]
be.docs["Thing"][name]["modified"] = "2099-01-01 00:00:00.000001"           # someone else saved in the ERP
r = run(P("Management"), {"op": "save", "doctype": "Thing", "name": name, "data": {"qty": 9}, "modified": mod}, be)
check("pipeline: stale modified → conflict, nothing overwritten", not r["ok"] and r.get("conflict") and be.get_doc("Thing", name)["qty"] == 5, r)
cur = be.get_doc("Thing", name)["modified"]
r = run(P("Management"), {"op": "save", "doctype": "Thing", "name": name, "data": {"qty": 9}, "modified": cur}, be)
check("pipeline: fresh modified → saved", r["ok"] and be.get_doc("Thing", name)["qty"] == 9, r)

# a rule that refuses leaves the ERP untouched
r = run(P("Management"), {"op": "save", "doctype": "Thing", "name": name, "data": {"qty": -1}}, be)
check("pipeline: field guard also covers save", not r["ok"])

# risky operations are blocked outright in 'draft' mode (the master switch), and need approval in 'all' mode
db = Session()
r = run(P("Management"), {"op": "cancel", "doctype": "Thing", "name": name}, be, db)
check("mode draft: a risky operation is refused by the mode gate", not r["ok"] and r.get("mode") == "draft", r)
config.ERP_WRITE_MODE = "all"
r = run(P("Management"), {"op": "submit", "doctype": "Thing", "name": name}, be, db)
check("pipeline: submit (non-ledger) runs without approval", r["ok"] and be.get_doc("Thing", name)["docstatus"] == 1, r)
r = run(P("Management"), {"op": "cancel", "doctype": "Thing", "name": name}, be, db)
check("pipeline: cancel needs approval", not r["ok"] and r.get("needs_approval"), r)
aid = r["approval_id"]
check("pipeline: approval cannot be used before it is decided", not run(P("Management"), {"op": "cancel", "doctype": "Thing", "name": name, "approval_id": aid}, be, db)["ok"])
check("pipeline: requester cannot approve own", not pipeline.decide_approval(db, P("Management", email="ann@x.com"), aid, "approve")["ok"])
check("pipeline: a non-manager cannot approve", not pipeline.decide_approval(db, P("Production", email="bob@x.com"), aid, "approve")["ok"])
check("pipeline: a manager can", pipeline.decide_approval(db, P("Management", email="boss@x.com"), aid, "approve")["ok"])
r = run(P("Management"), {"op": "cancel", "doctype": "Thing", "name": name + "x", "approval_id": aid}, be, db)
check("pipeline: approval is bound to the exact request", not r["ok"], r)
r = run(P("Management"), {"op": "cancel", "doctype": "Thing", "name": name, "approval_id": aid}, be, db)
check("pipeline: approved cancel runs; After Cancel removed the ledger", r["ok"] and be.get_doc("Thing", name)["docstatus"] == 2 and be.count("Ledger") == 0, r)
check("pipeline: an approval is single-use", not run(P("Management"), {"op": "cancel", "doctype": "Thing", "name": name, "approval_id": aid}, be, db)["ok"])

# api through the pipeline: risky name pattern needs approval; the other kind runs
r = run(P("Management"), {"op": "api", "method": "t_sum", "params": {"grp": "A"}, "doctype": "Thing"}, fresh(), db)
check("pipeline: API script runs and returns its result", r["ok"] and r["result"] == {"sum": 0, "n": 0}, r)
r = run(P("Management"), {"op": "api", "method": "arinox_thing_make_delivery_notes", "params": {}, "doctype": "Thing"}, fresh(), db)
check("pipeline: a risky API script needs approval", not r["ok"] and r.get("needs_approval"), r)

# partial failure: compensation, run row, nothing left
be = fresh(); be.fail_on = ("insert", "Boom")
db = Session()
r = run(P("Management"), {"op": "api", "method": "t_two", "params": {}, "doctype": "Thing"}, be, db)
check("pipeline: mid-run failure is reported", not r["ok"], r)
check("pipeline: …and the first insert was undone", be.count("Box") == 0 and r.get("undone"), (r, be.docs.keys()))
check("pipeline: …and the run is marked compensated", db.query(WriteRunModel).order_by(WriteRunModel.id.desc()).first().status == "compensated")

# write mode off refuses writes but allows previews
config.ERP_WRITE_MODE = "off"
be = fresh()
r = run(P("Management"), {"op": "insert", "doctype": "Thing", "data": {"qty": 1}}, be)
check("mode off: write refused", not r["ok"] and r.get("mode") == "off", r)
r = run(P("Management"), {"op": "insert", "doctype": "Thing", "data": {"qty": 1}, "preview": True}, be)
check("mode off: preview still works", r["ok"], r)
config.ERP_WRITE_MODE = "all"

# lock held by someone else
from models_cx import DocLockModel
import time
db = Session()
be = fresh(); be.seed("Thing", "LK", qty=1, remarks="")
db.add(DocLockModel(key="Thing::LK", owner="other@x.com", expires=time.time() + 100)); db.commit()
r = run(P("Management"), {"op": "save", "doctype": "Thing", "name": "LK", "data": {"qty": 2}}, be, db)
check("lock: second editor is told who has it", not r["ok"] and r.get("locked_by") == "other@x.com", r)
db.query(DocLockModel).delete(); db.add(DocLockModel(key="Thing::LK", owner="other@x.com", expires=time.time() - 1)); db.commit()
r = run(P("Management"), {"op": "save", "doctype": "Thing", "name": "LK", "data": {"qty": 2}}, be, db)
check("lock: an expired lock (crashed editor) does not block", r["ok"], r)
check("lock: released after the write", db.query(DocLockModel).count() == 0)

# kill switch via the pipeline
db = Session(); be = fresh()
pipeline.set_rules_off(db, True)
r = run(P("Management"), {"op": "insert", "doctype": "Thing", "data": {"qty": -5 + 10}}, be, db)
check("kill switch: rule scripts are off, the write still goes", r["ok"] and be.get_doc("Thing", r["doc"]["name"]).get("remarks") in (None, ""), r)
pipeline.set_rules_off(db, False)

# ───────────────────────── sync ─────────────────────────
config.ERP_WEBHOOK_SECRET = "s3cret"
db = Session()
check("webhook: wrong secret refused", not changefeed.erp_event(db, secret="nope", doctype="Rule", name="R1")["ok"])
check("webhook: empty configured secret refuses everything", True)
r = changefeed.erp_event(db, secret="s3cret", doctype="Rule", name="R1", modified="2026-11-06 11:00:00.000001")
r2 = changefeed.erp_event(db, secret="s3cret", doctype="Rule", name="R1", modified="2026-11-06 11:00:00.000001")
check("webhook: queued once, duplicate deduped", r["queued"] and not r2["queued"] and r2["duplicate"], (r, r2))

be = fresh()
be.seed("Rule", "R1", qty=5)
changefeed.poll(db, be, ENGINE)                         # first sight = baseline, history not replayed
check("poll: baseline records nothing", db.query(ChangeModel).filter_by(doctype="Rule", source="poll").count() == 0)
be.docs["Rule"]["R1"]["qty"] = 7; be.docs["Rule"]["R1"]["modified"] = "2026-11-06 12:00:00.000001"
p = changefeed.poll(db, be, ENGINE)
check("poll: a later modification is found", db.query(ChangeModel).filter_by(doctype="Rule", name="R1", source="poll").count() == 1, p)
p = changefeed.poll(db, be, ENGINE)
check("poll: found only once (watermark + seen-at-watermark)", db.query(ChangeModel).filter_by(doctype="Rule", name="R1", source="poll").count() == 1)

# a submit made in the ERP desk runs After Submit exactly once, however many syncs and webhooks
db = Session(); be = fresh(); be.seed("Rule", "R2", qty=5)
changefeed.poll(db, be, ENGINE)
db.add(ChangeModel(doctype="Rule", name="R2", event="update", modified="2026-11-06 10:00:00.000001", docstatus=0, source="poll", state="done")); db.commit()
be.docs["Rule"]["R2"].update(docstatus=1, modified="2026-11-06 12:30:00.000001")
changefeed.poll(db, be, ENGINE)
changefeed.erp_event(db, secret="s3cret", doctype="Rule", name="R2", modified="2026-11-06 12:30:00.000001", docstatus=1)
res1 = changefeed.reconcile(db, be, ENGINE)
res2 = changefeed.sync(db, be, ENGINE)
check("sync: the desk submit posted the ledger exactly once", be.count("Ledger", {"thing": "R2"}) == 1, (res1, res2, be.docs.get("Ledger")))
check("sync: its own ledger write was not treated as an ERP-side change", db.query(ChangeModel).filter_by(doctype="Ledger", state="new").count() == 0)

# a desk edit that breaks a rule becomes a breach, never an automatic revert
db = Session(); be = fresh(); be.seed("Rule", "R3", qty=5)
changefeed.poll(db, be, ENGINE)
be.docs["Rule"]["R3"].update(qty=500, modified="2026-11-06 13:00:00.000001")
changefeed.sync(db, be, ENGINE)
b = db.query(BreachModel).filter_by(doctype="Rule", name="R3").first()
check("breach: a rule-breaking desk edit is flagged", b is not None and b.state == "open" and "above limit" in b.message, b and b.message)
check("breach: the ERP data was NOT reverted", be.get_doc("Rule", "R3")["qty"] == 500)
be.docs["Rule"]["R3"].update(qty=50, modified="2026-11-06 13:30:00.000001")
changefeed.sync(db, be, ENGINE)
check("breach: fixing the value resolves it", db.query(BreachModel).filter_by(doctype="Rule", name="R3").first().state == "resolved")

# deletion in the ERP
db = Session(); be = fresh(); be.seed("Rule", "R4", qty=1)
db.add(BreachModel(doctype="Rule", name="R4", script="x", message="m", state="open")); db.commit()
db.add(ChangeModel(doctype="Rule", name="R4", event="delete", modified="d1", docstatus=2, source="poll", state="new")); db.commit()
changefeed.reconcile(db, be, ENGINE)
check("sync: a deleted record closes its breaches", db.query(BreachModel).filter_by(name="R4").first().state == "resolved")

# lock prevents overlapping syncs
db = Session()
check("sync: a second overlapping sync is skipped", changefeed._lock(db, "cx_sync_lock") and not changefeed._lock(db, "cx_sync_lock"))

# ───────────────────────── guardrails ─────────────────────────
check("roles: only Management/Admin delete", not guardrails.can(["Production"], "Production Card", "delete") and guardrails.can(["Management"], "Production Card", "delete"))
check("roles: Accounts submits invoices, Merchandiser cannot", guardrails.can(["Accounts"], "Sales Invoice", "submit") and not guardrails.can(["Merchandiser"], "Sales Invoice", "submit"))
check("roles: costing hidden from the shop floor", not guardrails.can(["Production"], "Cost Sheet", "read"))
check("classify: ledger submit is risky, plain submit is not", guardrails.classify("submit", "Delivery Note") == "risky" and guardrails.classify("submit", "Tech Pack") == "draft")

# a child table that a Custom Field adds to a standard doctype has no DocField row: its parent is found through the Custom Field (found by S9: Shipment.apparel_declarations)
from tsr.backend import HttpBackend  # noqa: E402


class _Http(HttpBackend):
    def __init__(self):
        super().__init__("http://erp.invalid", "k:s")

    def _req(self, method, path, params=None, data=None):
        dt = params.get("doctype")
        return {"message": [{"parent": "Packing List"}] if dt == "DocField" and "Packing List Carton" in params["filters"] else [{"dt": "Shipment"}] if dt == "Custom Field" and "Shipment Declaration" in params["filters"] else []}


_h = _Http()
check("parent of a child table: from the DocField", _h._parent_of("Packing List Carton") == "Packing List")
check("parent of a child table added by a Custom Field", _h._parent_of("Shipment Declaration") == "Shipment")
try:
    _h._parent_of("Nope")
    check("parent of an unknown child table is an error", False)
except Exception:
    check("parent of an unknown child table is an error", True)

print(f"\n{'✅' if not N['bad'] else '❌'} {N['ok']} assertions passed, {N['bad']} failed")
sys.exit(1 if N["bad"] else 0)
