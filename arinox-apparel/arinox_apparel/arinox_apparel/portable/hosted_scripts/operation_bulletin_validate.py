# Operation Bulletin, Before Save: totals of the timed operations, the daily and hourly target from the working minutes and expected efficiency, the pitch time, balance flags.
def run(doc):
    # include: lib_sewing.py
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    BAND = 0.15       # an operation within +-15 % of the pitch time is balanced
    if cint(doc.operators) <= 0:
        frappe.throw("Enter the number of operators.")
    minutes = cint(doc.working_minutes) or cint(frappe.db.get_single_value("Apparel Settings", "work_minutes_per_day") or 480)
    eff = flt(doc.expected_efficiency_pct) or flt(frappe.db.get_single_value("Apparel Settings", "planned_efficiency_pct") or 65)
    doc.working_minutes = minutes
    doc.expected_efficiency_pct = eff
    timed = []
    for o in doc.operations:
        if flt(o.machine_sam) < 0 or flt(o.manual_sam) < 0:
            frappe.throw("Row %s: a time cannot be negative." % o.idx)
        if flt(o.machine_sam) + flt(o.manual_sam) > 0:
            timed.append(o)
    doc.operation_count = len(timed)
    doc.sewing_sam = round(sum([flt(o.machine_sam) for o in timed]), 3)
    doc.manual_sam = round(sum([flt(o.manual_sam) for o in timed]), 3)
    doc.total_sam = round(doc.sewing_sam + doc.manual_sam, 3)
    doc.target_per_day = round(day_target(doc.operators, minutes, eff, doc.total_sam), 2)
    doc.target_per_hour = round(hour_target(doc.operators, minutes, eff, doc.total_sam), 2)
    doc.pcs_per_machine = round(pcs_per_machine_per_day(minutes, eff, doc.total_sam), 4)
    doc.pitch_time = round(doc.total_sam / len(timed), 3) if timed else 0
    for o in doc.operations:
        sam = flt(o.machine_sam) + flt(o.manual_sam)
        if sam <= 0:
            o.target_per_hr = 0
            o.operators_needed = 0
            o.pitch_flag = ""
            continue
        o.target_per_hr = round(operation_target_per_hour(sam, eff), 2)
        o.operators_needed = round(doc.target_per_hour / o.target_per_hr, 2) if o.target_per_hr else 0
        o.pitch_flag = "Above" if sam > doc.pitch_time * (1 + BAND) else ("Below" if sam < doc.pitch_time * (1 - BAND) else "")


run(doc)
