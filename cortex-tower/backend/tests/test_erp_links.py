#!/usr/bin/env python3
"""The ERP links, and the Sales Order that could not be made (2026-11-09).

Two reports, one file.

**"I cannot create a Sales Order through the tower."**  The contract carried the sizes the buyer listed, and the buyer
ordered nothing in XXS and XXL, so those size rows had a quantity of 0. The ERP's make-Sales-Order script turned every
size row into an order line, and Frappe refuses the whole document with *"Row #1: Quantity for Item … cannot be zero"*,
so the tower showed that sentence and no order. Two things are locked down here:

* the tower never sends a zero-quantity line (``deals.make_order``), whatever the ERP's script does — including the old
  script, which is put back into the registry for one test, because a script on the site can be reverted at any time;
* the ERP's own script skips those rows too, so the same document made from the ERP's button works as well.

**"Take me to the ERP takes me to the main page."**  Every address is built in exactly one place (``erp``), and each
deal step names its own page (``deals.erp_status`` → ``by_step`` / ``focus``), so a button opens the Sales Order that
was on screen instead of the ERP's front page.

Run:  python3 tests/test_erp_links.py
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

from database import get_session, init_db                                     # noqa: E402
init_db()
import deals                                                                  # noqa: E402
import erp                                                                    # noqa: E402
import functions                                                              # noqa: E402
import pipeline                                                               # noqa: E402
from deal_harness import fake_erp, ADMIN, COMPANY                             # noqa: E402

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


def pin_site(base="https://erp.test:9446", prefix="desk"):
    """Answer as if the ERP were reachable at ``base`` without touching the network."""
    erp._base_key = lambda: base                      # type: ignore[assignment]
    erp._DESK_PREFIX = (base.rstrip("/"), prefix)


# ───────────────────────── 1. one builder, derived not typed ─────────────────────────

def t_url_builder():
    print("\n1. Every ERP address is built by one function, from the site's own route rule")
    real_base, real_prefix, real_get = erp._base_key, erp._DESK_PREFIX, erp.requests.get
    try:
        pin_site()
        check("a two-word doctype is slugged", erp.doctype_slug("Tech Pack") == "tech-pack", erp.doctype_slug("Tech Pack"))
        check("a one-word doctype too", erp.doctype_slug("Opportunity") == "opportunity")
        check("a three-word doctype keeps every dash", erp.doctype_slug("Price Negotiation") == "price-negotiation")
        check("a document page", erp.doc_url("Sales Order", "SAL-ORD-2026-00083")
              == "https://erp.test:9446/desk/sales-order/SAL-ORD-2026-00083", erp.doc_url("Sales Order", "SAL-ORD-2026-00083"))
        check("a list page", erp.list_url("Sales Contract") == "https://erp.test:9446/desk/sales-contract",
              erp.list_url("Sales Contract"))
        check("url_for prefers the document", erp.url_for("Sales Contract", "SC-1")
              == "https://erp.test:9446/desk/sales-contract/SC-1", erp.url_for("Sales Contract", "SC-1"))
        check("url_for falls back to the list", erp.url_for("Sales Contract", "") == "https://erp.test:9446/desk/sales-contract")
        check("url_for with nothing at all is the desk", erp.url_for() == "https://erp.test:9446/desk")
        check("the desk root is offered", erp.desk_url() == "https://erp.test:9446/desk", erp.desk_url())
        check("no document, no link", erp.doc_url("Tech Pack", "") == "")
        check("a name with a slash is escaped", erp.doc_url("Tech Pack", "TP/1") == "https://erp.test:9446/desk/tech-pack/TP%2F1",
              erp.doc_url("Tech Pack", "TP/1"))
        check("a base with a trailing slash does not double it", erp.doc_url("Opportunity", "X")
              == "https://erp.test:9446/desk/opportunity/X")

        # the desk prefix is ASKED, not assumed: an older site has no /desk at all
        class _R:
            def __init__(self, code, loc=""):
                self.status_code, self.headers = code, {"Location": loc}

        seen = []

        def old_site(url, **kw):
            seen.append(url)
            return _R(404) if url.endswith("/desk") else _R(200)

        erp._DESK_PREFIX = None
        erp.requests.get = old_site               # type: ignore[assignment]
        check("a site without /desk gets /app links", erp.desk_prefix() == "app" and erp.doc_url("Opportunity", "X")
              == "https://erp.test:9446/app/opportunity/X", f"{erp.desk_prefix()} {seen}")

        def new_site(url, **kw):
            return _R(301, "/login?redirect-to=%2Fdesk") if url.endswith("/desk") else _R(200)

        erp._DESK_PREFIX = None
        erp.requests.get = new_site               # type: ignore[assignment]
        check("a site that redirects /desk to the login page keeps /desk", erp.desk_prefix() == "desk")

        def down(url, **kw):
            raise OSError("no route to host")

        erp._DESK_PREFIX = None
        erp.requests.get = down                   # type: ignore[assignment]
        check("an unreachable site still yields a link (the current spelling)", erp.desk_prefix() == "desk",
              erp.desk_prefix())
        check("...and building a link never raises", erp.doc_url("Sales Order", "X").endswith("/desk/sales-order/X"))

        # the old second builder in functions.py must not disagree with this one
        erp._DESK_PREFIX = ("https://erp.test:9446", "desk")
        links = functions._erp_links("Sales Order", "SAL-ORD-2026-00083", 1)
        check("functions._erp_links uses the same builder", links.get("erp_url") == erp.doc_url("Sales Order", "SAL-ORD-2026-00083"),
              str(links))
        check("a batch opens the list, not a random document",
              functions._erp_links("Sales Order", "SAL-ORD-2026-00083", 3).get("erp_url") == erp.list_url("Sales Order"))
        check("no doctype, no links", functions._erp_links("", "X", 1) == {})
    finally:
        erp._base_key, erp._DESK_PREFIX, erp.requests.get = real_base, real_prefix, real_get


# ───────────────────────── 2. each step names its own page ─────────────────────────

def _deal_with(db, refs: dict, styles: list | None = None, stage: str = "inquiry"):
    d = deals.create_manual(db, ADMIN, customer="EMJ APPAREL GROUP, LLC", title="Which ERP page")
    r = d.refs_dict()
    r.update(refs)
    d.refs = json.dumps(r)
    if styles is not None:
        d.styles = json.dumps(styles)
    d.stage = stage
    db.commit()
    return d


def t_step_pages():
    print("\n2. A step's \"open the ERP\" is that step's page - and the list while the document does not exist")
    real_base, real_prefix = erp._base_key, erp._DESK_PREFIX
    try:
        pin_site()
        be = fake_erp()
        deals.BACKEND = be
        db = get_session()
        style = deals.new_style(style_no="Z1001-A10-100", colour="SKY BLUE",
                                tech_pack="TP-2026-00003", cost_sheet="CS-2026-00001")
        d = _deal_with(db, {"opportunity": "CRM-OPP-2026-00003", "quotation": "SAL-QTN-2026-00002"},
                       styles=[style], stage="quoted")
        for dt, name in (("Opportunity", "CRM-OPP-2026-00003"), ("Quotation", "SAL-QTN-2026-00002"),
                         ("Tech Pack", "TP-2026-00003"), ("Cost Sheet", "CS-2026-00001")):
            be.seed(dt, name, docstatus=0)
        out = deals.erp_status(d, db)
        by = out.get("by_step") or {}
        check("the inquiry step opens the Opportunity", by.get("inquiry", {}).get("name") == "CRM-OPP-2026-00003", str(by.get("inquiry")))
        check("the costing step opens the Cost Sheet, not the Tech Pack", by.get("costing", {}).get("name") == "CS-2026-00001",
              str(by.get("costing")))
        check("the quote step opens the Quotation", by.get("quote", {}).get("name") == "SAL-QTN-2026-00002", str(by.get("quote")))
        check("the contract step has no document yet, so it opens the contract LIST",
              by.get("contract", {}).get("url", "").endswith("/desk/sales-contract"), str(by.get("contract")))
        check("the order step opens the Sales Order list", by.get("order", {}).get("url", "").endswith("/desk/sales-order"),
              str(by.get("order")))
        check("the deal is quoted, so the panel points at the Quotation",
              out.get("focus", {}).get("name") == "SAL-QTN-2026-00002", str(out.get("focus")))
        check("every page has a ready-made button label",
              all(p.get("label", "").startswith("Open ") for p in by.values()), str(by))
        check("a list fallback says so in words", by.get("order", {}).get("label") == "Open the sales order list",
              by.get("order", {}).get("label"))
        check("no page is the ERP front page while the deal has documents",
              all(p.get("url") != out.get("base_url") for p in by.values()), str(by))

        # the order is made: the panel and the order/track steps follow it to the Sales Order
        be.seed("Sales Order", "SAL-ORD-2026-00083", docstatus=0, status="Draft")
        d = deals._get(db, d.id)
        r = d.refs_dict()
        r["sales_order"] = "SAL-ORD-2026-00083"
        d.refs, d.stage = json.dumps(r), "order"
        db.commit()
        out = deals.erp_status(d, db)
        check("once ordered, the order step opens the order itself",
              out["by_step"]["order"]["url"].endswith("/desk/sales-order/SAL-ORD-2026-00083"), str(out["by_step"]["order"]))
        check("and the panel follows the deal to the Sales Order", out["focus"]["name"] == "SAL-ORD-2026-00083", str(out["focus"]))
        check("ship & track shows the same order", out["by_step"]["track"]["name"] == "SAL-ORD-2026-00083")

        # an ERP that is not reachable: no page, and the screen falls back to the front page rather than a dead link
        erp._base_key = lambda: ""
        out = deals.erp_status(deals._get(db, d.id), None)
        check("no ERP: no per-step page is invented", out.get("by_step") == {} and out.get("focus") == {}, str(out.get("by_step")))
        check("no ERP: the front-page link is empty too", out.get("base_url") == "")
    finally:
        erp._base_key, erp._DESK_PREFIX = real_base, real_prefix


# ───────────────────────── 3. the Sales Order with a zero-quantity size ─────────────────────────

SIZES = [("XXS", 0), ("XS", 201), ("S", 198), ("M", 200), ("L", 200), ("XL", 200), ("XXL", 0)]


def _seed_contract(be, name="SC-1", style_item="APPAREL-STYLE", colour="Cool Capri Wash"):
    """A signed contract exactly the shape the tower's own create writes: one line, seven size rows, two of them zero."""
    be.seed("Sales Contract", name, customer="EMJ APPAREL GROUP, LLC", company=COMPANY, currency="USD", docstatus=1,
            buyer_po_no="", contract_date="2026-11-07", incoterm="DAP", named_place="Los Angeles",
            items=[{"style_item": style_item, "colour": colour, "qty": 999, "rate": 10.43, "uom": "Nos",
                    "ex_factory_date": "2026-12-08", "etd": "2026-12-14", "in_warehouse_date": "2026-12-17",
                    "tolerance_pct": 0}],
            sizes=[{"style_item": style_item, "colour": colour, "size": z, "qty": q} for z, q in SIZES],
            tolerance_bands=[])


