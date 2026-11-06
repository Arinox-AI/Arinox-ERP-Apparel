# API arinox_production_card_save_production_card: create or update a DRAFT production card (validation runs). Never submits.
def main():
    data = frappe.form_dict.get("data")
    data = json.loads(data) if isinstance(data, str) else data
    if data.get("name") and frappe.db.exists("Production Card", data["name"]):
        doc = frappe.get_doc("Production Card", data["name"])
        if doc.docstatus != 0:
            frappe.throw("Only a draft production card can be changed here.")
        doc.check_permission("write")
        for k in data:
            if k not in ("name", "doctype", "docstatus"):
                doc.set(k, data[k])
    else:
        frappe.new_doc("Production Card").check_permission("create")
        d = dict(data)
        d["doctype"] = "Production Card"
        doc = frappe.get_doc(d)
    doc.save()
    frappe.flags.arinox_result = {"name": doc.name, "red_flags": doc.red_flags, "planned_cut_total": sum([frappe.utils.cint(r.planned_cut_qty) for r in doc.lines])}


main()
