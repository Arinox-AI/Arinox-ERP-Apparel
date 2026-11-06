# API arinox_fabric_inspection_make_purchase_return: purchase return of the rejected rolls, taken from the rejected warehouse. Answers the draft return (unsaved).
def main():
    # include: lib_mat.py
    # include: lib_purchasing.py
    # include: lib_matinsp.py
    flt = frappe.utils.flt
    fi = frappe.get_doc("Fabric Inspection", frappe.form_dict.get("inspection"))
    fi.check_permission("read")
    frappe.new_doc("Purchase Receipt").check_permission("create")
    if fi.docstatus != 1:
        frappe.throw("Submit the inspection first.")
    rejected = [r for r in fi.rolls if roll_disposition(frappe.utils.cint(r.inspected), r.roll_result, fi.lot_result) == "Rejected"]
    if not rejected:
        frappe.throw("No rolls were rejected.")
    ret = frappe.call("erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_return", source_name=fi.purchase_receipt)
    template = None
    for i in ret.items:
        if i.item_code == fi.fabric_item:
            template = i
            break
    if not template:
        frappe.throw("The fabric item is not on the receipt.")
    proto = template.as_dict()
    ret.set("items", [])
    reject_wh = company_warehouse("rejected_warehouse", fi.company)
    for r in rejected:
        line = dict(proto)
        for k in ("name", "idx", "serial_and_batch_bundle", "rejected_serial_and_batch_bundle", "creation", "modified"):
            line.pop(k, None)
        line.update({"qty": -flt(r.ticket_length), "received_qty": -flt(r.ticket_length), "stock_qty": -flt(r.ticket_length), "batch_no": r.batch, "use_serial_batch_fields": 1,
                     "warehouse": reject_wh, "rejected_qty": 0, "rejected_warehouse": None})
        ret.append("items", line)
    frappe.flags.arinox_result = ret.as_dict()


main()
