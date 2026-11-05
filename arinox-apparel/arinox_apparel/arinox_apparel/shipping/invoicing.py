"""Commercial invoices from a shipment's Delivery Notes.

One invoice per contract per shipment, numbered from the contract (`<contract>-INV-<nn>`), so the number that began the
order runs to the payment. A customer billed through a group trading company gets two invoices that share the number:
factory to trading company at the transfer price, trading company to the buyer at the order price. Everything is
created as a draft; the accountant submits (or uses Submit Invoices once the bill of lading is in)."""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from arinox_apparel.shipping import common, followup


def internal_customer(company):
	name = frappe.db.get_value("Customer", {"is_internal_customer": 1, "represents_company": company}, "name")
	if not name:
		frappe.throw(_("Company {0} needs an internal Customer (Is Internal Customer, Represents Company) before it can be billed in a group route.").format(company))
	return name


def transfer_rate(customer, row):
	"""Price of one piece between the group companies, by the customer's transfer-price basis."""
	c = frappe.db.get_value("Customer", customer, ["apparel_transfer_basis", "apparel_transfer_pct", "apparel_transfer_price_list"], as_dict=True)
	basis = c.apparel_transfer_basis or "Percent of Customer Price"
	if basis == "Percent of Customer Price":
		if not flt(c.apparel_transfer_pct):
			frappe.throw(_("Set the transfer price percent on customer {0}.").format(customer))
		return round(flt(row.rate) * flt(c.apparel_transfer_pct) / 100.0, 6)
	if basis == "Price List":
		if not c.apparel_transfer_price_list:
			frappe.throw(_("Set the transfer price list on customer {0}.").format(customer))
		template = frappe.db.get_value("Item", row.item_code, "variant_of")
		for code in (row.item_code, template):
			if code:
				price = frappe.db.get_value("Item Price", {"item_code": code, "price_list": c.apparel_transfer_price_list}, "price_list_rate")
				if price:
					return flt(price)
		frappe.throw(_("No price for {0} in price list {1}.").format(row.item_code, c.apparel_transfer_price_list))
	soi = frappe.db.get_value("Sales Order Item", row.so_detail, "apparel_cost_sheet") if row.get("so_detail") else None
	price = frappe.db.get_value("Cost Sheet", soi, "approved_price") if soi else None
	if not price:
		frappe.throw(_("{0} has no approved Cost Sheet price to use as the transfer price.").format(row.item_code))
	return flt(price)


def apply_terms(si, contract, dn):
	basis, days, transit = followup.contract_terms(contract)
	tmpl = frappe.db.get_value("Sales Contract", contract, "payment_terms_template") if contract and frappe.db.exists("Sales Contract", contract) else None
	if basis == followup.INVOICE and tmpl:
		si.payment_terms_template = tmpl
	else:
		ship = frappe.db.get_value("Shipment", dn.apparel_shipment, ["apparel_on_board_date", "apparel_eta", "apparel_delivery_date"], as_dict=True) if dn.get("apparel_shipment") else None
		_d, _s, due = followup.expected_due(basis, days, si.posting_date, ship.apparel_on_board_date if ship else None, ship.apparel_eta if ship else None,
											ship.apparel_delivery_date if ship else None, common.settings_value("rog_buffer_days", 5), transit)
		si.payment_terms_template = None
		si.due_date = max(due, getdate(si.posting_date))


def tag(si, dn, contract, number, leg):
	si.apparel_sales_contract = contract
	si.apparel_commercial_invoice_no = number
	si.apparel_shipment = dn.get("apparel_shipment")
	si.apparel_route_leg = leg
	pos = sorted({frappe.db.get_value("Packing List", it.apparel_packing_list, "buyer_po") or "" for it in dn.items if it.get("apparel_packing_list")} - {""})
	si.po_no = ", ".join(pos)[:140] or si.get("po_no")


def build_leg(dn, company, customer, rates, leg, contract, number, linked):
	"""A draft Sales Invoice for the pieces on `dn`. `rates` maps a DN row name to the unit price to bill."""
	if linked:
		from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice

		si = make_sales_invoice(dn.name)
	else:
		si = frappe.new_doc("Sales Invoice")
		si.company, si.customer = company, customer
		si.currency = dn.currency
		si.update_stock = 0
		for it in dn.items:
			si.append("items", {"item_code": it.item_code, "item_name": it.item_name, "description": it.description, "qty": it.qty, "uom": it.uom,
								"rate": rates[it.name], "sales_order": None})
	si.posting_date = dn.posting_date
	si.set_posting_time = 1
	if linked:
		for row in si.items:
			dn_row = next((i for i in dn.items if i.name == row.dn_detail), None)
			if dn_row and rates.get(dn_row.name):
				row.rate = rates[dn_row.name]
	tag(si, dn, contract, number, leg)
	si.run_method("set_missing_values")   # first: customer defaults may bring their own payment terms
	apply_terms(si, contract, dn)         # then the contract's basis wins
	si.set("payment_schedule", [])
	si.run_method("calculate_taxes_and_totals")
	si.insert()
	followup.refresh_invoice(si.name)
	return si.name


