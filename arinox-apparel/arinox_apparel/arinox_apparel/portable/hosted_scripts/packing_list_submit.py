# Packing List, Before Submit: every carton row has a gross weight (net not above gross), a heavy carton warns, and a failed or missing
# needle-detector check blocks packing (or warns) as the settings say.
def run(doc):
    flt = frappe.utils.flt
    if not doc.cartons:
        frappe.throw("Add the cartons, or use Generate Cartons.")
    for c in doc.cartons:
        if flt(c.gross_weight_kg) <= 0:
            frappe.throw("Enter the gross weight of every carton row (row %s)." % c.idx)
    maxkg = flt(frappe.db.get_single_value("Apparel Settings", "carton_max_gross_kg") or 0)
    for c in doc.cartons:
        if flt(c.net_weight_kg) > flt(c.gross_weight_kg):
            frappe.throw("Carton row %s: net weight is more than gross." % c.idx)
        if maxkg and flt(c.gross_weight_kg) > maxkg:
            frappe.msgprint("Carton row %s: %s kg gross is above the %s kg limit." % (c.idx, c.gross_weight_kg, maxkg), indicator="orange")

    mode = frappe.db.get_single_value("Apparel Settings", "needle_check_required") or "Off"
    if mode != "Off":
        line = frappe.db.get_value("Production Card", doc.production_card, "line")
        day = frappe.utils.getdate(doc.packing_date)
        problems = []
        base = {"line": line} if line else {}
        passed = dict(base)
        passed["check_date"] = day
        passed["result"] = "Pass"
        if not frappe.db.exists("Needle Detector Log", passed):
            problems.append("No passing needle detector check is logged for %s on %s." % (line or "any line", day))
        failed_filter = dict(base)
        failed_filter["result"] = "Fail"
        failed_filter["rescan_done"] = 0
        failed_filter["check_date"] = [">=", frappe.utils.add_days(day, -7)]
        failed = frappe.get_all("Needle Detector Log", failed_filter, pluck="name")
        if failed:
            problems.append("Failed detector check(s) %s have no re-scan logged." % ", ".join(failed))
        if problems:
            if mode == "Block":
                frappe.throw("<br>".join(problems), title="Needle detector")
            frappe.msgprint("<br>".join(problems), indicator="orange", title="Needle detector")


run(doc)
