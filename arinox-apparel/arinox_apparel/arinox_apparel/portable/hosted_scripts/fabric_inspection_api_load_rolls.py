# API arinox_fabric_inspection_load_rolls: one roll row per batch received on the receipt row (appended to the form's rolls).
def main():
    d = json.loads(frappe.form_dict.get("doc") or "{}")
    row = frappe.db.get_value("Purchase Receipt Item", {"name": d.get("purchase_receipt_item"), "parent": d.get("purchase_receipt")}, ["serial_and_batch_bundle"], as_dict=True)
    if not row:
        frappe.throw("Row %s is not on %s." % (d.get("purchase_receipt_item"), d.get("purchase_receipt")))
    batches = []
    if row.serial_and_batch_bundle:
        batches = [e.batch_no for e in frappe.get_all("Serial and Batch Entry", filters={"parent": row.serial_and_batch_bundle}, fields=["batch_no"]) if e.batch_no]
    rolls = list(d.get("rolls") or [])
    have = [r.get("batch") for r in rolls]
    for b in sorted(batches):
        if b not in have:
            rolls.append({"batch": b, "inspected": 1})
    frappe.flags.arinox_result = {"arinox_doc": {"rolls": rolls}, "count": len(rolls)}


main()
