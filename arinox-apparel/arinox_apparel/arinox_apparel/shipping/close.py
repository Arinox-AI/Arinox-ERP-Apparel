"""Commercial close of an order: production done, everything shipped is invoiced, every customer invoice paid, no claim
open and every claim window over (or waived with a reason). Closing sets the Sales Order to Closed."""

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, getdate, nowdate

from arinox_apparel.production import maths


def checklist(sales_order):
	"""[(label, ok, detail)]. Pure reading; nothing is changed."""
	out = []
	cards = frappe.get_all("Production Card", {"sales_order": sales_order, "docstatus": 1, "status": ["not in", ["Superseded", "Cancelled"]]}, ["name", "status"])
	open_cards = [c.name for c in cards if c.status not in ("Shipped", "Closed")]
	out.append((_("Production finished"), bool(cards) and not open_cards, ", ".join(open_cards) or (_("no production card") if not cards else "")))
	dns = frappe.get_all("Delivery Note", {"docstatus": 1, "name": ["in", frappe.db.sql_list("select distinct parent from `tabDelivery Note Item` where against_sales_order = %s and docstatus = 1", sales_order) or [""]]}, ["name", "status"])
	unbilled = []
	for dn in dns:
		shipment = frappe.db.get_value("Delivery Note", dn.name, "apparel_shipment")
		billed = frappe.db.exists("Sales Invoice Item", {"delivery_note": dn.name, "docstatus": 1}) or (shipment and frappe.db.exists("Sales Invoice", {"apparel_shipment": shipment, "docstatus": 1}))
		if not billed:
			unbilled.append(dn.name)
	out.append((_("Everything shipped is invoiced"), bool(dns) and not unbilled, ", ".join(unbilled) or (_("nothing shipped") if not dns else "")))
	contract = frappe.db.get_value("Sales Order", sales_order, "apparel_sales_contract")
	filters = {"docstatus": 1, "is_internal_customer": 0, "is_return": 0}
	if contract:
		filters["apparel_sales_contract"] = contract
	else:
		filters["name"] = ["in", frappe.db.sql_list("select distinct parent from `tabSales Invoice Item` where sales_order = %s", sales_order) or [""]]
	unpaid = [i.name for i in frappe.get_all("Sales Invoice", filters, ["name", "outstanding_amount"]) if flt(i.outstanding_amount) > 0.005]
	out.append((_("Customer invoices paid"), not unpaid, ", ".join(unpaid)))
	claims = frappe.get_all("Buyer Claim", {"sales_contract": contract, "docstatus": ["<", 2], "status": ["in", ["Open", "Under Review"]]}, pluck="name") if contract else []
	out.append((_("No claim open"), not claims, ", ".join(claims)))
	waiting = []
	if contract and frappe.db.exists("Sales Contract", contract):
		q, n = frappe.db.get_value("Sales Contract", contract, ["quality_claim_days", "quantity_claim_days"])
		longest = max(cint(q), cint(n))
		for s in frappe.get_all("Shipment", {"apparel_contracts": ["like", f"%{contract}%"], "docstatus": ["<", 2]}, ["name", "apparel_contracts", "apparel_arrival_date", "apparel_delivery_date"]):
			if contract not in (s.apparel_contracts or "").splitlines():
				continue   # a longer contract number that merely contains this one
			arrival = s.apparel_arrival_date or s.apparel_delivery_date
			if not arrival or date_diff(nowdate(), arrival) <= longest:
				waiting.append(s.name)
	out.append((_("Claim windows over"), not waiting, ", ".join(waiting)))
	return out


@frappe.whitelist()
def get_checklist(sales_order):
	if not frappe.has_permission("Sales Order", "read", sales_order):
		frappe.throw(_("You cannot read this order."), frappe.PermissionError)
	return [{"label": l, "ok": ok, "detail": d} for l, ok, d in checklist(sales_order)]


@frappe.whitelist()
def commercial_close(sales_order, waive_reason=None):
	if not ({"Accounts Manager", "Apparel Merchandising Manager", "System Manager"} & set(frappe.get_roles())):
		frappe.throw(_("Only an accounts or merchandising manager closes an order commercially."))
	so = frappe.get_doc("Sales Order", sales_order)
	so.check_permission("write")
	rows = checklist(sales_order)
	failed = [(l, d) for l, ok, d in rows if not ok]
	waivable = {_("Claim windows over")}
	hard = [(l, d) for l, d in failed if l not in waivable]
	if hard:
		frappe.throw("<br>".join(f"{l}: {d}" if d else l for l, d in hard), title=_("The order cannot be closed yet"))
	if failed and not (waive_reason or "").strip():
		frappe.throw(_("A claim window is still open. Write why the order may close anyway."))
	from erpnext.selling.doctype.sales_order.sales_order import update_status

	update_status("Closed", sales_order)
	so.add_comment("Comment", _("Closed commercially. {0}").format(waive_reason or ""))
	return True
