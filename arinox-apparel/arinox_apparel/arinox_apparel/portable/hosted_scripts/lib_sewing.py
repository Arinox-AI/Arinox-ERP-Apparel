# shared helpers from production/sewing.py and production/maths.py (sewing part): the active operation bulletin, the learning-curve day, targets, efficiency, DHU, RFT.
def active_ob(style_item):
    """The Operation Bulletin in force for a style (newest Active one), or None."""
    rows = frappe.get_all("Operation Bulletin", filters={"style_item": style_item, "status": "Active"}, order_by="version desc, creation desc", limit=1,
                          fields=["name", "total_sam", "operators", "working_minutes", "expected_efficiency_pct"])
    return rows[0] if rows else None


def learning_day(line, style_item, on_date):
    """Day number of a style on a line, counted from its first Line Input there (1 on the first day)."""
    first = frappe.db.sql("select min(i.input_date) from `tabLine Input` i join `tabProduction Card` c on c.name = i.production_card "
                          "where i.docstatus = 1 and i.line = %s and c.style_item = %s", (line, style_item))[0][0]
    if not first:
        return 1
    return max(frappe.utils.date_diff(frappe.utils.getdate(on_date), frappe.utils.getdate(first)) + 1, 1)


def curve():
    return [[r.day_no, r.pct_of_target] for r in frappe.get_all("Learning Curve Day", filters={"parent": "Apparel Settings", "parentfield": "learning_curve"}, fields=["day_no", "pct_of_target"])]


def day_target(operators, working_minutes, efficiency_pct, total_sam):
    """Garments per day = operators x working minutes x efficiency / SAM."""
    if not total_sam:
        return 0.0
    return float(operators) * float(working_minutes) * (float(efficiency_pct) / 100.0) / float(total_sam)


def hour_target(operators, working_minutes, efficiency_pct, total_sam):
    if not working_minutes:
        return 0.0
    return day_target(operators, working_minutes, efficiency_pct, total_sam) / (float(working_minutes) / 60.0)


def pcs_per_machine_per_day(working_minutes, efficiency_pct, total_sam):
    if not total_sam:
        return 0.0
    return float(working_minutes) * (float(efficiency_pct) / 100.0) / float(total_sam)


def operation_target_per_hour(sam, efficiency_pct):
    if not sam:
        return 0.0
    return 60.0 * (float(efficiency_pct) / 100.0) / float(sam)


def pct_of(numerator, denominator):
    d = float(denominator or 0)
    if not d:
        return None
    return float(numerator or 0) / d * 100.0


def learning_factor(day_no, crv):
    """crv: list of [day_no, pct_of_target]. Day beyond the table uses the last row; no table = 100 %."""
    rows = sorted([[int(d[0]), float(d[1])] for d in (crv or [])])
    if not rows:
        return 1.0
    chosen = rows[0][1]
    for d in rows:
        if day_no >= d[0]:
            chosen = d[1]
    return chosen / 100.0


def traffic_colour(defects, rules):
    """rules: list of [colour, defects_from]. The highest threshold reached wins; below all = Green."""
    chosen = "Green"
    best = -1
    for r in rules or []:
        if defects >= int(r[1]) and int(r[1]) > best:
            chosen = r[0]
            best = int(r[1])
    return chosen


def meas_compute(rows):
    """Up to five readings per point; in tolerance only when every reading is."""
    flt = frappe.utils.flt
    for m in rows:
        readings = [flt(v) for v in (m.actual, m.reading_2, m.reading_3, m.reading_4, m.reading_5) if v not in (None, "")]
        if not readings or m.spec is None:
            m.deviation = 0
            m.in_tolerance = 0
            continue
        devs = [round(x - flt(m.spec), 3) for x in readings]
        m.deviation = max(devs, key=abs)
        lo = -abs(flt(m.tol_minus))
        hi = abs(flt(m.tol_plus))
        m.in_tolerance = 1 if len([d for d in devs if lo <= d <= hi]) == len(devs) else 0
