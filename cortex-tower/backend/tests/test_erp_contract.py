"""Contract tests for the tri-state ERP read layer + the one write envelope.

Run:  python3 tests/test_erp_contract.py

Design: **no network, no ERP, no SQLite writes.** ``erp._request_ex`` is stubbed, so
the whole suite runs anywhere — including a box with no ERP credentials.

These are the tests that would have caught the 2026-11-04 failure:

* a deleted record and an unreachable ERP used to be the same answer (``{}``), so the
  intake ledger said "already created by an earlier approval" for a record the ERP no
  longer held, and the Sales Order was built against the ghost;
* a 417 "Field not permitted in query" is a *query* error and must never be read as
  "missing", or the caller re-creates a record that exists;
* a rollback counted a 404 as "kept", so the ledger could never be cleared.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault("DB_PATH_OVERRIDE", os.path.join(ROOT, "data", "test_contract.db"))

import erp                                                               # noqa: E402
import write_gate                                                        # noqa: E402

_PASS = 0
_FAIL = []


def ok(label, cond):
    global _PASS
    if cond:
        _PASS += 1
    else:
        _FAIL.append(label)
        print(f"  ✗ {label}")


def eq(label, got, want):
    ok(f"{label} (got {got!r}, want {want!r})", got == want)


# ── the failure classifier ──────────────────────────────────────────────────

def test_classification():
    print("\nCLASSIFICATION — every failure gets a name a caller can act on")
    C = erp._classify_failure
    eq("record 404", C(404, "Client Purchase Order CPO-9 not found", "/api/resource/Client Purchase Order/CPO-9"), "record_missing")
    eq("doctype 404 on a list",
       C(404, '{"exc_type":"DoesNotExistError"}', "/api/resource/Buyer Enquiry"), "doctype_missing")
    eq("doesnotexist names the doctype",
       C(404, "DocType Buyer Enquiry not found", "/api/resource/Buyer Enquiry/x"), "doctype_missing")
    eq("absent doctype answers 500 with a module path",
       C(500, "Error: No module named 'frappe.core.doctype.buyer_enquiry'",
         "/api/resource/Buyer Enquiry/x"), "doctype_missing")
    eq("field not permitted is a QUERY error, not a missing record",
       C(417, '{"exception":"frappe.exceptions.DataError: Field not permitted in query: subject"}',
         "/api/resource/Opportunity"), "field_not_permitted")
    eq("child-table permission", C(403, "Insufficient Permission for Sales Order Item",
                                  "/api/resource/Sales Order Item"), "auth")
    eq("401 after a failed re-discovery", C(401, "unauthorized", "/api/method/frappe.ping"), "auth")
    eq("500 transport", C(502, "bad gateway", "/api/resource/Item"), "http_502")


# ── the read layer ─────────────────────────────────────────────────────────

def _stub(monkeypatch_result):
    """Replace _request_ex for the duration of one test."""
    def _fake(path, params=None, retry=True):
        return monkeypatch_result(path, params, retry)
    erp._request_ex = _fake


def test_read_states():
    print("\nREAD STATES — found / missing / unavailable are three answers")
    real = erp._request_ex
    try:
        _stub(lambda p, q, r: (True, {"data": {"name": "CPO-00858"}}, 200, "", ""))
        r = erp.erp_doc_checked("Client Purchase Order", "CPO-00858")
        eq("found state", r.state, erp.FOUND)
        eq("found value", r.value.get("name"), "CPO-00858")
        eq("found reason empty", r.reason, "")

        _stub(lambda p, q, r: (False, None, 404, "record_missing", "not found"))
        r = erp.erp_doc_checked("Project", "PROJ-0043")
        eq("missing state", r.state, erp.MISSING)
        eq("missing reason", r.reason, "record_missing")
        eq("missing value is empty dict", r.value, {})

        _stub(lambda p, q, r: (False, None, 0, "timeout", "read timeout"))
        r = erp.erp_doc_checked("Project", "PROJ-0043")
        eq("timeout is UNAVAILABLE, never MISSING", r.state, erp.UNAVAILABLE)
        eq("timeout reason", r.reason, "timeout")

        _stub(lambda p, q, r: (False, None, 417, "field_not_permitted", "Field not permitted"))
        r = erp.erp_doc_checked("Opportunity", "CRM-OPP-1")
        eq("field error is UNAVAILABLE, never MISSING", r.state, erp.UNAVAILABLE)

        _stub(lambda p, q, r: (True, {"data": [{"name": "a"}, {"name": "b"}]}, 200, "", ""))
        r = erp.erp_list_checked("Item", ["name"], limit=2)
        eq("list found", (r.state, len(r.value)), (erp.FOUND, 2))

        # a list read may be cached for dashboards; the honest path is use_cache=False
        erp.erp_invalidate_cache()
        _stub(lambda p, q, r: (True, {"data": []}, 200, "", ""))
        r = erp.erp_list_checked("Item", ["name"], limit=2, use_cache=False)
        eq("empty list is FOUND with zero rows", (r.state, r.value), (erp.FOUND, []))

        _stub(lambda p, q, r: (False, None, 404, "doctype_missing", "DocType not found"))
        eq("absent doctype in a list", erp.erp_list_checked("Nope", ["name"]).state, erp.MISSING)
    finally:
        erp._request_ex = real


def test_two_state_wrapper_unchanged():
    print("\nBACKWARD COMPAT — the 149 existing call sites still get their emptiness")
    real = erp._request_ex
    try:
        _stub(lambda p, q, r: (False, None, 404, "record_missing", "not found"))
        eq("erp_doc still returns {}", erp.erp_doc("Project", "PROJ-0043"), {})
        eq("_request still returns (False, None)", erp._request("/x"), (False, None))
        _stub(lambda p, q, r: (True, {"data": {"name": "P"}}, 200, "", ""))
        eq("erp_doc still returns the doc", erp.erp_doc("Project", "P"), {"name": "P"})
    finally:
        erp._request_ex = real


def test_cache_cannot_serve_a_deleted_record():
    print("\nCACHE — a resolver must see the ERP, not a memory of it")
    calls = {"n": 0}

    def _fake(path, params=None, retry=True):
        calls["n"] += 1
        if calls["n"] == 1:
            return True, {"data": {"name": "PROJ-0043"}}, 200, "", ""
        return False, None, 404, "record_missing", "not found"

    real = erp._request_ex
    try:
        erp._request_ex = _fake
        erp.erp_invalidate_cache()
        first = erp.erp_doc_checked("Project", "PROJ-0043", use_cache=True)
        second = erp.erp_doc_checked("Project", "PROJ-0043")          # cache bypassed
        eq("first read found", first.state, erp.FOUND)
        eq("second read sees the deletion", second.state, erp.MISSING)
        eq("the ERP was asked twice", calls["n"], 2)
    finally:
        erp._request_ex = real
        erp.erp_invalidate_cache()


# ── the write envelope ────────────────────────────────────────────────────

def test_batch_cap():
    print("\nENVELOPE — one cap for both paths, and it is config's number")
    eq("cap is config's", write_gate.MAX_PER_RUN, 60)
    b = write_gate.Batch(db=None, label="t", limit=2, audit_records=False)
    b.register("Item", "A-1")
    b.register("Item", "A-2")
    eq("at the cap", b.can_create(), False)
    eq("refusal counted", b.refused, 1)
    ok("refusal is a sentence", "cap of 2" in b.errors[-1])
    eq("names recorded", b.names("Item"), ["A-1", "A-2"])
    ok("register is idempotent", (b.register("Item", "A-1"), len(b.created))[1] == 2)
    eq("summary", b.summary(), {"created": 2, "errors": 1, "refused": 1, "cap": 2})


def test_rollback_treats_absent_as_done():
    print("\nROLLBACK — a record someone already deleted is rolled back, not 'kept'")
    real_del = erp.erp_delete_checked
    try:
        def _fake_delete(doctype, name):
            if name == "gone":
                return True, "already_missing", ""
            if name == "killed":
                return True, "deleted", ""
            return False, "unavailable", "boomed"
        erp.erp_delete_checked = _fake_delete

        res = write_gate.rollback_names("Item", ["gone", "killed"])
        eq("ghost counts as undone", res["already_missing"], ["gone"])
        eq("deleted", res["deleted"], ["killed"])
        eq("ok when everything is gone", res["ok"], True)

        res2 = write_gate.rollback_names("Item", ["stuck"])
        eq("a real failure is still a failure", res2["ok"], False)
        eq("and it is named", res2["failed"], ["stuck: boomed"])

        res3 = write_gate.rollback_refs([{"doctype": "Item", "name": "gone"},
                                         {"doctype": "Item", "name": "killed"}])
        eq("rollback_refs ok", res3["ok"], True)
        eq("rollback_refs deleted", sorted(res3["deleted"]), ["Item killed"])
        eq("rollback_refs already_missing", res3["already_missing"], ["Item gone"])
    finally:
        erp.erp_delete_checked = real_del


def main():
    test_classification()
    test_read_states()
    test_two_state_wrapper_unchanged()
    test_cache_cannot_serve_a_deleted_record()
    test_batch_cap()
    test_rollback_treats_absent_as_done()
    print("\n" + "=" * 70)
    if _FAIL:
        print(f"❌ {len(_FAIL)} FAILED")
        for f in _FAIL:
            print("   -", f)
        sys.exit(1)
    print(f"✅ {_PASS} assertions passed")


if __name__ == "__main__":
    main()
