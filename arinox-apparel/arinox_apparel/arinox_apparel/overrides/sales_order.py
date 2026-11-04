"""A Sales Order made from a Sales Contract keeps its link, and a contract has at most one live order."""

import frappe
from frappe import _


def validate(doc, method=None):
	name = doc.get("apparel_sales_contract")
	if not name:
		return
	sc = frappe.db.get_value("Sales Contract", name, ["docstatus", "customer", "sales_order"], as_dict=True)
	if not sc or sc.docstatus != 1:
		frappe.throw(_("Sales Contract {0} is not signed (submitted).").format(name))
	if sc.customer != doc.customer:
		frappe.throw(_("Sales Contract {0} is for {1}.").format(name, sc.customer))
	if sc.sales_order and sc.sales_order != doc.name and frappe.db.get_value("Sales Order", sc.sales_order, "docstatus") != 2:
		frappe.throw(_("Sales Contract {0} already has Sales Order {1}.").format(name, sc.sales_order))


def on_submit(doc, method=None):
	if doc.get("apparel_sales_contract"):
		frappe.db.set_value("Sales Contract", doc.apparel_sales_contract, {"sales_order": doc.name, "status": "Ordered"})


def on_cancel(doc, method=None):
	if doc.get("apparel_sales_contract"):
		frappe.db.set_value("Sales Contract", doc.apparel_sales_contract, {"sales_order": None, "status": "Signed"})
