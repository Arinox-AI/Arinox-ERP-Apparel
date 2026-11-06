# API arinox_invoicing_prepare_invoices (shipment): draft the commercial invoices of a shipment. One invoice per contract per shipment, numbered
# <contract>-INV-<nn>. A customer billed through a group trading company gets two invoices that share the number: factory -> trading company at the
# transfer price (leg 1), trading company -> buyer at the order price (leg 2). Re-running replaces drafts and keeps their numbers; submitted
# invoices are left alone. An invoice that covers several contracts keeps the first as its link and lists all in "All Contracts On This Invoice".
def main():
    # include: lib_followup.py
    flt = frappe.utils.flt
    shipment = frappe.form_dict.get("shipment")
    ship = frappe.get_doc("Shipment", shipment)
    ship.check_permission("write")
    dns = [frappe.get_doc("Delivery Note", r.delivery_note) for r in ship.shipment_delivery_note]
    if not dns:
        frappe.throw("Make the delivery notes first (Make Delivery Notes).")

    def contract_of_order(so):
        if not so:
            return None
        return frappe.db.get_value("Sales Order", so, "apparel_sales_contract") or None

    def next_number(root):
        series = root + "-INV-"
        n = frappe.get_doc({"doctype": "Arinox Number", "prefix": series}).insert(ignore_permissions=True)
        return series + str(int(n.name[len(series):])).zfill(2)

    def internal_customer(company):
        name = frappe.db.get_value("Customer", {"is_internal_customer": 1, "represents_company": company}, "name")
        if not name:
            frappe.throw("Company %s needs an internal Customer (Is Internal Customer, Represents Company) before it can be billed in a group route." % company)
        return name

    def transfer_rate(customer, row):
        c = frappe.db.get_value("Customer", customer, ["apparel_transfer_basis", "apparel_transfer_pct", "apparel_transfer_price_list"], as_dict=True)
        basis = c.apparel_transfer_basis or "Percent of Customer Price"
        if basis == "Percent of Customer Price":
            if not flt(c.apparel_transfer_pct):
                frappe.throw("Set the transfer price percent on customer %s." % customer)
            return round(flt(row.rate) * flt(c.apparel_transfer_pct) / 100.0, 6)
        if basis == "Price List":
            if not c.apparel_transfer_price_list:
                frappe.throw("Set the transfer price list on customer %s." % customer)
            template = frappe.db.get_value("Item", row.item_code, "variant_of")
            for code in (row.item_code, template):
                if code:
                    price = frappe.db.get_value("Item Price", {"item_code": code, "price_list": c.apparel_transfer_price_list}, "price_list_rate")
                    if price:
                        return flt(price)
            frappe.throw("No price for %s in price list %s." % (row.item_code, c.apparel_transfer_price_list))
        soi = frappe.db.get_value("Sales Order Item", row.so_detail, "apparel_cost_sheet") if row.get("so_detail") else None
        price = frappe.db.get_value("Cost Sheet", soi, "approved_price") if soi else None
        if not price:
            frappe.throw("%s has no approved Cost Sheet price to use as the transfer price." % row.item_code)
        return flt(price)

    def build_leg(dn, company, customer, rates, leg, contract, number, linked):
        if linked:
            si = frappe.call("erpnext.stock.doctype.delivery_note.delivery_note.make_sales_invoice", source_name=dn.name)
        else:
            si = frappe.new_doc("Sales Invoice")
            si.company = company
            si.customer = customer
            si.currency = dn.currency
            si.update_stock = 0
            for it in dn.items:
                si.append("items", {"item_code": it.item_code, "item_name": it.item_name, "description": it.description, "qty": it.qty, "uom": it.uom, "rate": rates[it.name], "sales_order": None})
        si.posting_date = dn.posting_date
        si.set_posting_time = 1
        if linked:
            by_name = {}
            for i in dn.items:
                by_name[i.name] = i
            for row in si.items:
                dn_row = by_name.get(row.dn_detail)
                if dn_row and rates.get(dn_row.name):
                    row.rate = rates[dn_row.name]
        # tag it with the contract(s), the number, the shipment and the leg
        contracts = []
        for it in dn.items:
            c = contract_of_order(it.get("against_sales_order")) or it.get("against_sales_order")
            if c and c not in contracts:
                contracts.append(c)
        si.apparel_sales_contract = contract if frappe.db.exists("Sales Contract", contract) else None     # an order with no contract is numbered from its own name
        si.apparel_all_contracts = ", ".join(contracts)
        si.apparel_commercial_invoice_no = number
        si.apparel_shipment = shipment                       # the shipment being invoiced, whichever way the note was linked to it
        si.apparel_route_leg = leg
        pos = []
        for it in dn.items:
            if it.get("apparel_packing_list"):
                po = frappe.db.get_value("Packing List", it.apparel_packing_list, "buyer_po") or ""
                if po and po not in pos:
                    pos.append(po)
        si.po_no = ", ".join(sorted(pos))[:140] or si.get("po_no")
        si.run_method("set_missing_values")        # first: customer defaults may bring their own payment terms
        # then the contract's basis wins
        terms = contract_terms(contract)
        tmpl = frappe.db.get_value("Sales Contract", contract, "payment_terms_template") if frappe.db.exists("Sales Contract", contract) else None
        if terms[0] == "Days after Invoice Date" and tmpl:
            si.payment_terms_template = tmpl
        else:
            ship_row = frappe.db.get_value("Shipment", shipment, ["apparel_on_board_date", "apparel_eta", "apparel_delivery_date"], as_dict=True)
            buffer_days = frappe.db.get_single_value("Apparel Settings", "rog_buffer_days") or 5
            got = expected_due(terms[0], terms[1], si.posting_date, ship_row.apparel_on_board_date if ship_row else None, ship_row.apparel_eta if ship_row else None,
                               ship_row.apparel_delivery_date if ship_row else None, buffer_days, terms[2])
            si.payment_terms_template = None
            si.due_date = max(got[2], frappe.utils.getdate(si.posting_date))
        si.set("payment_schedule", [])
        si.run_method("calculate_taxes_and_totals")
        si.insert()
        refresh_invoice(si.name)
        return si.name

    made = []
    numbers = {}
    skipped = []
    for dn in dns:
        if dn.docstatus != 1:
            frappe.throw("Delivery note %s must be submitted before it is invoiced." % dn.name)
        first_so = dn.items[0].against_sales_order
        contract = dn.get("apparel_sales_contract") or contract_of_order(first_so) or first_so
        if contract not in numbers and contract not in skipped:
            # found by number prefix, not by the contract link: an order with no contract has no link but still has a number
            existing = frappe.get_all("Sales Invoice", {"apparel_shipment": shipment, "docstatus": ["<", 2], "apparel_commercial_invoice_no": ["like", contract + "-INV-%"]},
                                      ["name", "docstatus", "apparel_commercial_invoice_no"])
            if [e for e in existing if e.docstatus == 1]:
                frappe.msgprint("%s already has submitted invoices on this shipment; they were left as they are." % contract)
                skipped.append(contract)
            else:
                kept = [e.apparel_commercial_invoice_no for e in existing if e.apparel_commercial_invoice_no]
                numbers[contract] = kept[0] if kept else next_number(contract)
                for e in existing:
                    frappe.delete_doc("Sales Invoice", e.name, ignore_permissions=True, force=True)
        if contract in skipped:
            continue
        number = numbers[contract]
        via = frappe.db.get_value("Customer", dn.customer, "apparel_invoice_via_company")
        order_rates = {}
        for it in dn.items:
            order_rates[it.name] = flt(it.rate)
        if via and via != dn.company:
            t_rates = {}
            for it in dn.items:
                t_rates[it.name] = transfer_rate(dn.customer, it)
            made.append(build_leg(dn, dn.company, internal_customer(via), t_rates, 1, contract, number, False))
            made.append(build_leg(dn, via, dn.customer, order_rates, 2, contract, number, False))
        else:
            made.append(build_leg(dn, dn.company, dn.customer, order_rates, 1, contract, number, True))
    frappe.flags.arinox_result = made


main()
