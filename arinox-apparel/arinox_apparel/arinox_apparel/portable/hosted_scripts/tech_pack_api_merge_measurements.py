# API arinox_tech_pack_merge_measurements: converts Tech Pack measurement rows saved in the OLD layout (one row per point per size, fields
# size / value / tolerance_plus / tolerance_minus) to the current layout (one row per point, one column per size xxs..xxl, one tolerance).
# Needed only on a site that once held the old Tech Pack Measurement doctype: the old columns stay in the table, the new ones start at 0, so
# every point shows once per size with all sizes at 0 and the "entered twice" rule blocks the Tech Pack. A site that never had the old layout
# has no old columns and this returns converted = 0. Works on every Tech Pack, any customer. Safe to run again. Needs System Manager or
# Script Manager. Optional: tech_pack = one Tech Pack only.
def main():
    mine = frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")
    if frappe.session.user != "Administrator" and "System Manager" not in mine and "Script Manager" not in mine:
        frappe.throw("Only a System Manager or Script Manager can convert Tech Pack measurements.")

    standard = ["xxs", "xs", "s", "m", "l", "xl", "xxl"]
    # the sandbox has no has_column: read the column list with a plain select
    have = frappe.db.sql(
        "select column_name from information_schema.columns where table_schema = database() and table_name = 'tabTech Pack Measurement'", pluck=True)
    if "size" not in have or "value" not in have:
        frappe.flags.arinox_result = {"converted_points": 0, "removed_rows": 0, "left_alone": 0, "note": "no old-layout columns on this site; nothing to convert"}
        return
    plus = "tolerance_plus" if "tolerance_plus" in have else "0"
    minus = "tolerance_minus" if "tolerance_minus" in have else "0"

    only = frappe.form_dict.get("tech_pack")
    where = "parenttype = 'Tech Pack' and ifnull(size, '') != ''"
    args = []
    if only:
        where = where + " and parent = %s"
        args.append(only)
    rows = frappe.db.sql(
        "select name, parent, parentfield, idx, pom_code, point_of_measure, size, value, " + plus + " as tol_plus, " + minus + " as tol_minus "
        "from `tabTech Pack Measurement` where " + where + " order by parent, parentfield, idx",
        args, as_dict=True)

    # one group per point of measure inside a Tech Pack, in the order the points first appear
    groups = {}
    order = []
    for r in rows:
        key = "%s|%s|%s|%s" % (r.parent, r.parentfield, (r.pom_code or "").strip().upper(), (r.point_of_measure or "").strip().upper())
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)

    converted = 0
    removed = 0
    left_alone = 0     # a size that is not one of the seven columns (for example "14") cannot be stored in the new layout
    touched = []
    for key in order:
        members = groups[key]
        usable = [m for m in members if (m.size or "").strip().lower() in standard]
        left_alone = left_alone + len(members) - len(usable)
        if not usable:
            continue
        keeper = usable[0]
        values = {}
        tol = 0
        for m in usable:
            values[(m.size or "").strip().lower()] = m.value or 0
            tol = max(tol, m.tol_plus or 0, m.tol_minus or 0)
        values["tolerance"] = tol
        values["size"] = None
        values["value"] = 0
        frappe.db.set_value("Tech Pack Measurement", keeper.name, values, update_modified=False)
        for m in usable[1:]:
            frappe.delete_doc("Tech Pack Measurement", m.name, force=1, ignore_permissions=True)
            removed = removed + 1
        converted = converted + 1
        mark = keeper.parent + "|" + keeper.parentfield
        if mark not in touched:
            touched.append(mark)

    # close the gaps in the row numbers
    for mark in touched:
        parent = mark.split("|")[0]
        field = mark.split("|")[1]
        names = frappe.get_all("Tech Pack Measurement", {"parent": parent, "parentfield": field}, pluck="name", order_by="idx asc, creation asc")
        n = 0
        for name in names:
            n = n + 1
            frappe.db.set_value("Tech Pack Measurement", name, "idx", n, update_modified=False)

    frappe.flags.arinox_result = {"converted_points": converted, "removed_rows": removed, "left_alone": left_alone}


main()
