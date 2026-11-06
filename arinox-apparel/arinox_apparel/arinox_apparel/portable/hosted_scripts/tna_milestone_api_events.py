# API arinox_tna_milestone_get_events: calendar events for the Calendar view, one per milestone, coloured by its current status.
def main():
    # include: lib_tna.py
    start = frappe.form_dict.get("start")
    end = frappe.form_dict.get("end")
    flt_ = frappe.form_dict.get("filters")
    flt_ = json.loads(flt_) if isinstance(flt_, str) and flt_ else (flt_ or [])
    rows = frappe.get_list("TNA Milestone", filters=flt_ + [["planned_date", "<=", end], ["planned_date", ">=", start]],
                           fields=["name", "label", "style_no", "colour", "planned_start", "planned_date", "revised_date", "actual_date", "status", "color", "not_applicable"])
    out = []
    for r in rows:
        if frappe.utils.cint(r.not_applicable):
            continue
        date = r.actual_date or r.revised_date or r.planned_date
        out.append({"name": r.name, "title": ("%s %s: %s" % (r.style_no or "", r.colour or "", r.label)).strip(), "start": str(date), "end": str(date), "allDay": 1,
                    "color": r.color or COLOURS.get(r.status), "status": r.status})
    frappe.flags.arinox_result = out


main()
