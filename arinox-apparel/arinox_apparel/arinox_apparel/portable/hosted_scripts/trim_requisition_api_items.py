# API arinox_trim_requisition_create_trim_items: a plain stock item for every row that has none (answers the rows and the item codes made).
def main():
    # include: lib_mat.py
    # include: lib_items.py
    d = json.loads(frappe.form_dict.get("doc") or "{}")
    items = list(d.get("items") or [])
    made = []
    for r in items:
        if r.get("trim_item"):
            continue
        raw = (r.get("buyer_item_code") or r.get("description") or "").strip()
        code = ""
        dash = False
        for ch in raw:
            if ch.isalnum() and ch.isascii():
                code = code + ch
                dash = False
            elif not dash:
                code = code + "-"
                dash = True
        code = code.strip("-").upper()[:60]
        if not code:
            frappe.throw("Row %s: enter a buyer item code or a description first." % r.get("idx"))
        uom = r.get("consumption_uom") if r.get("calc_basis") == "By Length" and r.get("consumption_uom") else "Nos"
        r["trim_item"] = ensure_trim_item("TRIM-" + code, r.get("description"), r.get("trim_category"), uom, d.get("customer"), r.get("buyer_item_code"),
                                         frappe.utils.cint(r.get("customer_provided")))
        made.append(r["trim_item"])
    frappe.flags.arinox_result = {"arinox_doc": {"items": items}, "made": made}


main()
