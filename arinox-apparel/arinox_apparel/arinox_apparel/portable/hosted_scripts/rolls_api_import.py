# API arinox_rolls_import_roll_list: a Batch per roll and the bundle for one row of a draft Purchase Receipt. `rolls` is a JSON list or pasted text
# ('roll no, dye lot, length[, width]' per line). The roll total must equal the row quantity unless update_row_qty is set.
def main():
    # include: lib_mat.py
    flt = frappe.utils.flt
    f = frappe.form_dict
    pr = frappe.get_doc("Purchase Receipt", f.get("pr_name"))
    pr.check_permission("write")
    if pr.docstatus != 0:
        frappe.throw("Roll lists can only be imported into a draft receipt.")
    row_name = f.get("row_name")
    row = None
    for r in pr.items:
        if r.name == row_name:
            row = r
    if not row:
        frappe.throw("Row not found on %s." % pr.name)
    if not frappe.db.get_value("Item", row.item_code, "has_batch_no"):
        frappe.throw("%s is not batch tracked, so it has no rolls." % row.item_code)
    rolls = f.get("rolls")
    if isinstance(rolls, str):
        try:
            rolls = json.loads(rolls)
        except Exception:
            parsed = []
            for line in rolls.splitlines():
                s = line.strip().replace("\t", ",").replace(";", ",")
                parts = [p.strip() for p in s.split(",") if p.strip()]
                if len(parts) < 3:
                    s2 = s
                    while "  " in s2:
                        s2 = s2.replace("  ", ",")
                    parts = [p.strip() for p in s2.split(",") if p.strip()]
                if len(parts) < 3:
                    continue
                try:
                    length = float(parts[2])
                except Exception:
                    continue
                width = None
                if len(parts) > 3:
                    try:
                        width = float(parts[3])
                    except Exception:
                        width = None
                parsed.append({"roll_no": parts[0], "dye_lot": parts[1], "length": length, "width_cm": width})
            rolls = parsed
    clean = []
    seen = []
    for r in rolls:
        roll_no = str(r.get("roll_no") or "").strip()
        if not roll_no:
            frappe.throw("Every roll needs a roll number.")
        if roll_no.upper() in seen:
            frappe.throw("Roll number %s appears twice in the list." % roll_no)
        seen.append(roll_no.upper())
        length = flt(r.get("length"))
        if length <= 0:
            frappe.throw("Roll %s: the length must be more than zero." % roll_no)
        clean.append({"roll_no": roll_no, "dye_lot": (r.get("dye_lot") or "").strip(), "length": length, "width_cm": flt(r.get("width_cm")) or None})
    if not clean:
        frappe.throw("The roll list is empty.")
    stock_uom = frappe.db.get_value("Item", row.item_code, "stock_uom")
    gsm = frappe.db.get_value("Item", row.item_code, "apparel_fabric_gsm")
    length_uom = f.get("length_uom") or "Meter"
    total = 0
    for r in clean:
        r["metres"] = to_metres(r["length"], length_uom, gsm, r["width_cm"] or frappe.db.get_value("Item", row.item_code, "apparel_fabric_width_cm"))
        total = total + r["metres"]
    stock_qty = flt(row.stock_qty) or flt(row.qty) * (flt(row.conversion_factor) or 1)
    if abs(total - stock_qty) > max(0.005 * stock_qty, 0.01):
        if not frappe.utils.cint(f.get("update_row_qty")):
            frappe.throw("The roll list adds up to %s %s but the receipt row says %s. Fix the list, or change the row quantity." % (flt(total, 2), stock_uom, flt(stock_qty, 2)))
        row.qty = total / (flt(row.conversion_factor) or 1)
        row.received_qty = row.qty + flt(row.rejected_qty)
        pr.save()
        for r in pr.items:
            if r.name == row_name:
                row = r
    # a re-import replaces the draft bundle and the batches this receipt made
    old_bundle = row.get("serial_and_batch_bundle")
    if old_bundle:
        old = frappe.get_doc("Serial and Batch Bundle", old_bundle)
        if old.docstatus != 0:
            frappe.throw("Row %s already has a submitted roll bundle." % row.idx)
        old_batches = [e.batch_no for e in old.entries if e.batch_no]
        row.db_set({"serial_and_batch_bundle": None, "use_serial_batch_fields": 0})
        frappe.delete_doc("Serial and Batch Bundle", old_bundle, ignore_permissions=True, force=True)
        for b in old_batches:
            if frappe.db.exists("Batch", b) and frappe.db.get_value("Batch", b, "reference_name") == pr.name:
                frappe.delete_doc("Batch", b, ignore_permissions=True, force=True)
    entries = []
    for r in clean:
        bid = ("%s-%s" % (pr.name, r["roll_no"]))[:140]
        if frappe.db.exists("Batch", bid):
            frappe.throw("Batch %s already exists. Roll numbers must be unique within a receipt." % bid)
        b = frappe.get_doc({"doctype": "Batch", "batch_id": bid, "item": row.item_code, "supplier": pr.supplier, "reference_doctype": "Purchase Receipt", "reference_name": pr.name,
                            "apparel_roll_no": r["roll_no"], "apparel_dye_lot": r["dye_lot"], "apparel_ticket_length": r["metres"], "apparel_width_cm": r["width_cm"],
                            "apparel_inspection_status": "Uninspected"})
        b.flags.ignore_permissions = True
        b.insert()
        entries.append({"batch_no": b.name, "qty": flt(r["metres"], 6), "warehouse": row.warehouse})
    bundle = frappe.get_doc({"doctype": "Serial and Batch Bundle", "item_code": row.item_code, "warehouse": row.warehouse, "type_of_transaction": "Inward",
                             "voucher_type": "Purchase Receipt", "voucher_no": pr.name, "voucher_detail_no": row.name, "company": pr.company, "posting_date": pr.posting_date,
                             "posting_time": pr.posting_time, "has_batch_no": 1, "entries": entries})
    bundle.flags.ignore_permissions = True
    bundle.insert()
    row.db_set({"serial_and_batch_bundle": bundle.name, "use_serial_batch_fields": 0, "batch_no": None})
    frappe.flags.arinox_result = {"rolls": len(entries), "total": flt(total, 2), "bundle": bundle.name}


main()
