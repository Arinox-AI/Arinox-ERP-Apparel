def main(filters):
    # include: lib_samples.py
    getdate = frappe.utils.getdate

    def key(stype):
        return "t_" + "".join([c if c.isalnum() else "_" for c in stype.lower()])

    base = get_rules(None, None, None)
    types = [t for t in base if base[t]["gate"] != "No"]
    for t in frappe.get_all("Sample Requirement", filters={"enabled": 1, "gate": ["in", ["Required", "If Raised"]]}, pluck="sample_type"):
        if base.get(t) and base[t]["gate"] == "No" and t not in types:
            types.append(t)
    columns = [{"fieldname": "sales_order", "label": "Sales Order", "fieldtype": "Link", "options": "Sales Order", "width": 140},
               {"fieldname": "customer", "label": "Customer", "fieldtype": "Link", "options": "Customer", "width": 130},
               {"fieldname": "style_item", "label": "Style", "fieldtype": "Link", "options": "Item", "width": 120}, {"fieldname": "colour", "label": "Colour", "fieldtype": "Data", "width": 90}]
    for t in types:
        columns.append({"fieldname": key(t), "label": t, "fieldtype": "Data", "width": 110})
    columns.append({"fieldname": "next_due", "label": "Next Due", "fieldtype": "Date", "width": 100})
    columns.append({"fieldname": "overdue", "label": "Overdue", "fieldtype": "Int", "width": 70})
    columns.append({"fieldname": "gate", "label": "Bulk Gate", "fieldtype": "Data", "width": 90})
    so_filters = {"docstatus": 1}
    if filters.get("sales_order"):
        so_filters["name"] = filters.get("sales_order")
    if filters.get("customer"):
        so_filters["customer"] = filters.get("customer")
    today = getdate(frappe.utils.nowdate())
    rows = []
    for so in frappe.get_all("Sales Order", filters=so_filters, fields=["name", "customer"], order_by="transaction_date desc", limit=200):
        item_of = {}
        order = []
        for it in frappe.get_all("Sales Order Item", filters={"parent": so.name}, fields=["item_code", "apparel_colour"]):
            style = frappe.db.get_value("Item", it.item_code, "variant_of")
            if style:
                k = "%s|%s" % (style, (it.apparel_colour or "").strip())
                if k not in item_of:
                    item_of[k] = [style, (it.apparel_colour or "").strip(), it.item_code]
                    order.append(k)
        for k in order:
            style = item_of[k][0]
            colour = item_of[k][1]
            item_code = item_of[k][2]
            samples = frappe.get_all("Sample Approval", filters=scope_filters(so.name, style), fields=["name", "sample_type", "status", "colour", "due_date"])
            row = {"sales_order": so.name, "customer": so.customer, "style_item": style, "colour": colour}
            dues = []
            overdue = 0
            rules = get_rules(so.customer, so.name, style)
            for stype in types:
                rule = rules[stype]
                gate_type = effective_gate(rule, so.name)
                mine = [s for s in samples if s.sample_type == stype and (not rule["per_colour"] or not (s.colour or "").strip() or norm(s.colour) == norm(colour))]
                bad = [s for s in mine if s.status not in GATE_OK]
                if bad:
                    row[key(stype)] = bad[0].status
                elif mine:
                    row[key(stype)] = "Approved"
                else:
                    row[key(stype)] = "Missing" if gate_type == "Required" else "-"
                for s in bad:
                    if s.due_date:
                        dues.append(getdate(s.due_date))
                        overdue = overdue + (1 if getdate(s.due_date) < today else 0)
            gate = run_script("arinox_work_order_api_get_bulk_gate", production_item=item_code, sales_order=so.name).get("arinox_result")
            row["next_due"] = min(dues) if dues else None
            row["overdue"] = overdue
            row["gate"] = "Open" if not gate["blockers"] else "Blocked"
            if filters.get("only_blocked") and row["gate"] == "Open":
                continue
            rows.append(row)
    return (columns, rows)


data = list(main(filters))
