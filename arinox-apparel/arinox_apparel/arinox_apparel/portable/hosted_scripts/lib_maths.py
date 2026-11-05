# shared helpers: pure production maths (production/maths.py)
def planned_cut(order_qty, extra_pct):
    q = float(order_qty or 0)
    if q <= 0:
        return 0
    return int(frappe.utils.ceil(round(q * (1 + float(extra_pct or 0) / 100.0), 6)))


def max_ship_qty(order_qty, tolerance_pct):
    return int(frappe.utils.floor(round(float(order_qty or 0) * (1 + float(tolerance_pct or 0) / 100.0), 6)))


def norm(text):
    return (text or "").strip().upper()


def to_metres(qty, uom, gsm, width_cm):
    kind = {"m": "m", "meter": "m", "metre": "m", "mtr": "m", "mtrs": "m", "meters": "m", "metres": "m", "yd": "yd", "yds": "yd",
            "yard": "yd", "yards": "yd", "kg": "kg", "kgs": "kg", "kilogram": "kg", "kilograms": "kg"}.get((uom or "").strip().lower())
    q = frappe.utils.flt(qty)
    if kind == "m":
        return q
    if kind == "yd":
        return q * 0.9144
    if kind == "kg":
        if not frappe.utils.flt(gsm) or not frappe.utils.flt(width_cm):
            frappe.throw("GSM and cuttable width are needed to convert kg to metres.")
        return q * 1000 / (frappe.utils.flt(gsm) * frappe.utils.flt(width_cm) / 100)
    frappe.throw("Cannot convert UOM %s to metres. Use Meter, Yard or Kg for fabric." % uom)


def my_roles():
    return frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")


def has_any_role(names):
    mine = my_roles()
    for n in names:
        if n in mine:
            return True
    return False
