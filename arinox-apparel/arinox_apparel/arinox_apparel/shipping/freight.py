"""Freight cost of a shipment. The forwarder's quote is an ERPNext Supplier Quotation; the forwarder's bills are Purchase
Invoices; both are tagged with the Shipment. This module adds them up, compares them, and shares the cost out over the
orders on board. It writes no accounting entries."""

import frappe
from frappe import _
from frappe.utils import flt

from arinox_apparel.production import maths
from arinox_apparel.shipping import common


def refresh_costs(shipment):
	"""Estimate (the chosen quote), actual (the forwarder's invoices not cancelled) and the gap, written onto the shipment."""
	if not frappe.db.exists("Shipment", shipment):
		return
	quote = frappe.db.get_value("Shipment", shipment, "apparel_freight_quote")
	estimate = flt(frappe.db.get_value("Supplier Quotation", quote, "base_grand_total")) if quote else 0
	actual = flt(frappe.db.sql(
		"select ifnull(sum(base_grand_total), 0) from `tabPurchase Invoice` where apparel_shipment = %s and docstatus < 2 and ifnull(is_return, 0) = 0", shipment)[0][0])
	pct = maths.over_short_pct(actual, estimate) if estimate and actual else 0
	frappe.db.set_value("Shipment", shipment, {"apparel_estimate_total": estimate, "apparel_actual_total": actual, "apparel_cost_variance_pct": round(pct or 0, 2)}, update_modified=False)
	limit = flt(common.settings_value("freight_estimate_variance_pct", 10))
	if estimate and actual and abs(pct or 0) > limit:
		frappe.msgprint(_("Forwarder bills are {0} {1} % against the quote ({2} vs {3}).").format(_("over") if pct > 0 else _("under"), round(abs(pct), 1), actual, estimate), indicator="orange", title=_("Freight cost"))


def on_purchase_invoice(doc, method=None):
	before = doc.get_doc_before_save()
	for shipment in {doc.get("apparel_shipment"), before.get("apparel_shipment") if before else None} - {None, ""}:
		refresh_costs(shipment)


def allocation_basis(shipment):
	"""Share of a shipment's cost per order: by CBM at sea, by chargeable weight by air, by invoice value for duty."""
	d = frappe.db.get_value("Shipment", shipment, ["apparel_mode"], as_dict=True)
	rows = frappe.get_all("Shipment Packing List", {"parent": shipment}, ["packing_list", "sales_contract", "cbm", "gross_kg"])
	so = {r.packing_list: frappe.db.get_value("Packing List", r.packing_list, "sales_order") for r in rows}
	use = "gross_kg" if d and d.apparel_mode == "Air" else "cbm"
	total = sum(flt(r.get(use)) for r in rows)
	out = {}
	for r in rows:
		key = (r.sales_contract or so[r.packing_list])
		out[key] = out.get(key, 0) + (flt(r.get(use)) / total if total else 1.0 / len(rows))
	return out, use


def allocated_costs(shipment):
	"""[(contract, share, cost)] with the shipment's actual cost (estimate while no bill has arrived) shared by the basis."""
	d = frappe.db.get_value("Shipment", shipment, ["apparel_estimate_total", "apparel_actual_total"], as_dict=True)
	cost = flt(d.apparel_actual_total) or flt(d.apparel_estimate_total)
	shares, use = allocation_basis(shipment)
	return [(k, round(v, 6), round(cost * v, 2)) for k, v in sorted(shares.items())], use, cost
