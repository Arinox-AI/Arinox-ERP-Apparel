# API arinox_cost_sheet_get_previous_costing: the materials and charges of an earlier Cost Sheet, for copying into a new one.
def main():
    doc = frappe.get_doc("Cost Sheet", frappe.form_dict.get("cost_sheet"))
    doc.check_permission("read")
    skip = ("name", "parent", "parentfield", "parenttype", "idx", "creation", "modified", "owner", "modified_by", "docstatus")
    mats = []
    for m in doc.materials:
        d = m.as_dict()
        mats.append({k: d[k] for k in d if k not in skip})
    chs = []
    for c in doc.charges:
        d = c.as_dict()
        row = {k: d[k] for k in d if k not in skip}
        row["source"] = "Previous Costing"
        chs.append(row)
    frappe.flags.arinox_result = {"materials": mats, "charges": chs, "sam": doc.sam}


main()
