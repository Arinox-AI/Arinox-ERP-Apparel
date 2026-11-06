# API arinox_trim_inspection_make_inspection: a new inspection for one received row (unsaved; a fabric one comes with its rolls loaded).
def main():
    f = frappe.form_dict
    kind = "Trim"
    pr = frappe.get_doc("Purchase Receipt", f.get("purchase_receipt"))
    pr.check_permission("read")
    dt = "Fabric Inspection" if kind == "Fabric" else "Trim Inspection"
    frappe.new_doc(dt).check_permission("create")
    row = frappe.db.get_value("Purchase Receipt Item", {"name": f.get("purchase_receipt_item"), "parent": pr.name}, ["stock_qty", "serial_and_batch_bundle"], as_dict=True)
    if not row:
        frappe.throw("Row %s is not on %s." % (f.get("purchase_receipt_item"), pr.name))
    if pr.docstatus != 1:
        frappe.throw("Purchase Receipt %s is not submitted. Inspect goods that have been received." % pr.name)
    doc = frappe.new_doc(dt)
    doc.purchase_receipt = pr.name
    doc.purchase_receipt_item = f.get("purchase_receipt_item")
    if kind == "Fabric":
        batches = []
        if row.serial_and_batch_bundle:
            batches = [e.batch_no for e in frappe.get_all("Serial and Batch Entry", filters={"parent": row.serial_and_batch_bundle}, fields=["batch_no"]) if e.batch_no]
        for b in sorted(batches):
            doc.append("rolls", {"batch": b, "inspected": 1})
    else:
        doc.received_date = pr.posting_date
        doc.received_qty = row.stock_qty
        doc.warehouse_incharge = frappe.session.user
    frappe.flags.arinox_result = doc.as_dict()


main()
