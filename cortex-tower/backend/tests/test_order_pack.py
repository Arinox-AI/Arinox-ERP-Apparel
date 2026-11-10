"""Step 8 of the Order page (order_pack), on a seeded in-memory ERP with the ERP scripts stubbed.   Run from backend/:  python3 tests/test_order_pack.py   Synthetic data only."""
import json
import os
import re
import sys
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
os.environ["DB_PATH_OVERRIDE"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["KOGO_AUTH_VERIFIED"] = "1"
os.environ["USER_EMAIL"] = "buy@test.local"
os.environ["USER_NAME"] = "Buyer"
os.environ["USER_IS_ADMIN"] = "1"

from database import get_session, init_db  # noqa: E402
init_db()
import deals  # noqa: E402
import erp  # noqa: E402
import functions  # noqa: E402
import guardrails  # noqa: E402
import order_pack as P  # noqa: E402
from tsr.fake import FakeBackend  # noqa: E402

erp._base_key = lambda: "https://erp.test:9446"
erp._DESK_PREFIX = ("https://erp.test:9446", "desk")
N = {"ok": 0, "bad": 0}


def check(label, cond, extra=""):
    N["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", label, extra)


F = functions.FUNCTIONS
db = get_session()
CALLS = []
SUMMARY = [{"colour": "Navy", "size": "M", "order_qty": 600, "FIN_A": 500, "SAMPLE_OUT": 4, "PACKED": 96},
           {"colour": "Navy", "size": "L", "order_qty": 400, "FIN_A": 400, "SAMPLE_OUT": 0, "PACKED": 0}]
PLAN = [{"carton_from": 1, "carton_to": 10, "tail": 0, "contents": [["Navy", "M", 24]]}, {"carton_from": 11, "carton_to": 21, "tail": 0, "contents": [["Navy", "L", 24]]},
        {"carton_from": 22, "carton_to": 22, "tail": 1, "contents": [["Navy", "L", 10]]}]
RAISE = {"gen": None}


def fake_read(me, method, params=None):
    CALLS.append((method, params))
    if method == "arinox_production_card_get_summary":
        return {"card": "PC-1", "rows": SUMMARY}
    if method == "arinox_packing_list_generate_cartons":
        if RAISE["gen"]:
            raise RuntimeError(RAISE["gen"])
        cs = [{"carton_from": r["carton_from"], "carton_to": r["carton_to"], "tail": r["tail"]} for r in PLAN]
        ct = [{"carton_from": r["carton_from"], "colour": c[0], "size": c[1], "qty_per_carton": c[2]} for r in PLAN for c in r["contents"]]
        return {"arinox_doc": {"cartons": cs, "contents": ct}, "rows": len(PLAN), "plan": PLAN}
    if method == "arinox_final_inspection_pick_cartons":
        return {"arinox_doc": {"cartons_picked": [{"packing_list": "PL-1", "carton_no": 3}], "draw_seed": int((params or {}).get("seed") or 777)}, "picked": 1}
    raise AssertionError(method)


P.read_script = fake_read
W = []
deals._ex = lambda db_, me, req: W.append(req) or {"ok": True}

be = FakeBackend()
be.seed("Sales Order", "SO-1", docstatus=1, customer="Acme Apparel Co", company="Demo Co", items=[])
be.seed("Production Card", "PC-1", sales_order="SO-1", docstatus=1, status="In Sewing", style_item="ST1", style_no="ST1", line="Line 1")
be.seed("Packing List", "PL-1", sales_order="SO-1", production_card="PC-1", docstatus=1, status="Open", pack_type="Solid Colour Solid Size", total_cartons=22, total_pieces=500, final_inspection="FI-1")
be.seed("Packing List", "PL-2", sales_order="SO-1", production_card="PC-1", docstatus=0, status="Open", total_cartons=2, total_pieces=48)
be.seed("Final Inspection", "FI-1", sales_order="SO-1", docstatus=1, result="Accepted", computed_result="Accepted", major_found=1, major_ac=2, major_re=3, minor_found=0, minor_ac=5, minor_re=6,
        critical_found=0, critical_ac=0, critical_re=1, lots=[{"doctype": "Final Inspection Lot", "packing_list": "PL-1"}])
be.seed("Final Inspection", "FI-2", sales_order="SO-1", docstatus=1, result="Rejected", computed_result="Rejected", major_found=4, major_ac=2, major_re=3, lots=[{"doctype": "Final Inspection Lot", "packing_list": "PL-2"}])
be.seed("Needle Detector Log", "ND-1", line="Line 1", check_date=date.today().isoformat(), result="Fail", rescan_done=0)
deals.BACKEND = be

# 1 · pure arithmetic
rows = [{"colour": "Navy", "size": "M", "order_qty": 240, "packable": 240}, {"colour": "Navy", "size": "L", "order_qty": 260, "packable": 400}]
s = P.summarise_plan(PLAN, rows)
r = {(x["colour"], x["size"]): x for x in s["rows"]}
check("cartons and pieces per size from the carton rows", r[("Navy", "M")]["cartons"] == 10 and r[("Navy", "M")]["pieces"] == 240 and r[("Navy", "L")]["cartons"] == 12 and r[("Navy", "L")]["pieces"] == 11 * 24 + 10, s)
check("totals against the order", s["cartons"] == 22 and s["pieces"] == 514 and s["order_qty"] == 500 and s["pct_of_order"] == 102.8, s)
check("a size planned above what is packable is flagged", P.summarise_plan([{"carton_from": 1, "carton_to": 11, "contents": [["Navy", "M", 24]]}], rows)["rows"][1]["over"] is True)
check("empty plan: zero pieces, nothing over", P.summarise_plan([], rows)["pieces"] == 0 and not P.summarise_plan([], rows)["any_over"])
a = P.aql_view({"major_found": 3, "major_ac": 2, "major_re": 3, "minor_found": 1, "minor_ac": 5, "critical_found": 0, "critical_ac": 0, "computed_result": "Rejected", "result": ""})
check("AQL view: a class above its accept number is not within the plan", a["classes"]["major"]["ok"] is False and a["within_plan"] is False and a["verdict"] == "Rejected", a)

# 2 · the read
o = F["order_pack_get"](db=db, sales_order="SO-1")
check("read ok; matrix from the ledger with what is still packable", o["ok"] and o["matrix"][0]["packable"] == 400 and o["matrix"][1]["packable"] == 400 and o["summary"]["order_qty"] == 1000, o["matrix"])
check("packed = submitted lists only; cartons counted", o["summary"]["packed"] == 500 and o["summary"]["cartons"] == 22 and o["summary"]["lists_submitted"] == 1, o["summary"])
pl = {p["name"]: p for p in o["packing_lists"]}
check("a submitted list without a final inspection could be inspected; one already in an inspection could not", pl["PL-1"]["can_inspect"] is False and pl["PL-1"]["inspections"] == ["FI-1"] and pl["PL-2"]["can_inspect"] is False, pl)
fi = {f["name"]: f for f in o["inspections"]}
check("AQL result per inspection", fi["FI-1"]["aql"]["within_plan"] and not fi["FI-2"]["aql"]["within_plan"] and fi["FI-2"]["lots"] == ["PL-2"], fi)
check("accepted inspection counted; the rejected one does not cancel it", o["summary"]["inspection_passed"] is True and o["summary"]["inspection_rejected"] is False)
check("needle: a failed check today without a rescan is flagged", o["summary"]["needle_today"] and o["summary"]["needle_failed"], o["summary"])
check("no order given", F["order_pack_get"](db=db, sales_order="")["ok"] is False)

# 3 · the plan (read only)
W.clear()
kw = dict(sales_order="SO-1", card="PC-1", pack_type="Solid Colour Solid Size", pcs_per_carton=24)
r = F["order_pack_plan"](db=db, **kw)
check("plan: the ERP's carton rows set against the order", r["ok"] and r["summary"]["cartons"] == 22 and r["summary"]["rows"][0]["packable"] == 400, r)
check("plan writes nothing", not W)
check("zero pieces per carton refused", not F["order_pack_plan"](db=db, **{**kw, "pcs_per_carton": 0})["ok"])
check("an unknown pack type refused", not F["order_pack_plan"](db=db, **{**kw, "pack_type": "Loose"})["ok"])
check("an assorted pack without a ratio refused", not F["order_pack_plan"](db=db, **{**kw, "pack_type": "Assorted"})["ok"])
r = F["order_pack_plan"](db=db, **{**kw, "pack_type": "Solid Colour Assorted Size", "ratios": [{"size": "M", "pieces_per_pack": 2}, {"size": "L", "pieces_per_pack": 4}]})
check("a ratio pack passes the ratio rows to the ERP", r["ok"] and json.loads(CALLS[-2][1]["doc"])["ratios"] == [{"colour": None, "size": "M", "pieces_per_pack": 2}, {"colour": None, "size": "L", "pieces_per_pack": 4}], CALLS[-2])
RAISE["gen"] = "Nothing is available to pack: finish pieces into A-grade first."
r = F["order_pack_plan"](db=db, **kw)
check("zero packable: the ERP's own sentence comes back, not a crash", r["ok"] is False and "Nothing is available" in r["error"], r)
RAISE["gen"] = None
check("no card", not F["order_pack_plan"](db=db, sales_order="SO-1", card="", pack_type="Assorted", pcs_per_carton=4)["ok"])

# 4 · pre-fill (the documents are made in the generic form)
p = F["order_prefill_pack"](db=db, sales_order="SO-1", kind="packing", **{k: v for k, v in kw.items() if k != "sales_order"})
i = p["initial"]
check("packing list: cartons and contents from the ERP, header from the card and order", p["ok"] and p["doctype"] == "Packing List" and len(i["cartons"]) == 3 and len(i["contents"]) == 3 and i["production_card"] == "PC-1"
      and i["sales_order"] == "SO-1" and i["customer"] == "Acme Apparel Co" and i["pcs_per_carton"] == 24, p)
RAISE["gen"] = "Nothing is available to pack: finish pieces into A-grade first."
check("packing list with nothing packable refused", not F["order_prefill_pack"](db=db, sales_order="SO-1", kind="packing", card="PC-1", pack_type="Solid Colour Solid Size", pcs_per_carton=24)["ok"])
RAISE["gen"] = None
p = F["order_prefill_pack"](db=db, sales_order="SO-1", kind="inspection", packing_lists=["PL-1"], seed=42)
check("inspection: the lot, the drawn cartons and the seed kept", p["ok"] and p["doctype"] == "Final Inspection" and p["initial"]["lots"] == [{"packing_list": "PL-1"}] and p["initial"]["draw_seed"] == 42
      and p["initial"]["inspection_type"] == "Final" and p["initial"]["production_card"] == "PC-1", p)
check("inspection: a draft packing list refused", not F["order_prefill_pack"](db=db, sales_order="SO-1", kind="inspection", packing_lists=["PL-2"])["ok"])
check("inspection: no lot refused", not F["order_prefill_pack"](db=db, sales_order="SO-1", kind="inspection", packing_lists=[])["ok"])
be.seed("Packing List", "PL-X", sales_order="SO-OTHER", production_card="PC-9", docstatus=1)
check("inspection: another order's list refused", not F["order_prefill_pack"](db=db, sales_order="SO-1", kind="inspection", packing_lists=["PL-X"])["ok"])
p = F["order_prefill_pack"](db=db, sales_order="SO-1", kind="needle")
check("needle: today, the card's line, Pass", p["ok"] and p["initial"]["line"] == "Line 1" and p["initial"]["result"] == "Pass" and p["initial"]["check_date"] == date.today().isoformat(), p)
check("a kind that does not exist is refused", not F["order_prefill_pack"](db=db, sales_order="SO-1", kind="x")["ok"])
check("nothing was written by any pre-fill or plan", not W)

# 5 · roles and structure
for dt, role, ok in (("Packing List", "Shipping", True), ("Packing List", "QC", True), ("Packing List", "Accounts", False), ("Final Inspection", "QC", True), ("Final Inspection", "Shipping", False),
                     ("Needle Detector Log", "Production", True), ("Needle Detector Log", "Accounts", False)):
    try:
        P.need_dt({"roles": [role]}, dt, "x"); got = True
    except guardrails.Denied:
        got = False
    check(f"{role} {'may' if ok else 'may not'} write {dt}", got == ok)
src = open(os.path.join(os.path.dirname(HERE), "order_pack.py")).read()
check("the module never writes through a backend or the pipeline itself", not re.search(r"\b(?:be|backend)\.(insert|save|submit|cancel|delete|set_value)\(", src) and "deals._ex" not in src)
check("no idem_key", "idem_key" not in src)
check("submitting a packing list and a final inspection posts the ledger: risky for the packing list", guardrails.classify("submit", "Packing List") == "risky")
print(f"\n{'✅' if not N['bad'] else '❌'} {N['ok']} assertions passed, {N['bad']} failed")
sys.exit(1 if N["bad"] else 0)
