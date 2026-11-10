"""A fake ERP that behaves like the Arinox site for the inquiry → order chain.

The doctype meta and reference rows (cost heads, product types, Apparel Settings) are a read-only export of the local
``hosted.localhost`` site (tests/fixtures/deal_meta.json). The scripts that run are the real vendored Arinox scripts.
"""
import json
import os

from tsr.fake import FakeBackend

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = json.load(open(os.path.join(HERE, "fixtures", "deal_meta.json")))
COMPANY = "Cortex Vietnam Garment Limited"


class ArinoxFake(FakeBackend):
    """FakeBackend plus the one naming rule the scripts lean on: an Arinox Number is named <prefix><counter>."""

    def insert(self, doc):
        if doc.get("doctype") == "Arinox Number" and not doc.get("name"):
            prefix = doc.get("prefix") or ""
            used = [n for n in self.docs.get("Arinox Number", {}) if n.startswith(prefix)]
            doc = {**doc, "name": prefix + "%05d" % (len(used) + 1)}
        if doc.get("doctype") == "Item" and not doc.get("name") and doc.get("item_code"):
            doc = {**doc, "name": doc["item_code"]}
        if doc.get("doctype") == "Customer" and not doc.get("name") and doc.get("customer_name"):
            doc = {**doc, "name": doc["customer_name"]}          # Selling Settings: customer naming by name
        return super().insert(doc)


    def call(self, method, kwargs):
        """ERPNext's variant helpers, the way the Sales Order builder uses them."""
        if method.endswith("get_variant"):
            want = sorted((str(k), str(v)) for k, v in (kwargs.get("args") or {}).items())
            for it in self.docs.get("Item", {}).values():
                if it.get("variant_of") == kwargs.get("template") and sorted((a["attribute"], a["attribute_value"]) for a in it.get("attributes") or []) == want:
                    return it["name"]
            return None
        if method.endswith("create_variant"):
            args = kwargs.get("args") or {}
            code = kwargs.get("item") + "-" + "-".join(str(v).replace(" ", "")[:10] for v in args.values())
            return {"doctype": "Item", "item_code": code, "item_name": code, "variant_of": kwargs.get("item"), "stock_uom": "Nos", "item_group": "Products",
                    "attributes": [{"attribute": k, "attribute_value": v} for k, v in args.items()]}
        return super().call(method, kwargs)


def fake_erp(configured: bool = True) -> FakeBackend:
    be = ArinoxFake(meta=dict(FIX["meta"]))
    ref = FIX["ref"]
    settings = dict(ref["apparel_settings"])
    settings["fg_warehouse"] = "Finished Goods - CVG"
    be.singles["Apparel Settings"] = settings
    be.singles["Global Defaults"] = {"default_company": COMPANY}
    be.singles["Stock Settings"] = {"default_warehouse": ""}
    be.seed("Company", COMPANY, default_currency="USD", company_name=COMPANY)
    be.seed("Warehouse", "Finished Goods - CVG", company=COMPANY)
    be.seed("Currency", "USD")
    for h in ref["cost_heads"]:
        be.seed("Cost Head", h["name"], enabled=1, **{k: v for k, v in h.items() if k != "name"})
    for p in ref["product_types"]:
        row = {k: v for k, v in p.items() if k != "name"}
        if configured:                      # the setup step the ERP asks for: an Item Group per product type
            row["item_group"] = row.get("item_group") or "Products"
        be.seed("Product Type", p["name"], **row)
    be.seed("Item Attribute", "Colour", attribute_name="Colour", item_attribute_values=[])
    be.seed("Item Attribute", "Size", attribute_name="Size", item_attribute_values=[])
    be.seed("Item Group", "Products", is_group=0)
    be.seed("Item", "APPAREL-STYLE", item_name="Apparel Style (quotation line)", item_group="Products", stock_uom="Nos")
    be.seed("Customer Group", "Commercial")
    be.seed("Territory", "Rest Of The World")
    be.seed("Customer", "EMJ APPAREL GROUP, LLC", customer_name="EMJ APPAREL GROUP, LLC", default_currency="USD",
            customer_group="Commercial", territory="Rest Of The World")
    be.autonames.update({"Opportunity": "CRM-OPP-2026-", "Tech Pack": "TP-2026-", "Cost Sheet": "CS-2026-",
                         "Price Negotiation": "PN-2026-", "Quotation": "SAL-QTN-2026-", "Sales Order": "SAL-ORD-2026-"})
    return be


ADMIN = {"email": "admin@test", "name": "Admin", "roles": ["Admin", "Management"], "is_admin": True, "erp_user": "Administrator"}