@frappe.whitelist()
def prepare_invoices(shipment):
	"""Draft the invoices of a shipment. Re-running replaces drafts and keeps the invoice numbers; submitted invoices are left alone."""
	if not frappe.has_permission("Sales Invoice", "create"):
		frappe.throw(_("You cannot create sales invoices."), frappe.PermissionError)
	ship = frappe.get_doc("Shipment", shipment)
	ship.check_permission("write")
	dns = [frappe.get_doc("Delivery Note", r.delivery_note) for r in ship.shipment_delivery_note]
	if not dns:
		frappe.throw(_("Make the delivery notes first (Make Delivery Notes)."))
	made = []
	numbers, skipped = {}, set()   # one commercial number per contract; contracts that already have submitted invoices
	for dn in dns:
		if dn.docstatus != 1:
			frappe.throw(_("Delivery note {0} must be submitted before it is invoiced.").format(dn.name))
		contract = dn.get("apparel_sales_contract") or common.serial_root(dn.items[0].against_sales_order)
		if contract not in numbers and contract not in skipped:
			existing = frappe.get_all("Sales Invoice", {"apparel_shipment": shipment, "apparel_sales_contract": contract, "docstatus": ["<", 2]},
									  ["name", "docstatus", "apparel_commercial_invoice_no"])
			if any(e.docstatus == 1 for e in existing):
				frappe.msgprint(_("{0} already has submitted invoices on this shipment; they were left as they are.").format(contract))
				skipped.add(contract)
			else:
				numbers[contract] = next((e.apparel_commercial_invoice_no for e in existing if e.apparel_commercial_invoice_no), None) or common.next_serial(contract, "INV")
				for e in existing:
					frappe.delete_doc("Sales Invoice", e.name, ignore_permissions=True, force=True)
		if contract in skipped:
			continue
		number = numbers[contract]
		via = frappe.db.get_value("Customer", dn.customer, "apparel_invoice_via_company")
		order_rates = {it.name: flt(it.rate) for it in dn.items}
		if via and via != dn.company:
			t_rates = {it.name: transfer_rate(dn.customer, it) for it in dn.items}
			made.append(build_leg(dn, dn.company, internal_customer(via), t_rates, 1, contract, number, linked=False))
			made.append(build_leg(dn, via, dn.customer, order_rates, 2, contract, number, linked=False))
		else:
			made.append(build_leg(dn, dn.company, dn.customer, order_rates, 1, contract, number, linked=True))
	from arinox_apparel.shipping import shipment as shipment_mod

	shipment_mod.refresh_status(shipment)
	return made


@frappe.whitelist()
def submit_invoices(shipment):
	"""Submit the drafts leg by leg (the factory's invoice first). Needs the bill of lading date when the contract counts from it."""
	if not frappe.has_permission("Sales Invoice", "submit"):
		frappe.throw(_("You cannot submit sales invoices."), frappe.PermissionError)
	ship = frappe.get_doc("Shipment", shipment)
	ship.check_permission("write")
	drafts = frappe.get_all("Sales Invoice", {"apparel_shipment": shipment, "docstatus": 0}, ["name", "apparel_sales_contract"], order_by="apparel_route_leg, creation")
	if not drafts:
		frappe.throw(_("There are no draft invoices on this shipment."))
	for d in drafts:
		basis = followup.contract_terms(d.apparel_sales_contract)[0]
		if basis == followup.BL and not ship.apparel_on_board_date:
			frappe.throw(_("{0} counts payment from the bill of lading. Record the on-board date first.").format(d.apparel_sales_contract))
	done = []
	for d in drafts:
		followup.refresh_invoice(d.name)
		si = frappe.get_doc("Sales Invoice", d.name)
		si.submit()
		done.append(si.name)
		followup.refresh_invoice(si.name)
	for dn in {r.delivery_note for r in ship.shipment_delivery_note}:
		if frappe.db.exists("Sales Invoice", {"apparel_shipment": shipment, "apparel_route_leg": 2, "docstatus": 1}) and not frappe.db.exists("Sales Invoice Item", {"delivery_note": dn, "docstatus": 1}):
			try:
				from erpnext.stock.doctype.delivery_note.delivery_note import update_delivery_note_status

				update_delivery_note_status(dn, "Closed")
			except Exception:
				frappe.log_error(title="Closing delivery note after group invoicing failed", message=frappe.get_traceback())
	return done
