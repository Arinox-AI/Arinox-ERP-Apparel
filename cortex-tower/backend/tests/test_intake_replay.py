"""The replay test — approve, delete in the ERP, approve again.

Run:  python3 tests/test_intake_replay.py

This is the test for the failure of 2026-11-04. What happened in the live app:

  1. an approval created Customer + Opportunity + CPO + Project + 7 Items;
  2. those records were deleted in the ERP;
  3. the queue was approved again and answered *"already created by an earlier
     approval — not repeated"*, then tried to build a Sales Order against the ghosts:
     `Could not find Customer: HARBOR & LANE…, Project: PROJ-0043, CPO-01242`.

No network, no ERP writes: the whole instance is a dict.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault("DB_PATH_OVERRIDE", os.path.join(ROOT, "data", "test_replay.db"))

import erp                                                               # noqa: E402
import intake_exec                                                       # noqa: E402

_PASS = 0
_FAIL = []


def ok(label, cond, detail=""):
    global _PASS
    if cond:
        _PASS += 1
    else:
        _FAIL.append(label)
        print(f"  ✗ {label} {detail}")


class Site:
    """A fake ERP: doctype -> {name: doc}, with a switch for 'the ERP is unreachable'."""

    def __init__(self):
        self.rows = {}
        self.seq = 0
        self.down = False
        self.created = []

    def create(self, doctype, payload):
        if self.down:
            return False, {}, "erp down"
        self.seq += 1
        prefix = {"Customer": "CUST", "Opportunity": "CRM-OPP", "Project": "PROJ",
                  "Sales Order": "SAL-ORD"}.get(doctype, doctype.split()[0].upper())
        name = f"{prefix}-T{self.seq}"
        self.rows.setdefault(doctype, {})[name] = {"name": name, **payload}
        self.created.append({"doctype": doctype, "name": name, "payload": payload})
        return True, {"name": name}, None

    def delete_all(self):
        self.rows = {}

    def doc_checked(self, doctype, name, use_cache=False):
        if self.down:
            return erp.ReadResult(erp.UNAVAILABLE, {}, "timeout", "read timeout")
        if name in (self.rows.get(doctype) or {}):
            return erp.ReadResult(erp.FOUND, self.rows[doctype][name], "", "")
        return erp.ReadResult(erp.MISSING, {}, "record_missing", "not found")

    def get(self, doctype, fields=None, filters=None, limit=500, order=None):
        return list((self.rows.get(doctype) or {}).values())

    def delete_checked(self, doctype, name):
        if self.down:
            return False, "unavailable", "erp down"
        if name in (self.rows.get(doctype) or {}):
            del self.rows[doctype][name]
            return True, "deleted", ""
        return True, "already_missing", ""


class Run:
    """The minimum an IntakeRun must expose to execute()."""

    def __init__(self, plan, facts=None, matches=None, created_refs=None):
        self.id = 1
        self.route = "enquiry"
        self.plan = json.dumps(plan)
        self.facts = json.dumps(facts or {})
        self.matches = json.dumps(matches or {})
        self.created_refs = json.dumps(created_refs or [])
        self.status = "understood"
        self.result_note = ""
        self.decided_by = None
        self.decided_at = None


PLAN = [
    {"key": "customer", "label": "Customer", "kind": "create", "doctype": "Customer",
     "status": "ready",
     "payload": {"customer_name": "KESTREL OUTFITTERS LTD", "customer_type": "Company"}},
    {"key": "opportunity", "label": "Opportunity", "kind": "create", "doctype": "Opportunity",
     "status": "ready",
     "payload": {"opportunity_type": "Sales", "status": "Open", "title": "Kestrel enquiry",
                 "conversion_rate": 1}},
]


def wire(site):
    erp.erp_create = site.create
    erp.erp_doc_checked = site.doc_checked
    erp.erp_ref_state = lambda dt, n: site.doc_checked(dt, n).state
    erp.erp_get = site.get
    erp.erp_delete_checked = site.delete_checked
    erp.erp_delete = lambda dt, n: (True, None)
    erp.erp_update = lambda dt, n, d: (True, d)
    erp.erp_doc = lambda dt, n: (site.rows.get(dt) or {}).get(n) or {}
    # find_existing/preflight consult these for the required-field filler
    erp.erp_get_checked = lambda dt, **kw: (True, site.get(dt))


def test_first_approval(site):
    print("\n1 · first approval — two drafts, and the ledger records both")
    run = Run(PLAN, matches={"company": "CORTEX FASHION (HK) LIMITED"})
    res = intake_exec.execute(None, run, actor="Test")
    ok("approved", res.get("status") == "approved", str(res.get("note"))[:120])
    refs = json.loads(run.created_refs)
    ok("two refs on the ledger", len(refs) == 2, json.dumps(refs))
    ok("the Customer is on the ledger", any(r["doctype"] == "Customer" for r in refs))
    ok("the ERP holds them", site.doc_checked("Customer", "CUST-T1").state == erp.FOUND)
    return run


def test_replay_after_deletion(site, run):
    print("\n2 · the records are deleted in the ERP, and the queue is approved again")
    site.delete_all()                      # someone deleted them in the ERP
    ok("the ERP really is empty", site.doc_checked("Customer", "CUST-T1").state == erp.MISSING)

    before = len(site.created)
    res = intake_exec.execute(None, run, actor="Test")
    note = run.result_note or ""
    ok("it approves again", res.get("status") == "approved", note[:160])
    ok("it does NOT claim they already exist",
       "already created by an earlier approval" not in note, note[:200])
    ok("it says the ERP no longer holds them", "no longer holds" in note, note[:200])
    ok("the records are created AGAIN", len(site.created) - before == 2,
       f"{len(site.created) - before} created")
    refs = json.loads(run.created_refs)
    ok("the ledger is rebuilt, not appended", len(refs) == 2, json.dumps(refs))
    ok("no ghost refs survive", all(r["name"] != "CUST-T1" for r in refs), json.dumps(refs))
    ok("the new Customer exists", any(k.startswith("CUST-T") and k != "CUST-T1"
                                      for k in site.rows.get("Customer", {})))


def test_unverifiable_stops(site, run):
    print("\n3 · if the ERP cannot be asked, it stops — it does not guess")
    site.down = True
    before = len(site.created)
    res = intake_exec.execute(None, run, actor="Test")
    ok("blocked", res.get("status") == "blocked", str(res.get("status")))
    ok("nothing was written", len(site.created) == before, f"{len(site.created) - before}")
    ok("it says why", "cannot verify" in (run.result_note or ""), (run.result_note or "")[:160])
    ok("and names the reason", "timeout" in (run.result_note or ""), (run.result_note or "")[:200])
    site.down = False


def test_frozen_plan_link_is_dropped(site):
    print("\n4 · a link frozen into the plan is dropped when its record is gone")
    plan = [
        {"key": "opportunity", "label": "Opportunity", "kind": "create", "doctype": "Opportunity",
         "status": "ready",
         "payload": {"opportunity_type": "Sales", "status": "Open", "conversion_rate": 1,
                     "party_name": "CUST-DELETED", "project": "PROJ-0043"}},
    ]
    run = Run(plan, matches={})
    site.rows.setdefault("Opportunity", {})
    res = intake_exec.execute(None, run, actor="Test")
    note = run.result_note or ""
    ok("it did not build on PROJ-0043", "dropped project=PROJ-0043" in note, note[:220])
    ok("it did not build on the ghost buyer", "dropped party_name=CUST-DELETED" in note, note[:220])
    ok("it still reported honestly", res.get("status") in ("approved", "blocked"), str(res.get("status")))


def test_reuse_target_deleted_is_a_create(site):
    """The failure he actually hit (2026-11-04).

    Plan step 1 was `kind: reuse, existing: "HARBOR & LANE APPAREL CO."`. The buyer had been
    deleted in the ERP, and the old code set `customer = None` and **skipped the step** — so
    the Client PO was created with no buyer and the Sales Order blocked with
    `Customer: customer is required … nothing on the record supplies it`.
    A missing reuse target is a CREATE, not a skip.
    """
    print("\n6 · a reuse target that was deleted becomes a CREATE, not a skip")
    plan = [
        {"key": "customer", "label": "Customer — reuse KESTREL", "kind": "reuse",
         "doctype": "Customer", "status": "ready", "payload": {"existing": "KESTREL-OUT-1"}},
        {"key": "sales_order", "label": "Sales Order", "kind": "create", "doctype": "Sales Order",
         "status": "ready",
         "payload": {"company": "CORTEX FASHION (HK) LIMITED", "currency": "USD",
                     "conversion_rate": 1, "delivery_date": "2027-02-11",
                     "items": [{"item_code": "C9533-U71-725-S", "qty": 100, "rate": 14.2}]}},
    ]
    site.rows.pop("Customer", None)          # the buyer is gone from the ERP
    run = Run(plan, facts={"buyer": {"name": "KESTREL OUTFITTERS LTD"}}, matches={})
    res = intake_exec.execute(None, run, actor="Test")
    note = run.result_note or ""
    ok("the Customer is created again", "created Customer" in note, note[:220])
    ok("it says why", "deleted from the ERP" in note, note[:220])
    refs = json.loads(run.created_refs)
    ok("the ledger carries the new Customer",
       any(r["doctype"] == "Customer" for r in refs), json.dumps(refs))
    ok("the Sales Order is NOT blocked for a missing customer",
       "Customer: customer is required" not in note, note[:260])
    so = (site.rows.get("Sales Order") or {})
    ok("and the Sales Order carries the buyer",
       bool(so) and all((v or {}).get("customer") for v in so.values()), json.dumps(list(so))[:160])


def test_required_link_missing_blocks(site):
    """A REQUIRED link is never dropped — a document with no buyer is worse than a refusal."""
    print("\n7 · a required link that is gone blocks the step instead of being dropped")
    plan = [{"key": "so", "label": "Sales Order", "kind": "create", "doctype": "Sales Order",
             "status": "ready",
             "payload": {"customer": "CUST-GONE-1", "company": "CORTEX FASHION (HK) LIMITED",
                         "currency": "USD", "conversion_rate": 1, "delivery_date": "2027-02-11",
                         "items": [{"item_code": "CUST-1", "qty": 1, "rate": 1}]}}]
    run = Run(plan, matches={})
    before = len(site.created)
    res = intake_exec.execute(None, run, actor="Test")
    note = run.result_note or ""
    ok("no Sales Order was created", len(site.created) == before, f"{len(site.created) - before}")
    ok("it blocks", res.get("status") == "blocked", str(res.get("status")))
    ok("and names the required field", "requires a customer" in note, note[:240])


def test_rollback_clears_the_ledger(site, run):
    print("\n5 · rollback clears a ledger whose records are already gone")
    site.delete_all()
    refs = json.loads(run.created_refs)
    res = intake_exec.rollback(refs)
    ok("rollback succeeds against ghosts", res.get("ok") is True, json.dumps(res)[:200])
    ok("they are reported as already missing", len(res.get("already_missing") or []) == len(refs))


def main():
    site = Site()
    wire(site)
    run = test_first_approval(site)
    test_replay_after_deletion(site, run)
    test_unverifiable_stops(site, run)
    test_frozen_plan_link_is_dropped(site)
    test_reuse_target_deleted_is_a_create(site)
    test_required_link_missing_blocks(site)
    test_rollback_clears_the_ledger(site, run)
    print("\n" + "=" * 70)
    if _FAIL:
        print(f"❌ {len(_FAIL)} FAILED")
        for f in _FAIL:
            print("   -", f)
        sys.exit(1)
    print(f"✅ {_PASS} assertions passed")


if __name__ == "__main__":
    main()
