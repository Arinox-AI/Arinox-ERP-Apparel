#!/usr/bin/env python3
"""The costing sheet is the factory's own worksheet, kept as a module of this app (2026-11-07).

The user, naming the file that settled it: *"APPAREL_COSTING_DETAILED_REVISED ... it has the templates of all the costing,
you just have one more page where in future if you want to tweak price, add more stuff you can add, and from this, one
button click and you can see all your costing put."*

So the sheet is the workbook's **DETAILED COSTING** page, line for line:

* **already there** — opening a style's sheet seeds it from `models_costing.TEMPLATE`: the header block, 18 raw material
  rows (including FABRIC EXPORT / IMPORT COST PER METER), 5 processing charges with APPLY 1/0, 6 percentage expenses and
  profit. Material lines take their usage from the buyer's BOM when one arrived, so the lines already say what each one
  costs per piece.
* **add anything by hand** — a line somebody adds stays on the sheet, after the template rows.
* **saved in the app's database** — `costing_sheet` + `costing_line` tables, one sheet per style.
* **the workbook's arithmetic** (`costing_sheet.compute`): usage × (1 + wastage) × rate; the fabric export/import lines
  priced on the total fabric metres including wastage; the carton at 1 / pcs-per-carton; percentages on the product cost;
  profit on the total cost; FOB per piece in USD **and VND**; order value. Section 2 checks the numbers against the
  workbook's own sample inputs (FOB 14.37478725 for the sheet as it ships).
* **one click transfers the prices** into the ERP Cost Sheet (draft), and the fabric export/import lines travel as the ERP's
  `Fabric Export Cost` / `Fabric Import Cost` cost heads, because that is what they are in the ERP.

No network: the model is stubbed where used, the ERP is the fake Arinox site.

Run:  python3 tests/test_costing_sheet.py
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
import costing_sheet                                                         # noqa: E402
import deals                                                                 # noqa: E402
from deal_harness import fake_erp, ADMIN                                     # noqa: E402
from models_costing import TEMPLATE, CostingLineModel, CostingSheetModel     # noqa: E402

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


def _deal(db):
    be = fake_erp()
    deals.BACKEND = be
    d = deals.create_manual(db, ADMIN, customer="EMJ APPAREL GROUP, LLC", title="Cost it", contact_email="b@acme.test")
    styles = json.loads(d.styles or "[]")
    styles[0].update({"style_no": "Z1001-A10-100", "product_type": "Woven Top", "qty": 500, "sizes": ["S", "M", "L"],
                      "bom": [{"item_code": "U70", "material_type": "Fabric", "description": "(Self) 100% COTTON",
                               "uom": "Yard", "consumption": 1.4},
                              {"item_code": "U71", "material_type": "Fabric", "description": "(Content) 100% COTTON",
                               "uom": "Yard", "consumption": 0.1},
                              {"item_code": "BT234", "material_type": "Trim", "description": "BUTTON 18L",
                               "uom": "Nos", "consumption": 7},
                              {"item_code": "FZ900", "material_type": "Fusing", "description": "FUSE #9085",
                               "uom": "Yard", "consumption": 0.24}]})
    d.styles = json.dumps(styles)
    db.commit()
    out = deals.register(db, ADMIN, d.id)
    s = json.loads(out.styles or "[]")[0]
    deals.cost_open(db, ADMIN, out.id, s["key"])
    return out, s


def _by_tpl(lines):
    return {ln.tpl: ln for ln in lines if ln.tpl}


def t_seeded():
    print("\n1. The sheet is there, and it is the workbook's page")
    db = get_session()
    d, s = _deal(db)
    sheet, lines, totals = costing_sheet.open_sheet(db, d, s)
    check("a sheet exists without anyone uploading anything", sheet.id and sheet.deal_id == d.id)
    tpl = _by_tpl(lines)
    check("every template row is on the sheet", len(tpl) == len(TEMPLATE), f"{len(tpl)} of {len(TEMPLATE)}")
    check("the sheet opens like the workbook: 18 raw material rows", sum(1 for l in lines if l.kind == "material"
          and l.tpl and l.tpl.startswith("M")) == 18)
    check("then 5 processing charges", sum(1 for l in lines if l.kind == "processing") == 5)
    check("then 6 expenses and profit", sum(1 for l in lines if l.kind == "expense") == 7)
    check("MAIN FABRIC is the first line", lines[0].label == "MAIN FABRIC", lines[0].label)
    check("the fabric export / import rows are material rows, priced by rule",
          tpl["M03"].kind == "material" and tpl["M03"].rule == "fabric_metres" and tpl["M04"].rule == "fabric_metres")
    check("the carton is priced by the pcs-per-carton rule", tpl["M11"].rule == "per_carton")
    check("four OTHERS rows, like the workbook", sum(1 for l in lines if l.label == "OTHERS") == 4)
    check("the expense percentages are the template's own",
          [round(tpl[k].share or 0, 4) for k in ("E01", "E02", "E03", "E04", "E05", "E06", "E07")]
          == [0.03, 0.01, 0.01, 0.02, 0.15, 0.0, 0.15],
          str([tpl[k].share for k in ("E01", "E02", "E03", "E04", "E05", "E06", "E07")]))
    check("only making charges apply to start with (workbook APPLY 1/0)",
          tpl["P01"].apply and not any(tpl[k].apply for k in ("P02", "P03", "P04", "P05")))
    check("the order quantity comes from the style", sheet.order_qty == 500, str(sheet.order_qty))
    check("MAIN FABRIC took the self fabric's usage", (tpl["M01"].usage or 0) == 1.4, str(tpl["M01"].usage))
    check("the contrast fabric line took the other fabric", (tpl["M02"].usage or 0) == 0.1, str(tpl["M02"].usage))
    check("a BOM line is used once (button not counted twice)", (tpl["M14"].usage or 0) == 7, str(tpl["M14"].usage))
    check("the sheet is exactly the template - nothing invented on it",
          not [l.label for l in lines if l.tpl is None], str([l.label for l in lines if l.tpl is None]))
    check("the ERP cost heads are on the charge lines", tpl["P01"].cost_head == "Stitching (CMT)", tpl["P01"].cost_head)
    check("the buyer is on the sheet", bool(sheet.buyer), str(sheet.buyer))
    reopened = db.query(CostingSheetModel).filter(CostingSheetModel.deal_id == d.id).count()
    check("opening it again reuses the same sheet (it is stored)", reopened == 1, str(reopened))
    check("opening it again changes nothing", [l.id for l in reopen(db, d, s)] == [l.id for l in lines])


def reopen(db, d, s):
    _sheet, lines, _t = costing_sheet.open_sheet(db, d, s)
    return lines


def t_workbook():
    print("\n2. The arithmetic is the workbook's (its own sample inputs)")
    db = get_session()
    d, s = _deal(db)
    sheet, lines, _ = costing_sheet.open_sheet(db, d, s)
    sheet.order_qty = 5500
    sheet.pcs_per_carton = 40
    sheet.vnd_per_usd = 25000
    tpl = _by_tpl(lines)
    rates = {"M01": (0.6, 0.05, 3.0), "M02": (0.6, 0.05, 3.0), "M03": (None, 0.0, 0.25), "M04": (None, 0.0, 0.25),
             "M05": (1, 0, 0.05), "M06": (1, 0, 0.05), "M07": (2, 0, 0.05), "M08": (1, 0, 0.05), "M09": (6, 0, 0.02),
             "M10": (200, 0, 0.001), "M11": (None, 0, 0.15), "M12": (0.5, 0, 0.1), "M13": (1, 0, 0.1), "M14": (1, 0, 0.1)}
    for key, (usage, waste, rate) in rates.items():
        tpl[key].usage, tpl[key].wastage_pct, tpl[key].rate = usage, waste, rate
    for key in ("M15", "M16", "M17", "M18"):
        tpl[key].usage, tpl[key].wastage_pct, tpl[key].rate = 0.01, 0, 0.3
    tpl["P01"].rate = 5.0
    for ln in lines:
        if ln.tpl is None:
            ln.apply = False                       # the test is the workbook, which has no extra lines
    db.commit()
    t = costing_sheet.compute(sheet, lines)

    def close(a, b, tol=1e-6):
        return a is not None and abs(a - b) < tol

    check("fabric metres = both fabrics incl. wastage (workbook C19)", close(t["fabric_metres"], 1.26), str(t["fabric_metres"]))
    check("total cost of raw materials = 5.24575", close(t["raw_material"], 5.24575), str(t["raw_material"]))
    check("the export/import lines are 1.26 m × 0.25 each",
          close(next(r["cost_per_pc"] for r in t["rows"] if r["label"].startswith("FABRIC EXPORT")), 0.315)
          and close(next(r["cost_per_pc"] for r in t["rows"] if r["label"].startswith("FABRIC IMPORT")), 0.315))
    check("the carton is 1/40 × 0.15", close(next(r["cost_per_pc"] for r in t["rows"] if r["label"] == "CARTON"), 0.00375),
          str(next(r["cost_per_pc"] for r in t["rows"] if r["label"] == "CARTON")))
    check("product cost = 10.24575", close(t["product_cost"], 10.24575), str(t["product_cost"]))
    check("other expenses = 2.254065 (3+1+1+2+15 % of the product cost)", close(t["other_expenses"], 2.254065),
          str(t["other_expenses"]))
    check("FOB before profit = 12.499815", close(t["fob_before_profit"], 12.499815), str(t["fob_before_profit"]))
    check("profit = 15% of that, 1.87497225", close(t["profit"], 1.87497225), str(t["profit"]))
    check("FOB per pc USD = 14.37478725", close(t["fob_usd"], 14.37478725), str(t["fob_usd"]))
    check("FOB per pc VND = × 25,000", close(t["fob_vnd"], 359369.68125, 1e-4), str(t["fob_vnd"]))
    check("order value = FOB × 5,500 pcs", close(t["order_value"], 79061.329875, 1e-4), str(t["order_value"]))


def t_saved_in_db():
    print("\n3. What a person types is stored, not recomputed from a file")
    db = get_session()
    d, s = _deal(db)
    sheet, lines, _ = costing_sheet.open_sheet(db, d, s)
    rows = [ln.to_dict() for ln in lines]
    fabric = next(r for r in rows if r["label"] == "MAIN FABRIC")
    fabric["rate"] = 3.75
    fabric["usage"] = 1.62
    rows.append({"kind": "material", "label": "EMBROIDERY THREAD", "material_type": "Thread", "usage": 12,
                 "uom": "MTR", "rate": 0.02, "apply": True})
    sheet2, lines2, totals = costing_sheet.save_sheet(db, d, s, {"pcs_per_carton": 24, "profit_pct": 0.2,
                                                                 "vnd_per_usd": 25000, "buyer": "EMJ",
                                                                 "fob_port": "HCM",
                                                                 "signoffs": {"FIRST COSTING DONE BY":
                                                                              {"name": "Nanda", "date": "2026-11-07"}}},
                                                       rows)
    check("the header is stored with the edit", sheet2.pcs_per_carton == 24 and sheet2.profit_pct == 0.2
          and sheet2.vnd_per_usd == 25000 and sheet2.buyer == "EMJ" and sheet2.fob_port == "HCM",
          f"{sheet2.pcs_per_carton} / {sheet2.profit_pct} / {sheet2.vnd_per_usd}")
    check("the sign-off boxes are stored", sheet2.signoffs_dict()["FIRST COSTING DONE BY"]["name"] == "Nanda",
          str(sheet2.signoffs_dict()))
    profit_line = next(l for l in lines2 if l.cost_head == "Profit")
    check("the profit % on the header is the PROFIT line's share", round(profit_line.share, 4) == 0.2, str(profit_line.share))
    fabric2 = next(l for l in lines2 if l.label == "MAIN FABRIC")
    check("the rate survived the round trip", fabric2.rate == 3.75 and fabric2.usage == 1.62,
          f"{fabric2.rate} / {fabric2.usage}")
    added = next((l for l in lines2 if l.label == "EMBROIDERY THREAD"), None)
    check("a line added by hand is kept", added is not None and added.tpl is None, str(added and added.to_dict()))
    check("and it sits after the template rows", added is not None and added.seq > len(TEMPLATE), str(added and added.seq))
    check("and the totals were recomputed", totals["raw_material"] > 0, str(totals["raw_material"]))
    db.expire_all()
    again = db.query(CostingLineModel).filter(CostingLineModel.sheet_id == sheet2.id,
                                              CostingLineModel.label == "MAIN FABRIC").first()
    check("it is in the database, not in memory", again is not None and again.rate == 3.75, str(again))
    rows3 = [r for r in rows if r["label"] != "EMBROIDERY THREAD"]
    _s, lines3, _t = costing_sheet.save_sheet(db, d, s, {}, rows3)
    check("a line removed in the screen is removed from the sheet", not any(l.label == "EMBROIDERY THREAD" for l in lines3))


def t_template_sync():
    print("\n4. A sheet stored against an older template is brought into line, losing nothing")
    db = get_session()
    d, s = _deal(db)
    sheet, lines, _ = costing_sheet.open_sheet(db, d, s)
    # rewrite the sheet the way the previous template stored it: export/import as charges, a DEPRECIATION row,
    # no slots at all, and a rate somebody typed
    for ln in lines:
        ln.tpl = None
        if ln.label.startswith("FABRIC EXPORT") or ln.label.startswith("FABRIC IMPORT"):
            ln.kind, ln.from_fabric, ln.rule, ln.material_type, ln.uom = "processing", True, None, None, "PCS"
        if ln.label == "MAIN FABRIC":
            ln.rate = 4.25                                   # a real price, entered by a person
    db.add(CostingLineModel(sheet_id=sheet.id, seq=99, kind="expense", label="DEPRECIATION", cost_head="Depreciation",
                            share=0.0, apply=True))
    db.commit()
    costing_sheet.sync_template(db, sheet)
    lines = costing_sheet._sorted_lines(db, sheet)
    tpl = _by_tpl(lines)
    check("every row found its slot again by name", len(tpl) == len(TEMPLATE), f"{len(tpl)} of {len(TEMPLATE)}")
    check("the export line is a material row priced by the fabric metres again",
          tpl["M03"].kind == "material" and tpl["M03"].rule == "fabric_metres" and tpl["M03"].uom == "MTR")
    check("the rate a person typed is still there", tpl["M01"].rate == 4.25, str(tpl["M01"].rate))
    check("a retired row nothing was entered on is gone", not any(l.label == "DEPRECIATION" for l in lines))
    check("the template rows are in the workbook's order", [l.tpl for l in lines if l.tpl] == [x["tpl"] for x in TEMPLATE])
    snapshot = [(l.id, l.tpl, l.seq, l.rate, l.share, l.apply) for l in lines]
    costing_sheet.sync_template(db, sheet)
    again = [(l.id, l.tpl, l.seq, l.rate, l.share, l.apply) for l in costing_sheet._sorted_lines(db, sheet)]
    check("syncing twice changes nothing (idempotent)", snapshot == again)


def t_list():
    print("\n5. The Costing page has a list to open")
    db = get_session()
    d, s = _deal(db)
    costing_sheet.open_sheet(db, d, s)
    rows = costing_sheet.list_sheets(db)
    mine = next((r for r in rows if r["deal_id"] == d.id and r["style_key"] == s["key"]), None)
    check("the style is listed", mine is not None, str(len(rows)))
    check("with the sheet it already has", mine and mine["sheet_id"] and mine["style_no"] == "Z1001-A10-100", str(mine))
    check("and its FOB / order value", mine and mine["fob_usd"] is not None and mine["order_value"] is not None,
          str(mine and (mine["fob_usd"], mine["order_value"])))
    d2 = deals.create_manual(db, ADMIN, customer="SECOND BUYER", title="No sheet yet", contact_email="c@acme.test")
    rows = costing_sheet.list_sheets(db)
    check("a style with no sheet yet is listed too, so it can be started",
          any(r["deal_id"] == d2.id and r["sheet_id"] is None for r in rows))


def t_transfer():
    print("\n6. One click transfers the prices into the ERP")
    db = get_session()
    d, s = _deal(db)
    sheet, lines, _ = costing_sheet.open_sheet(db, d, s)
    tpl = _by_tpl(lines)
    tpl["M01"].rate = 4.0
    tpl["M03"].rate = 0.25
    tpl["P01"].rate = 5.0
    for key in ("E01", "E02", "E03", "E04", "E05"):
        tpl[key].share = 0.0
    tpl["E05"].share = 0.15
    for ln in lines:
        if ln.tpl and ln.tpl.startswith("E"):
            ln.apply = ln.tpl in ("E05", "E07")
        if ln.tpl and ln.tpl.startswith("P"):
            ln.apply = ln.tpl == "P01"
    db.commit()
    _s, _l, totals = costing_sheet.open_sheet(db, d, s)
    out = deals.cost_sheet_transfer(db, ADMIN, d.id, s["key"])
    cs = out["cost_sheet"]
    fabric = next((m for m in cs["materials"] if "MAIN FABRIC" in str(m.get("description") or "").upper()), None)
    check("the sheet's fabric rate reached the ERP line", fabric is not None and fabric.get("rate") == 4.0, str(fabric)[:120])
    chg = {str(c.get("cost_head")): c for c in cs["charges"]}
    check("CMT reached its cost head", (chg.get("Stitching (CMT)") or {}).get("rate") == 5.0, str(chg.get("Stitching (CMT)")))
    check("a percentage reached its cost head", (chg.get("Overhead") or {}).get("rate") == 0.15, str(chg.get("Overhead")))
    check("the fabric export cost travels as the ERP's own cost head, not as a material line",
          (chg.get("Fabric Export Cost") or {}).get("rate") == 0.25
          and not any("EXPORT" in str(m.get("description") or "").upper() for m in cs["materials"]),
          str(chg.get("Fabric Export Cost"))[:120])
    check("the sheet's FOB became the quoted price", cs["totals"]["quoted_price"] == totals["fob_usd"],
          f"{cs['totals']['quoted_price']} vs {totals['fob_usd']}")
    check("the ERP computed a price", (cs["totals"]["computed_price"] or 0) > 0, str(cs["totals"]["computed_price"]))
    check("it stayed a draft", cs["docstatus"] == 0, str(cs["docstatus"]))
    check("the sheet remembers it was transferred", out["sheet"]["transferred_at"] is not None, str(out["sheet"]["transferred_at"]))
    check("the answer says what it did", out["applied"]["charges_set"] >= 2 and out["applied"]["quoted_price"],
          str(out["applied"]))
    rows = [dict(m) for m in cs["materials"]]
    rows[0]["rate"] = 4.5
    res = deals.cost_save(db, ADMIN, d.id, s["key"], rows, cs["charges"], quoted_price=9.5)
    check("a hand edit after the transfer wins", res["cost_sheet"]["materials"][0]["rate"] == 4.5
          and res["cost_sheet"]["totals"]["quoted_price"] == 9.5, str(res["cost_sheet"]["materials"][0].get("rate")))


def t_prices_to_bom():
    print("\n7. The price kept for an item goes onto that BOM item in one click")
    db = get_session()
    d, s = _deal(db)
    sheet, lines, _ = costing_sheet.open_sheet(db, d, s)
    tpl = _by_tpl(lines)
    check("every material row is tied to the BOM item it covers",
          tpl["M01"].item_code == "U70" and tpl["M02"].item_code == "U71" and tpl["M14"].item_code == "BT234",
          f"{tpl['M01'].item_code} / {tpl['M02'].item_code} / {tpl['M14'].item_code}")
    rows = [ln.to_dict() for ln in lines]
    tpl["M01"].rate = 3.2
    tpl["M02"].rate = 2.9
    tpl["M14"].rate = 0.04
    for r in rows:
        if r["label"] == "MAIN FABRIC":
            r["rate"] = 3.2
        if r["label"] == "TRIM / CONTRAST FABRIC":
            r["rate"] = 2.9
        if r["label"] == "BUTTON":
            r["rate"] = 0.04
    costing_sheet.save_sheet(db, d, s, {}, rows)
    book = {r["item_code"]: r["rate"] for r in costing_sheet.prices(db) if r["item_code"]}
    check("the prices are kept in the app's price book, against the item",
          book.get("U70") == 3.2 and book.get("U71") == 2.9 and book.get("BT234") == 0.04, str(book))
    check("an item's price can be looked up again", costing_sheet.lookup_price(db, "U70", "")["rate"] == 3.2)
    out = deals.apply_prices_to_bom(db, ADMIN, d.id, s["key"])
    check("the click walks the BOM items on the ERP's Cost Sheet", out["items"] >= 4, str(out["items"]))
    check("and puts each item's price on it", out["updated"] >= 3, str(out["updated"]))
    fuse = next((ln for ln in costing_sheet._sorted_lines(db, sheet) if ln.item_code == "FZ900"), None)
    check("a BOM item the named rows have no place for sits in a spare OTHERS row",
          fuse is not None and fuse.label == "OTHERS", str(fuse and fuse.label))
    check("an item with no price is reported, not guessed",
          any("FUSE" in m for m in out["missing"]), str(out["missing"]))
    tpl["M15"].rate = 0.5
    rows2 = [ln.to_dict() for ln in costing_sheet._sorted_lines(db, sheet)]
    costing_sheet.save_sheet(db, d, s, {}, rows2)
    out2 = deals.apply_prices_to_bom(db, ADMIN, d.id, s["key"])
    fus = next((m for m in out2["cost_sheet"]["materials"] if "FUSE" in str(m.get("description"))), {})
    check("its price goes on when one is given", fus.get("rate") == 0.5, str(fus)[:140])
    cs_rows = {str(m.get("description") or ""): m for m in out["cost_sheet"]["materials"]}
    fabric = cs_rows.get("(Self) 100% COTTON") or next((m for k, m in cs_rows.items() if "Self" in k), {})
    check("the fabric item carries the sheet's price", fabric.get("rate") == 3.2, str(fabric)[:140])
    check("its consumption is untouched", fabric.get("consumption") == 1.4, str(fabric.get("consumption")))
    check("nothing was submitted", out["cost_sheet"]["docstatus"] == 0, str(out["cost_sheet"]["docstatus"]))
    again = deals.apply_prices_to_bom(db, ADMIN, d.id, s["key"])
    check("a second click changes nothing (already applied)", again["updated"] == 0, str(again["updated"]))
    charges = {str(c.get("cost_head")): c for c in out["cost_sheet"]["charges"]}
    check("the click only touches material prices, not the cost heads",
          all(not c.get("rate") for c in charges.values()), str(charges)[:150])


def t_submitted_refused():
    print("\n7. A submitted costing is never overwritten")
    db = get_session()
    d, s = _deal(db)
    cs = deals.cost_open(db, ADMIN, d.id, s["key"])["cost_sheet"]
    charges = [{**c, "not_applicable": 1 if not c.get("rate") else 0} for c in cs["charges"]]
    deals.cost_save(db, ADMIN, d.id, s["key"], cs["materials"], charges, quoted_price=8.0)
    deals.cost_submit(db, ADMIN, d.id, s["key"])
    refused = ""
    try:
        deals.cost_sheet_transfer(db, ADMIN, d.id, s["key"])
    except deals.DealError as e:
        refused = str(e)
    check("transfer to a submitted sheet is refused with a reason", "submitted" in refused.lower(), refused)


def t_import_still_works():
    print("\n8. A sheet somebody sent can still fill this module")
    db = get_session()
    d, s = _deal(db)
    reply = json.dumps({"kind": "costing", "currency": "USD",
                        "materials": [{"label": "MAIN FABRIC", "material_type": "Fabric", "usage": 1.5, "uom": "MTR",
                                       "wastage_pct": 5, "rate": 3.2}],
                        "charges": [{"label": "MAKING CHARGES (CMT)", "cost_head": "Stitching (CMT)", "value": 4.5,
                                     "apply": True},
                                    {"label": "OVERHEADS", "cost_head": "Overhead", "value": 0.12, "apply": True}],
                        "totals": {"profit_pct": 0.18}})
    saved = ai_nextsteps._llm
    ai_nextsteps._llm = lambda db_, msg, timeout=120: reply
    try:
        _d, doc = deals.cost_document_read(db, ADMIN, d.id, s["key"], "sent_costing.txt",
                                           b"MAIN FABRIC 1.5 0.05 3.2\nMAKING 4.5\nOVERHEADS 0.12")
    finally:
        ai_nextsteps._llm = saved
    sheet, lines, totals = costing_sheet.apply_import(db, d, json.loads(deals._get(db, d.id).styles or "[]")[0], doc)
    by = {l.cost_head or l.label: l for l in lines}
    check("the imported usage and rate land on the template's line", by["MAIN FABRIC"].usage == 1.5
          and by["MAIN FABRIC"].rate == 3.2, f"{by['MAIN FABRIC'].usage} / {by['MAIN FABRIC'].rate}")
    check("the imported wastage is a fraction", by["MAIN FABRIC"].wastage_pct == 0.05, str(by["MAIN FABRIC"].wastage_pct))
    check("an imported charge lands on its cost head", by["Stitching (CMT)"].rate == 4.5, str(by["Stitching (CMT)"].rate))
    check("an imported percentage lands as a share", by["Overhead"].share == 0.12, str(by["Overhead"].share))
    check("the profit % came across", sheet.profit_pct == 0.18, str(sheet.profit_pct))
    check("the totals are computed here, not copied", totals["raw_material"] > 0 and totals["fob_usd"] > 0,
          str(totals["fob_usd"]))


def main():
    print("The costing sheet as a module")
    t_seeded()
    t_workbook()
    t_saved_in_db()
    t_template_sync()
    t_list()
    t_transfer()
    t_prices_to_bom()
    t_submitted_refused()
    t_import_still_works()
    print("\n" + "=" * 70)
    if _FAIL:
        print(f"❌ {len(_FAIL)} failed: {_FAIL}")
        return 1
    print(f"✅ {_PASS} assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
