#!/usr/bin/env python3
"""A mail with TWO documents: the Tech Pack and the BOM (2026-11-07).

The user's point, and it is the right one: *"tech pack has all the cuttings required and measurements, that is different;
BOM is just what items are required to make and how much it could require."* Two documents arrive together and they must
not be poured into the same place:

| what arrives | where it belongs in the ERP |
|---|---|
| Tech Pack — measurement chart, construction/cutting notes, wash & care, packing, size range | the Tech Pack's own spec fields (`measurements` chart, `construction_notes`, `wash_care`, `packing_notes`, `size_range`) |
| BOM — materials + quantity per garment | the Tech Pack's **Buyer BOM** tab (`materials`), which costing copies onto the Cost Sheet |

So one mail is now read document by document: each attachment is given to the model, the answer says what kind of
document it is, and the two halves land in their own homes.

Two traps this suite keeps shut:

* the ERP's `Tech Pack Measurement` child has one column per size and **only XXS … XXL exist**, so a size chart in 2/4/6
  cannot be charted — those sizes are reported, never silently dropped;
* a model writing `construction_notes` puts **raw newlines inside a JSON string**, which is invalid JSON and used to lose
  the whole answer. `_json_junk_strip` now escapes control characters inside strings.

No network: the model is stubbed, the ERP is the fake Arinox site.

Run:  python3 tests/test_tech_pack_read.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ["DB_PATH_OVERRIDE"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["KOGO_AUTH_VERIFIED"] = "1"

from database import get_session, init_db                                    # noqa: E402
init_db()
import ai_nextsteps                                                          # noqa: E402
import deals                                                                 # noqa: E402
from deal_harness import fake_erp, ADMIN                                     # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "BOM_C9043-U70-629.xls")

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


TECH_PACK_TEXT = """ACME APPAREL GROUP - TECH PACK
Style: Z1001-A10-100   Style Name: 1 POCKET CROPPED BUTTON DOWN
Size Range: XXS-XXL    Fabric: 100% LYOCELL
MEASUREMENT CHART (cm)
Point of Measure | Tol | XXS | XS | S | M | L | XL | XXL
Chest | 0.5 | 44 | 46 | 48 | 50 | 52 | 55 | 58
Waist | 0.5 | 40 | 42 | 44 | 46 | 48 | 51 | 54
CONSTRUCTION
- 1 patch pocket on the left chest, 6 x 5 cm.
WASH & CARE
Machine wash cold, tumble dry low.
PACKING
Flat pack, 1 pc per polybag, 48 pcs per carton.
"""

TECH_PACK_REPLY = json.dumps({
    "kind": "tech_pack", "style_no": "Z1001-A10-100", "style_name": "1 POCKET CROPPED BUTTON DOWN",
    "colour": "CLCPW", "fabric": "100% LYOCELL", "sizes": ["XXS", "XS", "S", "M", "L", "XL", "XXL"],
    "size_range": "XXS-XXL", "qty": None, "product_type": "Woven Top", "rows": [],
    "measurements": [
        {"pom_code": "A", "point_of_measure": "Chest", "section": "Body", "tolerance": 0.5,
         "values": {"XXS": 44, "XS": 46, "S": 48, "M": 50, "L": 52, "XL": 55, "XXL": 58}},
        {"pom_code": "B", "point_of_measure": "Waist", "section": "Body", "tolerance": 0.5,
         "values": {"XXS": 40, "XS": 42, "S": 44, "M": 46, "L": 48, "XL": 51, "XXL": 54}},
    ],
    "construction_notes": "1 patch pocket on the left chest, 6 x 5 cm.\nFront placket with 6 buttons.",
    "wash_care": "Machine wash cold, tumble dry low.",
    "packing_notes": "Flat pack, 1 pc per polybag, 48 pcs per carton.",
})


def t_control_chars():
    print("\n1. A multi-line note does not destroy the answer")
    raw = '{"kind": "tech_pack", "construction_notes": "line one\nline two\tTabbed"}'
    parsed = deals._json_block(raw)
    check("a raw newline inside a string is repaired", bool(parsed), str(parsed))
    check("the text survives", parsed.get("construction_notes") == "line one\nline two\tTabbed", repr(parsed.get("construction_notes")))
    check("a correct escape is left alone", deals._json_block('{"a": "x\\ny"}') == {"a": "x\ny"})


def t_spec_from_ai():
    print("\n2. The specification half is validated")
    spec = deals.spec_from_ai(TECH_PACK_REPLY, "Z1001-A10-100", ["Woven Top", "Dress"])
    check("it is recognised as a tech pack", spec["kind"] == "tech_pack", spec["kind"])
    check("the style fields come through", spec["style_no"] == "Z1001-A10-100" and spec["style_name"].startswith("1 POCKET"),
          str(spec["style_name"]))
    check("the size range comes through", spec["size_range"] == "XXS-XXL", spec["size_range"])
    check("the product type is one the ERP has", spec["product_type"] == "Woven Top", spec["product_type"])
    check("two measurement rows", len(spec["measurements"]) == 2, str(len(spec["measurements"])))
    chest = spec["measurements"][0]
    check("a measurement keeps its point and values", chest["point_of_measure"] == "Chest" and chest["values"]["M"] == 50.0,
          str(chest))
    check("the construction notes keep their lines", "\n" in spec["construction_notes"], repr(spec["construction_notes"][:40]))
    check("wash & care and packing come through", spec["wash_care"].startswith("Machine wash")
          and spec["packing_notes"].startswith("Flat pack"), str(spec["packing_notes"][:30]))
    check("no BOM rows are invented for a tech pack", not (deals._json_block(TECH_PACK_REPLY).get("rows")), "")

    chart, unmapped = deals.tp_measurements(spec)
    check("the chart is shaped the way the ERP stores it", chart and chart[0].get("m") == 50.0 and chart[0].get("xxs") == 44.0,
          str(chart[:1]))
    check("the point of measure and tolerance are kept", chart[0]["point_of_measure"] == "Chest" and chart[0]["tolerance"] == 0.5,
          str(chart[0]))
    numeric = {"measurements": [{"point_of_measure": "Chest", "values": {"2": 30, "4": 32, "S": 48}}]}
    chart2, unmapped2 = deals.tp_measurements(numeric)
    check("sizes the ERP has no column for are reported", unmapped2 == ["2", "4"], str(unmapped2))
    check("the sizes it does have are charted", chart2[0].get("s") == 48.0, str(chart2[0]))


def t_two_documents():
    print("\n3. One mail, two attachments, two homes")
    be = fake_erp()
    deals.BACKEND = be
    db = get_session()
    bom_bytes = open(FIXTURE, "rb").read()
    calls = []

    def fake_llm(db_, message, timeout=120):
        calls.append(message[:40])
        return TECH_PACK_REPLY if "_TECHPACK" in message else json.dumps({
            "kind": "bom", "style_no": "Z1001-A10-100", "rows": [
                {"item_code": "U70", "material_type": "Fabric", "description": "(Self) 100% LYOCELL",
                 "uom": "Yard", "consumption": 1.47},
                {"item_code": "BT234", "material_type": "Trim", "description": "BUTTON 18L", "uom": "Nos", "consumption": 1}]})

    saved = ai_nextsteps._llm
    ai_nextsteps._llm = fake_llm
    try:
        tp_bytes = TECH_PACK_TEXT.encode()
        atts = [{"filename": "Z1001-A10-100_BOM.xls", "data": bom_bytes},
                {"filename": "Z1001-A10-100_TECHPACK.txt", "data": tp_bytes}]
        info = deals.read_inquiry("Enquiry - Z1001", "Please cost the attached style. 500 pcs.", atts, deals.product_types())
        info = deals.read_with_model(db, info, atts)
    finally:
        ai_nextsteps._llm = saved
    st = (info.get("styles") or [{}])[0]
    check("the mail was read by the model", info.get("read_by_model") is True)
    check("both files were sent to it", len(calls) == 2, str(calls))
    check("the BOM produced material lines", len(st.get("bom") or []) == 2, str(len(st.get("bom") or [])))
    check("the tech pack produced a specification", bool(st.get("spec")), str(st.get("spec"))[:80])
    check("the specification carries the chart", len((st.get("spec") or {}).get("measurements") or []) == 2)
    check("the two sources are named apart", st.get("bom_file", "").endswith("(read by the model)")
          and (st.get("spec") or {}).get("source", "").endswith("_TECHPACK.txt"), f"{st.get('bom_file')} / {st.get('spec', {}).get('source')}")
    check("the style fields were filled", st.get("style_name", "").startswith("1 POCKET") and st.get("sizes") ==
          ["XXS", "XS", "S", "M", "L", "XL", "XXL"], f"{st.get('style_name')} {st.get('sizes')}")


def t_register_sends_the_spec():
    print("\n4. The specification reaches the Tech Pack, and only there")
    be = fake_erp()
    deals.BACKEND = be
    db = get_session()
    d = deals.create_manual(db, ADMIN, customer="EMJ APPAREL GROUP, LLC", title="Two documents",
                            contact_email="jane@acme-apparel.test")
    styles = json.loads(d.styles or "[]")
    spec = deals.spec_from_ai(TECH_PACK_REPLY, "Z1001-A10-100", ["Woven Top"])
    styles[0].update({"style_no": "Z1001-A10-100", "product_type": "Woven Top", "qty": 500,
                      "style_name": spec["style_name"], "sizes": spec["sizes"], "colour": "CLCPW",
                      "fabric": spec["fabric"], "spec": spec,
                      "bom": [{"item_code": "U70", "material_type": "Fabric", "description": "(Self) 100% LYOCELL",
                               "uom": "Yard", "consumption": 1.47}]})
    d.styles = json.dumps(styles)
    db.commit()
    out = deals.register(db, ADMIN, d.id)
    s = json.loads(out.styles or "[]")[0]
    tp = be.get_doc("Tech Pack", s["tech_pack"]) or {}
    check("a Tech Pack was made", bool(s.get("tech_pack")), str(s.get("tech_pack")))
    check("the measurement chart is on it", len(tp.get("measurements") or []) == 2, str(tp.get("measurements"))[:80])
    row = (tp.get("measurements") or [{}])[0]
    check("the chart is per point of measure and per size", row.get("point_of_measure") == "Chest" and row.get("m") == 50.0,
          str(row))
    check("construction notes are on it", "patch pocket" in (tp.get("construction_notes") or ""), str(tp.get("construction_notes"))[:60])
    check("wash & care is on it", "Machine wash" in (tp.get("wash_care") or ""), str(tp.get("wash_care"))[:40])
    check("packing notes are on it", "polybag" in (tp.get("packing_notes") or ""), str(tp.get("packing_notes"))[:40])
    check("the size range is on it", tp.get("size_range") == "XXS-XXL", str(tp.get("size_range")))
    check("the BOM lines are still on the Buyer BOM tab", len(tp.get("materials") or []) == 1, str(tp.get("materials"))[:80])
    check("the timeline says where the pack came from", any("measurement row" in w for w in (s.get("warnings") or [])),
          str(s.get("warnings")))


def main():
    if not os.path.isfile(FIXTURE):
        print(f"SKIP — the fixture is missing ({FIXTURE})")
        return 0
    print("A mail with a Tech Pack AND a BOM")
    t_control_chars()
    t_spec_from_ai()
    t_two_documents()
    t_register_sends_the_spec()
    print("\n" + "=" * 70)
    if _FAIL:
        print(f"❌ {len(_FAIL)} failed: {_FAIL}")
        return 1
    print(f"✅ {_PASS} assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
