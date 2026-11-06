# Needle Detector Log, Before Save: a failed check needs the action taken, and the number scanned again when a re-scan is logged.
def run(doc):
    if doc.result == "Fail":
        if not (doc.action or "").strip():
            frappe.throw("A failed check needs the action taken.")
        if doc.rescan_done and not frappe.utils.cint(doc.garments_rescanned):
            frappe.throw("Enter how many garments were scanned again.")
    else:
        doc.rescan_done = 0


run(doc)
