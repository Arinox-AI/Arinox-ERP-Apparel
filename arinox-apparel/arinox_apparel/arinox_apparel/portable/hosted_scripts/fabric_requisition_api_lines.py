# API arinox_fabric_requisition_get_lines_from_sales_orders: one row per style x colour x fabric of the Tech Pack, quantities from the Sales Order (appended to the form's rows).
# A row already on the form is recognised by its Tech Pack material row (or description), so two fabrics of one style and colour with no linked item are both kept.
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
    have = ["|".join([i.get("sales_order") or "", i.get("style_item") or "", (i.get("colour") or "").strip().upper(), i.get("material_role") or "", i.get("fabric_item") or "", i.get("tech_pack_material") or i.get("fabric_description") or ""]) for i in items]
    added = 0
    for so in sos:
        for line in fr_lines_for_sales_order(so, d.get("customer"), d.get("company")):
            k = "|".join([line.get("sales_order") or "", line.get("style_item") or "", (line.get("colour") or "").strip().upper(), line.get("material_role") or "", line.get("fabric_item") or "", line.get("tech_pack_material") or line.get("fabric_description") or ""])
            if k in have:
                continue
            have.append(k)
            items.append(line)
            added = added + 1
    frappe.flags.arinox_result = {"arinox_doc": {"items": items}, "count": added}


main()
