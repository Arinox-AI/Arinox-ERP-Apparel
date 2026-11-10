#!/usr/bin/env python3
"""The buyer's own order number — typed, per company, never assumed (2026-11-03).

The defect this suite locks down: the Client PO identified the buyer's order with `client_po_no`
(globally unique) plus `em_no` — "EM" being **EMJ Apparel Group's** series. Every other buyer
numbers their own way, and two buyers may legitimately use the same digits, so
  · a second number had no home and no type,
  · `client_po_no` unique=1 made the second company's PO collide with the first's,
  · the intake blocked a PO number already on file "for another buyer" — which is NORMAL.

No network, no writes: the ERP is stubbed. One optional live check confirms the master is seeded.

Run:  python3 tests/test_buyer_ref.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import buyer_ref                                                          # noqa: E402
import intake                                                             # noqa: E402
import intake_exec                                                        # noqa: E402

_PASS = 0
_FAIL = []


def check(name, cond, detail=""):
    global _PASS
    if cond:
        _PASS += 1
        print(f"  PASS  {name}")
    else:
        _FAIL.append(name)
        print(f"  FAIL  {name}   {detail}")


def eq(name, got, want):
    check(name, got == want, f"got {got!r} want {want!r}")


# ────────────────────────────────────────────────────────────────────────────
# the records, as the live site now holds them
# ────────────────────────────────────────────────────────────────────────────
TYPES = [
    {"name": "EM", "ref_code": "EM", "ref_label": "EM No.", "role": "Order identity",
     "normalise": "Upper alnum", "strip_prefix": "", "format_regex": r"^EM\d{4,6}$"},
    {"name": "PO", "ref_label": "PO No.", "ref_code": "PO", "role": "Commercial PO",
     "normalise": "Strip prefix + alnum", "strip_prefix": "PO", "format_regex": ""},
    {"name": "REF", "ref_code": "REF", "ref_label": "Buyer reference", "role": "Secondary",
     "normalise": "Upper alnum", "strip_prefix": "", "format_regex": ""},
]

CUSTOMERS = {
    "EMJ Apparel Group": [
        {"ref_type": "EM", "label_as_printed": "EM No.", "format_regex": r"^EM\d{4,6}$",
         "is_required": 1, "is_identity": 1, "sequence": 1},
        {"ref_type": "PO", "label_as_printed": "P.O. NO.", "format_regex": r"^\d{4,7}$",
         "is_required": 1, "is_identity": 0, "sequence": 2},
    ],
    "Bella Dahl": [
        {"ref_type": "PO", "label_as_printed": "P.O. NO.", "format_regex": r"^(PO\s*)?\d{4,6}$",
         "is_required": 1, "is_identity": 1, "sequence": 1},
    ],
    "Aster & Oak GmbH": [],          # no configuration — nothing may be invented for them
}


class FakeERP:
    """Reads only. `erp_get` answers the two masters, `erp_doc` the Customer and a CPO."""

    def __init__(self, cpos=None):
        self.cpos = cpos or []

    def erp_get(self, doctype, fields=None, filters=None, limit=500, order=None):
        if doctype == "Buyer Order Ref Type":
            return TYPES
        if doctype == "Client Purchase Order":
            return self.cpos
        if doctype == "Customer":
            return [{"name": c, "customer_name": c, "email_id": ""} for c in CUSTOMERS]
        return []

    def erp_doc(self, doctype, name):
        if doctype == "Customer":
            return {"name": name, "order_ref_formats": CUSTOMERS.get(name, [])}
        return {}


# ────────────────────────────────────────────────────────────────────────────
def t_classify():
    print("\n1 · reading a paper — the type comes from the buyer's record")
    erp = FakeERP()
    buyer_ref.invalidate()

    emj = buyer_ref.classify(erp, "EMJ Apparel Group", ["70795", "EM92432"])
    eq("EMJ: two numbers become two typed rows", len(emj["refs"]), 2)
    eq("EMJ: the EM number is the identity", emj["order_ref"], "EM92432")
    eq("EMJ: its label is the buyer's own", emj["order_ref_label"], "EM No.")
    eq("EMJ: the PO row is typed as the commercial PO",
       [r["ref_type"] for r in emj["refs"]], ["EM", "PO"])
    eq("EMJ: PO row normalised", emj["refs"][1]["normalised"], "70795")
    eq("EMJ: exactly one identity row",
       sum(1 for r in emj["refs"] if r.get("is_identity")), 1)

    bella = buyer_ref.classify(erp, "Bella Dahl", ["PO 69785"])
    eq("Bella Dahl: one number, typed PO", [r["ref_type"] for r in bella["refs"]], ["PO"])
    eq("Bella Dahl: their PO names the order", bella["order_ref"], "PO 69785")
    eq("Bella Dahl: comparable key drops the prefix",
       bella["refs"][0]["normalised"], "69785")
    eq("Bella Dahl: no warning", bella["warnings"], [])

    oak = buyer_ref.classify(erp, "Aster & Oak GmbH", ["AO-5644"])
    eq("unconfigured buyer: one row, nothing refused", len(oak["refs"]), 1)
    eq("unconfigured buyer: typed as the commercial PO", oak["refs"][0]["ref_type"], "PO")
    eq("unconfigured buyer: still carries an identity", oak["order_ref"], "AO-5644")
    eq("unconfigured buyer: no invented label", oak["order_ref_label"], "PO No.")

    missing = buyer_ref.classify(erp, "EMJ Apparel Group", ["70795"])
    eq("a required number the paper does not carry: one row", len(missing["refs"]), 1)
    check("…and it is reported, by the buyer's own label",
          any("EM No." in w for w in missing["warnings"]), missing["warnings"])
    eq("…and the PO still names the order", missing["order_ref"], "70795")


def t_normalise():
    print("\n2 · two spellings of one number")
    eq("PO 69785", buyer_ref.normalise("PO 69785", "Strip prefix + alnum", "PO"), "69785")
    eq("P.O. #69785", buyer_ref.normalise("P.O. #69785", "Strip prefix + alnum", "PO"), "69785")
    eq("po-69785", buyer_ref.normalise("po-69785", "Strip prefix + alnum", "PO"), "69785")
    eq("69785", buyer_ref.normalise("69785", "Strip prefix + alnum", "PO"), "69785")
    eq("EM92430 keeps its letters", buyer_ref.normalise("EM 92430", "Upper alnum"), "EM92430")
    eq("digits only", buyer_ref.normalise("HL-93312", "Digits only"), "93312")
    check("different numbers stay different",
          buyer_ref.normalise("69786", "Strip prefix + alnum", "PO") != "69785")


def t_identity():
    print("\n3 · which number names the order, per buyer")
    erp = FakeERP()
    buyer_ref.invalidate()
    eq("EMJ identifies by EM", buyer_ref.identity_type(erp, "EMJ Apparel Group")["name"], "EM")
    eq("Bella Dahl identifies by their PO",
       buyer_ref.identity_type(erp, "Bella Dahl")["name"], "PO")
    eq("an unconfigured buyer is identified by their PO — never by another buyer's series",
       buyer_ref.identity_type(erp, "Aster & Oak GmbH")["name"], "PO")
    # the fallback is the ROLE default, which the client sets; assert it is never asserted as EMJ policy
    check("configuration is what makes EM the identity for EMJ",
          buyer_ref.formats(erp, "EMJ Apparel Group")[0]["is_identity"] == 1)

    eq("same buyer, two spellings, one order",
       buyer_ref.same_order(erp, "Bella Dahl", "PO 69785", "Bella Dahl", "69785"), True)
    eq("same digits, two buyers, NOT one order",
       buyer_ref.same_order(erp, "EMJ Apparel Group", "69785", "Bella Dahl", "69785"), False)
    eq("a different number is a different order",
       buyer_ref.same_order(erp, "EMJ Apparel Group", "69785", "EMJ Apparel Group", "69786"), False)


def t_match():
    print("\n4 · the duplicate rule is (buyer, their number)")
    erp = FakeERP(cpos=[
        {"name": "CPO-00851", "client_po_no": "69785", "customer": "EMJ Apparel Group",
         "order_ref": "EM92409"},
    ])
    buyer_ref.invalidate()

    facts = {"document_type": "po", "po": {"number": "69785", "reference": None},
             "buyer": {"name": "Bella Dahl", "email": ""}, "style": {}}
    out = intake.match(_db(), facts, erp=erp)
    eq("Bella Dahl's 69785 resolves to Bella Dahl", out["customer"], "Bella Dahl")
    check("another buyer's identical number does NOT block",
          "po_number_on_file_for_another_buyer" not in out["blocking"], out["blocking"])
    check("…it is a warning, and it says why",
          any("per buyer" in w for w in out["warnings"]), out["warnings"])
    eq("…and it is not linked to the other buyer's record", out["po_existing"], None)

    same = {"document_type": "po", "po": {"number": "69785", "reference": None},
            "buyer": {"name": "EMJ Apparel Group", "email": ""}, "style": {}}
    out2 = intake.match(_db(), same, erp=erp)
    eq("the same buyer's same number is the existing record",
       out2["po_existing"], "CPO-00851")
    eq("…and no other-buyer warning", out2.get("po_other_buyer"), None)


def t_payload():
    print("\n5 · the record the intake writes")
    erp = FakeERP()
    buyer_ref.invalidate()
    facts = {"po": {"number": "70795", "reference": "EM92432"}, "document_type": "po",
             "commercial": {"currency": "USD", "total_qty": 800, "total_value": 10880},
             "style": {"code": "C9051-U70-654"}, "buyer": {"name": "EMJ Apparel Group"},
             "quality": {}, "ship_date": "2026-06-26", "_message_id": "", "_attachment": ""}
    matches = {"customer": "EMJ Apparel Group",
               "refs": buyer_ref.classify(erp, "EMJ Apparel Group",
                                          ["70795", "EM92432"])["refs"],
               "order_ref": "EM92432", "order_ref_label": "EM No.", "order_ref_type": "EM"}
    payload = intake_exec._cpo_payload(facts, matches)
    eq("PO number stays the PO number", payload["client_po_no"], "70795")
    eq("the buyer's order reference is stamped", payload["order_ref"], "EM92432")
    eq("…with its type", payload["order_ref_type"], "EM")
    eq("…with the buyer's own label", payload["order_ref_label"], "EM No.")
    eq("typed rows travel with the record", len(payload["refs"]), 2)
    eq("each row is a child of the right doctype",
       {r["doctype"] for r in payload["refs"]}, {"Buyer Order Ref"})
    check("the legacy EM column is NOT written by new records", "em_no" not in payload)

    bella = {"po": {"number": "69785", "reference": None}, "document_type": "po",
             "commercial": {"currency": "USD"}, "style": {"code": "C2027-S84-304"},
             "buyer": {"name": "Bella Dahl"}, "quality": {}}
    m2 = {"customer": "Bella Dahl",
          "refs": buyer_ref.classify(erp, "Bella Dahl", ["PO 69785"])["refs"],
          "order_ref": "PO 69785", "order_ref_label": "P.O. NO.", "order_ref_type": "PO"}
    p2 = intake_exec._cpo_payload(bella, m2)
    eq("Bella Dahl: the PO is the identity", p2["order_ref"], "PO 69785")
    eq("Bella Dahl: one typed row", len(p2["refs"]), 1)
    eq("Bella Dahl: labelled as their paper prints it", p2["order_ref_label"], "P.O. NO.")


def t_live():
    print("\n6 · live instance (skipped when unreachable)")
    try:
        import erp as _erp
        types = _erp.erp_get("Buyer Order Ref Type", fields=["name", "ref_code", "role"],
                             limit=0) or []
    except Exception as exc:                                  # noqa: BLE001
        print(f"  SKIP  no ERP ({str(exc)[:60]})")
        return
    if not types:
        print("  SKIP  the master is not on this instance")
        return
    check("the type master is seeded", len(types) >= 3, len(types))
    check("EM is a row in it, not a constant in code",
          any(t["ref_code"] == "EM" for t in types))
    cust = _erp.erp_doc("Customer", "EMJ Apparel Group") or {}
    check("EMJ carries its own reference formats", len(cust.get("order_ref_formats") or []) == 2)
    cpo = _erp.erp_get("Client Purchase Order", fields=["name", "order_ref", "order_ref_label"],
                       limit=0) or []
    check("every live CPO carries a stamped reference",
          bool(cpo) and all(c.get("order_ref") for c in cpo), f"{len(cpo)} records")


class _db:
    """The intake's storage handle — this suite touches nothing but the classification."""

    def __getattr__(self, item):
        return lambda *a, **k: None


def main():
    t_classify()
    t_normalise()
    t_identity()
    t_match()
    t_payload()
    t_live()
    print("\n" + "=" * 70)
    if _FAIL:
        print(f"❌ {len(_FAIL)} failed: {_FAIL}")
        return 1
    print(f"✅ {_PASS} assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
