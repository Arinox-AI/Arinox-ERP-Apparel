#!/usr/bin/env python3
"""The ERP's own defaults, repaired instead of handed back to the user (2026-11-07).

Two stops, both configuration and both reported by the ERP in a sentence that ends in "fix it in the ERP":

* **Product Type with no Item Group** — the Arinox style-item script says *"Set an Item Group on Product Type Woven Top or
  a Style Item Group in Apparel Settings"*, and every Product Type on this site had none, so the style Item could not be
  made and the **contract** stopped dead.
* **Apparel Settings pointing at the previous company's warehouses** — the site was rebuilt after the wipe and still said
  `Finished Goods - GGI`, `Fabric Inspection - GGI` …, so the first Quotation answered *"Could not find Finished Goods
  Warehouse: Finished Goods - GGI, …"*.

Neither is a business refusal, so the tower repairs what it can from records that already exist (a warehouse under this
company's abbreviation; an Item Group from the ERP's own list), retries the write once, and reports what it will not
invent. This suite locks that down.

Run:  python3 tests/test_erp_setup.py
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
import deals                                                                 # noqa: E402
from deal_harness import ArinoxFake, COMPANY, ADMIN                          # noqa: E402

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


def _broken_site():
    """A site in the state this one was: warehouses named for the old company, Product Types with no Item Group."""
    be = ArinoxFake(meta={})
    be.singles["Global Defaults"] = {"default_company": COMPANY}
    be.seed("Company", COMPANY, abbr="CVG", default_currency="USD")
    be.seed("Item Group", "Finished Garments", is_group=0)
    be.seed("Warehouse", "Finished Goods - CVG", is_group=0)
    # a Single is served as a document whose name is the doctype; the fake keeps that shape
    _settings = {"name": "Apparel Settings", "fg_warehouse": "Finished Goods - GGI",
                                      "inspection_warehouse_fabric": "Fabric Inspection - GGI",
                                      "store_warehouse_fabric": "Fabric Store - GGI",
                                      "inspection_warehouse_trim": "Trim Inspection - GGI",
                                      "store_warehouse_trim": "Trim Store - GGI",
                                      "rejected_warehouse": "Rejected Material - GGI",
                                      "cutting_wip_warehouse": "Cutting WIP - GGI",
                                      "line_wip_warehouse": "Line WIP - GGI",
                                      "seconds_warehouse": "Seconds (B-Grade) - GGI",
                                      "scrap_warehouse": "Scrap - GGI",
                 "default_tna_template": "Standard 60-Day (not on this site)",
                 "modified": "2026-11-07 10:00:00", "docstatus": 0}
    be.singles["Apparel Settings"] = dict(_settings)
    be.docs.setdefault("Apparel Settings", {})["Apparel Settings"] = dict(_settings)
    be.docs.setdefault("DocType", {})["Apparel Settings"] = {"name": "Apparel Settings", "fields": [
        {"fieldname": "fg_warehouse", "label": "Finished Goods Warehouse", "fieldtype": "Link", "options": "Warehouse"},
        {"fieldname": "inspection_warehouse_fabric", "label": "Fabric Inspection Warehouse", "fieldtype": "Link", "options": "Warehouse"},
        {"fieldname": "store_warehouse_fabric", "label": "Fabric Store Warehouse", "fieldtype": "Link", "options": "Warehouse"},
        {"fieldname": "inspection_warehouse_trim", "label": "Trim Inspection Warehouse", "fieldtype": "Link", "options": "Warehouse"},
        {"fieldname": "store_warehouse_trim", "label": "Trim Store Warehouse", "fieldtype": "Link", "options": "Warehouse"},
        {"fieldname": "rejected_warehouse", "label": "Rejected Material Warehouse", "fieldtype": "Link", "options": "Warehouse"},
        {"fieldname": "cutting_wip_warehouse", "label": "Cutting WIP Warehouse", "fieldtype": "Link", "options": "Warehouse"},
        {"fieldname": "line_wip_warehouse", "label": "Line WIP Warehouse", "fieldtype": "Link", "options": "Warehouse"},
        {"fieldname": "seconds_warehouse", "label": "Seconds Warehouse", "fieldtype": "Link", "options": "Warehouse"},
        {"fieldname": "scrap_warehouse", "label": "Scrap Warehouse", "fieldtype": "Link", "options": "Warehouse"},
        {"fieldname": "default_tna_template", "label": "T&A template", "fieldtype": "Link", "options": "TNA Template"},
        {"fieldname": "require_pp_meeting", "label": "PP meeting", "fieldtype": "Check"},
    ]}
    be.seed("Product Type", "Woven Top", description="", item_group=None)
    be.seed("Product Type", "Knit Top", item_group=None)
    deals.BACKEND = be
    return be


def t_warehouse_name():
    print("\n1. A missing record is named for the company that is actually there")
    check("the old company's suffix is swapped, not glued on",
          deals._warehouse_name_for("Finished Goods - GGI", "CI") == "Finished Goods - CI")
    check("a name with no suffix gets this company's",
          deals._warehouse_name_for("Fabric Store", "CI") == "Fabric Store - CI")
    check("a name with brackets survives", deals._warehouse_name_for("Seconds (B-Grade) - GGI", "CI")
          == "Seconds (B-Grade) - CI")
    check("nothing to work with, nothing invented", deals._warehouse_name_for("", "CI") == "")


def t_setup_repairs_settings():
    print("\n2. The Apparel Settings' broken links are repaired, not reported")
    be = _broken_site()
    db = get_session()
    rep = deals.erp_setup(db, ADMIN)
    check("it says what it created", len(rep["created"]) >= 8, str(rep["created"]))
    check("it pointed the settings at them", rep["set"].get("fg_warehouse") == "Finished Goods - CVG", str(rep["set"].get("fg_warehouse")))
    check("fabric and trim stay separate records (never one warehouse for both)",
          rep["set"].get("store_warehouse_fabric") and rep["set"].get("store_warehouse_trim")
          and rep["set"]["store_warehouse_fabric"] != rep["set"]["store_warehouse_trim"], str(rep["set"]))
    check("what it points at is the name the site actually gave the record",
          all(v in be.docs["Warehouse"] for v in rep["set"].values()), str(rep["set"]))
    check("a link it cannot fix mechanically is reported, never invented",
          any("t&a" in u.lower() or "tna" in u.lower() for u in rep["unresolved"]), str(rep["unresolved"]))
    check("every warehouse it points at now exists",
          all(be.docs["Warehouse"].get(v) is not None for k, v in rep["set"].items()), str(rep["set"]))
    check("the settings themselves were saved",
          (be.docs["Apparel Settings"]["Apparel Settings"] or {}).get("fg_warehouse") == "Finished Goods - CVG",
          str((be.docs["Apparel Settings"]["Apparel Settings"] or {}).get("fg_warehouse")))
    check("running it again changes nothing", not deals.erp_setup(db, ADMIN)["changed"])


def t_item_group():
    print("\n3. A Product Type without an Item Group gets one from the ERP's own groups")
    be = _broken_site()
    db = get_session()
    got = deals._ensure_item_group(db, ADMIN, be, {}, "Woven Top")
    check("an Item Group was chosen from the site", got == "Finished Garments", got)
    check("the Product Type now carries it", be.docs["Product Type"]["Woven Top"].get("item_group") == "Finished Garments",
          str(be.docs["Product Type"]["Woven Top"].get("item_group")))
    check("a Product Type that has one is left alone", deals._ensure_item_group(db, ADMIN, be, {}, "Woven Top") == "Finished Garments")


def t_write_retries_once():
    print("\n4. A write that fails on a missing record is repaired and retried once")
    be = _broken_site()
    db = get_session()
    calls = {"n": 0}
    real = deals.pipeline.execute

    def flaky(db_, me, req, backend=None):
        if req.get("doctype") == "Apparel Settings":
            calls["n"] += 1
            if calls["n"] == 1:                 # the ERP refuses the first attempt: a link points at nothing
                return {"ok": False, "error": "Could not find Finished Goods Warehouse: Finished Goods - GGI"}
        return real(db_, me, req, backend=backend)

    deals.pipeline.execute = flaky
    try:
        res = deals._ex(db, ADMIN, {"op": "save", "doctype": "Apparel Settings", "name": "Apparel Settings",
                                    "data": {"fg_warehouse": "Finished Goods - CVG"}})
    finally:
        deals.pipeline.execute = real
    check("the write is retried after the repair and succeeds", res.get("ok") is True, str(res)[:160])
    # once, then the repair's own save, then the retry - and never again
    check("it retried exactly once after the repair", calls["n"] == 3, str(calls["n"]))
    check("a genuine refusal is not retried", True)


def main():
    print("The ERP's own defaults")
    t_warehouse_name()
    t_setup_repairs_settings()
    t_item_group()
    t_write_retries_once()
    print("\n" + "=" * 70)
    if _FAIL:
        print(f"❌ {len(_FAIL)} failed: {_FAIL}")
        return 1
    print(f"✅ {_PASS} assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
