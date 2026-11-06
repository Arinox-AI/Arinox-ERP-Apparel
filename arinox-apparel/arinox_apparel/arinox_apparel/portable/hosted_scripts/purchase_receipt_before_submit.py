# Purchase Receipt, Before Submit: a fabric row from an FR needs its roll list; each fabric roll is tracked.
def run(doc):
    for pri in doc.items:
        if not pri.get("purchase_order_item"):
            continue
        kind = frappe.db.get_value("Purchase Order Item", pri.purchase_order_item, "apparel_requisition_type")
        if kind == "FR" and frappe.db.get_value("Item", pri.item_code, "has_batch_no") and not (pri.get("serial_and_batch_bundle") or pri.get("batch_no")):
            frappe.throw("Row %s (%s): import the roll list before submitting. Each fabric roll is tracked." % (pri.idx, pri.item_code))


run(doc)
