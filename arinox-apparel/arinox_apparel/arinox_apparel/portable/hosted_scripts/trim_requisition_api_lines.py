# API arinox_trim_requisition_get_lines_from_sales_orders: one row per non-fabric material of the Tech Pack (by size, colour, carton, length or per garment), quantities from the Sales Order (appended to the form's rows).
def main():
    # include: lib_samples.py
    # include: lib_allocation.py
    # include: lib_mat.py
    # include: lib_purchasing.py
    # include: lib_requisition.py
    d = json.loads(frappe.form_dict.get("doc") or "{}")
    sos = frappe.form_dict.get("sales_orders")
    sos = json.loads(sos) if isinstance(sos, str) else sos
    items = list(d.get("items") or [])
    have = ["|".join([i.get("sales_order") or "", i.get("style_item") or "", (i.get("colour") or "").strip().upper(), (i.get("size") or "").strip().upper(), i.get("trim_category") or "", i.get("trim_item") or i.get("description") or "", (i.get("trim_colour") or "").strip().upper()]) for i in items]
    added = 0
    for so in sos:
        for line in tr_lines_for_sales_order(so, d.get("customer"), d.get("company")):
            k = "|".join([line.get("sales_order") or "", line.get("style_item") or "", (line.get("colour") or "").strip().upper(), (line.get("size") or "").strip().upper(), line.get("trim_category") or "", line.get("trim_item") or line.get("description") or "", (line.get("trim_colour") or "").strip().upper()])
            if k in have:
                continue
            have.append(k)
            items.append(line)
            added = added + 1
    frappe.flags.arinox_result = {"arinox_doc": {"items": items}, "count": added}


main()
