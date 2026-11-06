# API arinox_sample_approval_load_spec_from_tech_pack: the measurement table filled with the tech pack spec for the sample size (answers the unsaved rows).
def main():
    d = json.loads(frappe.form_dict.get("doc") or "{}")
    if not d.get("tech_pack"):
        frappe.throw("Select the Tech Pack first.")
    if not d.get("sample_size"):
        frappe.throw("Enter the sample size first.")
    tp = frappe.get_doc("Tech Pack", d.get("tech_pack"))
    rows = []
    col = d.get("sample_size").strip().lower()
    if col not in ["xxs", "xs", "s", "m", "l", "xl", "xxl"]:
        frappe.throw("Sample size %s is not a standard size on the Tech Pack." % d.get("sample_size"))
    for m in tp.measurements:
        if frappe.utils.flt(m.get(col)):
            rows.append({"pom_code": m.pom_code, "point_of_measure": m.point_of_measure, "size": d.get("sample_size").strip().upper(), "spec": m.get(col), "tol_plus": m.tolerance, "tol_minus": m.tolerance})
    if not rows:
        frappe.throw("The Tech Pack has no measurements for size %s." % d.get("sample_size"))
    frappe.flags.arinox_result = {"arinox_doc": {"measurements": rows}, "count": len(rows)}


main()