def _deal_with_contract(db, contract="SC-1"):
    d = _deal_with(db, {"sales_contract": contract})
    return d


def t_make_order_skips_empty_sizes():
    print("\n3. A size with no pieces is not an order line (the Sales Order that could not be made)")
    real_base, real_prefix = erp._base_key, erp._DESK_PREFIX
    try:
        pin_site()
        be = fake_erp()
        deals.BACKEND = be
        db = get_session()
        _seed_contract(be)
        d = _deal_with_contract(db)
        out = deals.make_order(db, ADMIN, d.id)
        so_name = out.refs_dict().get("sales_order")
        so = (be.docs.get("Sales Order") or {}).get(so_name) or {}
        rows = so.get("items") or []
        check("the Sales Order is made", bool(so_name) and out.stage == "order", f"{so_name} {out.stage}")
        check("it has one row per size that was actually ordered", len(rows) == 5, f"{len(rows)} rows")
        check("no row has a zero quantity", all(float(r.get("qty") or 0) > 0 for r in rows), [r.get("qty") for r in rows])
        check("the sizes that were dropped are not on it", not [r for r in rows if r.get("apparel_size") in ("XXS", "XXL")],
              [r.get("apparel_size") for r in rows])
        check("the quantities are the buyer's, untouched", [float(r.get("qty")) for r in rows] == [201.0, 198.0, 200.0, 200.0, 200.0],
              [r.get("qty") for r in rows])
        check("every row carries the contract price", all(float(r.get("rate") or 0) == 10.43 for r in rows),
              [r.get("rate") for r in rows])
        events = [e.get("text", "") for e in json.loads(out.events or "[]")]
        check("the timeline says which sizes were left off", any("no pieces" in t and "XXS" in t and "XXL" in t for t in events),
              str(events[-2:]))
        check("the order is a draft (submitting stays an ERP action)", int(so.get("docstatus") or 0) == 0, so.get("docstatus"))

        # nothing at all ordered: a sentence, not a raw ERP refusal
        be2 = fake_erp()
        deals.BACKEND = be2
        _seed_contract(be2, name="SC-2")
        be2.docs["Sales Contract"]["SC-2"]["sizes"] = [{"style_item": "APPAREL-STYLE", "colour": "Cool Capri Wash",
                                                        "size": z, "qty": 0} for z, _q in SIZES]
        d2 = _deal_with_contract(db, "SC-2")
        try:
            deals.make_order(db, ADMIN, d2.id)
            check("an all-zero contract is refused in words", False, "no error raised")
        except deals.DealError as e:
            check("an all-zero contract is refused in words", "nothing to order" in str(e), str(e))
    finally:
        erp._base_key, erp._DESK_PREFIX = real_base, real_prefix


