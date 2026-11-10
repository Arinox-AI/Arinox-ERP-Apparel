"""Doctype gate of the rulebook (synthetic, fake ERP). Run from backend/: python3 tests/test_rulebook_gate.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import erp, rulebook
N = {"ok": 0, "bad": 0}


def check(label, cond, extra=""):
    N["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", label, extra)


def fake(states):
    def f(dt, fields=None, filters=None, limit=500, order=None, use_cache=True):
        st, rows = states.get(dt, (erp.FOUND, [{"name": "X1"}]))
        return erp.ReadResult(st, rows, "", "")
    return f


real = erp.erp_list_checked
try:
    rule = rulebook._r_work_order_missing
    bom = rulebook._r_bom_missing_order
    po = rulebook._r_client_po_unlinked
    order = rulebook._r_order_overdue

    erp.erp_list_checked = fake({"Work Order": (erp.FOUND, []), "Client Purchase Order": (erp.MISSING, []),
                                 "BOM": (erp.FOUND, [])})
    check("empty Work Order -> skipped", rulebook.rule_gate(rule)[0] is False)
    check("empty BOM -> skipped", rulebook.rule_gate(bom)[0] is False)
    run, note = rulebook.rule_gate(po)
    check("missing doctype -> skipped", run is False and "Client Purchase Order" in note, note)
    check("ungated rule always runs", rulebook.rule_gate(order) == (True, ""))

    erp.erp_list_checked = fake({})
    check("present doctype -> kept", rulebook.rule_gate(rule) == (True, ""))
    check("present Buyer-side doctype -> kept", rulebook.rule_gate(po) == (True, ""))

    erp.erp_list_checked = fake({"Work Order": (erp.UNAVAILABLE, []), "Client Purchase Order": (erp.UNAVAILABLE, [])})
    run, note = rulebook.rule_gate(rule)
    check("unreadable ERP -> kept and noted", run is True and "could not check" in note, note)
    run, note = rulebook.rule_gate(po)
    check("unreadable ERP (plain doctype) -> kept and noted", run is True and "could not check" in note, note)

    def boom(*a, **k): raise RuntimeError("down")
    erp.erp_list_checked = boom
    check("exception -> kept", rulebook.rule_gate(rule)[0] is True)

    calls = []
    def counting(dt, **k):
        calls.append(dt); return erp.ReadResult(erp.FOUND, [{"name": "a"}], "", "")
    erp.erp_list_checked = counting
    memo = {}
    rulebook.rule_gate(rule, memo); rulebook.rule_gate(rule, memo)
    check("probe cached per call", calls == ["Work Order"], calls)
    check("every gated rule is a real rule", all(any(r.__name__ == n for r in rulebook.RULES) for n in rulebook.RULE_NEEDS))
finally:
    erp.erp_list_checked = real
print(f"test_rulebook_gate: {N['ok']} ok, {N['bad']} bad")
sys.exit(1 if N["bad"] else 0)
