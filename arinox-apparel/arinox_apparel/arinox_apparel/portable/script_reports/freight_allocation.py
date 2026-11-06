def main(filters):
    # include: lib_shipping.py
    # include: lib_shipment.py
    columns = [{"fieldname": "shipment", "label": "Shipment", "fieldtype": "Link", "options": "Shipment", "width": 130},
               {"fieldname": "contract", "label": "Contract / Order", "fieldtype": "Data", "width": 190}, {"fieldname": "basis", "label": "Basis", "fieldtype": "Data", "width": 90},
               {"fieldname": "share_pct", "label": "Share %", "fieldtype": "Percent", "width": 90}, {"fieldname": "cost", "label": "Allocated Cost", "fieldtype": "Float", "width": 120},
               {"fieldname": "estimate", "label": "Quote", "fieldtype": "Float", "width": 110}, {"fieldname": "actual", "label": "Forwarder Bills", "fieldtype": "Float", "width": 120},
               {"fieldname": "variance", "label": "Bills vs Quote %", "fieldtype": "Percent", "width": 120}]
    cond = {"docstatus": ["<", 2], "apparel_mode": ["is", "set"]}
    if filters.get("shipment"):
        cond["name"] = filters.get("shipment")
    rows = []
    for s in frappe.get_all("Shipment", filters=cond, fields=["name", "apparel_estimate_total", "apparel_actual_total", "apparel_cost_variance_pct"]):
        res = allocated_costs(s.name)
        for r in res[0]:
            rows.append({"shipment": s.name, "contract": r[0], "basis": "CBM" if res[1] == "cbm" else "kg", "share_pct": round(r[1] * 100, 2), "cost": r[2],
                         "estimate": s.apparel_estimate_total, "actual": s.apparel_actual_total, "variance": s.apparel_cost_variance_pct})
    return (columns, rows)


data = list(main(filters))
