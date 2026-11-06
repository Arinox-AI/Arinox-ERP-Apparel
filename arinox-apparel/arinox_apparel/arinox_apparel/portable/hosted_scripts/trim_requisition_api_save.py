# API arinox_trim_requisition_save_trim_requisition: create or update a DRAFT trim requisition. Validation runs. Never submits. Answers the name.
def main():
    data = frappe.form_dict.get("data")
    data = json.loads(data) if isinstance(data, str) else data
    if data.get("name") and frappe.db.exists("Trim Requisition", data["name"]):
        doc = frappe.get_doc("Trim Requisition", data["name"])
        if doc.docstatus != 0:
            frappe.throw("Only a draft can be changed. Use Revise on an approved requisition.")
        doc.check_permission("write")
        for k in data:
            if k not in ("name", "items", "doctype"):
                doc.set(k, data[k])
        if "items" in data:
            doc.set("items", data["items"])
        doc.save()
    else:
        d = {}
        for k in data:
            if k != "name":
                d[k] = data[k]
        d["doctype"] = "Trim Requisition"
        doc = frappe.get_doc(d)
        doc.check_permission("create")
        doc.insert()
    frappe.flags.arinox_result = doc.name


main()
