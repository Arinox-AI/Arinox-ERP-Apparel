# Cost Head, Before Save: material scope only for heads priced from materials; Profit must be a percentage; a head used by an enabled Costing Parameter cannot be disabled.
def run(doc):
    if doc.calc_type != "From Materials":
        doc.material_scope = None
    if doc.head_group == "Profit" and doc.calc_type not in ("Percent of Subtotal", "Percent of Product Cost", "Percent of Price"):
        frappe.throw("Profit must be a percentage: Percent of Subtotal (markup on cost, as on the costing sheet), Percent of Product Cost, or Percent of Price.")
    if not doc.enabled and not doc.is_new():
        used = frappe.db.sql("""select p.name from `tabCosting Parameter Rate` r join `tabCosting Parameter` p on p.name = r.parent
            where r.cost_head = %s and p.enabled = 1 limit 1""", doc.name)
        if used:
            frappe.throw("Cost head is used by enabled Costing Parameter %s." % used[0][0])


run(doc)
