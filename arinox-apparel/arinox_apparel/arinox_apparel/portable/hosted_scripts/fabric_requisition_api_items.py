# API arinox_fabric_requisition_create_fabric_items: the template and colour variant for every row that has none (answers the rows and the item codes made).
def main():
    # include: lib_mat.py
    # include: lib_items.py
    d = json.loads(frappe.form_dict.get("doc") or "{}")
    items = list(d.get("items") or [])
    made = []
    for r in items:
        if r.get("fabric_item"):
            continue
        code = (r.get("fabric_description") or "").split(",")[0].strip()
        if not code:
            frappe.throw("Row %s: the description must start with the fabric quality code." % r.get("idx"))
        r["fabric_item"] = ensure_fabric_item(code, r.get("fabric_colour") or r.get("colour"), r.get("fabric_description"), r.get("gsm"), r.get("cuttable_width_cm"))
        made.append(r["fabric_item"])
    frappe.flags.arinox_result = {"arinox_doc": {"items": items}, "made": made}


main()
