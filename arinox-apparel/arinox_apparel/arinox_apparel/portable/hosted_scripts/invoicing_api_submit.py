# API arinox_invoicing_submit_invoices (shipment): submit the drafts leg by leg (the factory's invoice first). When the contract counts
# payment from the bill of lading, the on-board date must be recorded first.
def main():
    # include: lib_followup.py
    shipment = frappe.form_dict.get("shipment")
    ship = frappe.get_doc("Shipment", shipment)
    ship.check_permission("write")
    drafts = frappe.get_all("Sales Invoice", {"apparel_shipment": shipment, "docstatus": 0}, ["name", "apparel_sales_contract"], order_by="apparel_route_leg, creation")
    if not drafts:
        frappe.throw("There are no draft invoices on this shipment.")
    for d in drafts:
        if contract_terms(d.apparel_sales_contract)[0] == "Days after B/L Date" and not ship.apparel_on_board_date:
            frappe.throw("%s counts payment from the bill of lading. Record the on-board date first." % d.apparel_sales_contract)
    done = []
    for d in drafts:
        refresh_invoice(d.name)
        si = frappe.get_doc("Sales Invoice", d.name)
        si.submit()
        done.append(si.name)
        refresh_invoice(si.name)
    frappe.flags.arinox_result = done


main()