def t_make_order_survives_an_old_script():
    """The same order, with the PREVIOUS make-Sales-Order script on the site: the tower still cannot send an empty line."""
    print("\n4. The tower is safe even if the ERP's own script goes back to sending zero rows")
    real_base, real_prefix = erp._base_key, erp._DESK_PREFIX
    eng = pipeline.engine()
    method = "arinox_sales_contract_make_sales_order"
    rec = eng.registry.api[method]
    good_script = rec["script"]
    good_code = eng.registry.code[rec["name"]]
    try:
        pin_site()
        bad = good_script.replace("        if cint(s.qty) <= 0:\n"
                                  "            continue    # a size nobody orders is not an order line (the ERP refuses a zero quantity)\n", "")
        bad = bad.replace('    if not so.items:\n        frappe.throw("Every size row on this contract has a quantity of zero, so there is nothing to order. Enter the pieces first.")\n', "")
        check("the old script really is the buggy one", bad != good_script and "if cint(s.qty) <= 0" not in bad)
        rec["script"] = bad
        eng.registry.code[rec["name"]] = compile(bad, rec["name"], "exec")

        be = fake_erp()
        deals.BACKEND = be
        db = get_session()
        _seed_contract(be, name="SC-3")
        d = _deal_with_contract(db, "SC-3")
        out = deals.make_order(db, ADMIN, d.id)
        so = (be.docs.get("Sales Order") or {}).get(out.refs_dict().get("sales_order")) or {}
        rows = so.get("items") or []
        check("the order is still made with the old script on the site", bool(rows), str(out.refs_dict()))
        check("and it still has no zero-quantity line", rows and all(float(r.get("qty") or 0) > 0 for r in rows),
              [r.get("qty") for r in rows])
    except deals.DealError as e:
        check("the order is still made with the old script on the site", False, str(e))
    finally:
        rec["script"] = good_script
        eng.registry.code[rec["name"]] = good_code
        erp._base_key, erp._DESK_PREFIX = real_base, real_prefix


def t_script_is_fixed_on_the_site():
    """The ERP's own button (Sales Contract → Sales Order) must work too, so the script we ship carries the guard."""
    print("\n5. The ERP's own make-Sales-Order script skips the empty sizes as well")
    from tsr.runner import Registry
    reg = Registry.load()
    rec = reg.api["arinox_sales_contract_make_sales_order"]
    check("the shipped script skips a zero-quantity size row", "if cint(s.qty) <= 0:" in rec["script"])
    check("...and says so when there is nothing to order at all", "nothing to order" in rec["script"])


def main():
    print("ERP links + the Sales Order that could not be made")
    t_url_builder()
    t_step_pages()
    t_make_order_skips_empty_sizes()
    t_make_order_survives_an_old_script()
    t_script_is_fixed_on_the_site()
    print("\n" + "=" * 70)
    if _FAIL:
        print(f"❌ {len(_FAIL)} failed: {_FAIL}")
        return 1
    print(f"✅ {_PASS} assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
