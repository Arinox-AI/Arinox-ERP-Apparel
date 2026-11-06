# API arinox_production_card_get_summary: stage totals per colour x size for one card, with the plan next to them.
def main():
    card = frappe.form_dict.get("name")
    doc = frappe.get_doc("Production Card", card)
    res = run_script("arinox_engine", action="totals", card=card)
    t = res.get("arinox_result") or {}
    rows = []
    for l in doc.lines:
        row = {"colour": l.colour, "size": l.size, "order_qty": l.order_qty, "planned_cut_qty": l.planned_cut_qty}
        prefix = l.colour + "|" + l.size + "|"
        for k in t:
            if k.startswith(prefix):
                row[k[len(prefix):]] = t[k]
        rows.append(row)
    frappe.flags.arinox_result = {"card": card, "status": doc.status, "rows": rows}


main()
