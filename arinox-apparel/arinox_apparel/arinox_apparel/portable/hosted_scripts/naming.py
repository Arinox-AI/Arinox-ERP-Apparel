# Before Insert, one record per doctype that the app names in Python (autoname()). The doctype names itself from the hidden
# field arinox_name (autoname field:arinox_name); this script fills that field. Counters come from Arinox Number, a doctype
# whose own naming series hands out numbers that never repeat (the same job getseries did).
# Everything sits inside one function: in the sandbox, module-level functions cannot see each other.

def run(doc):
    def two(n):
        return ("0" + str(n))[-2:]

    def draw(prefix, digits):
        n = frappe.get_doc({"doctype": "Arinox Number", "prefix": prefix}).insert(ignore_permissions=True)
        return prefix + str(int(n.name[len(prefix):])).zfill(digits)

    def dated(prefix, on):
        d = frappe.utils.getdate(on or frappe.utils.nowdate())
        return prefix + str(d.year)[2:] + "." + two(d.month) + "."

    def company_prefix(company, field, fallback):
        value = ""
        if company:
            value = frappe.db.get_value("Company", company, field) or ""
        return (value or fallback).strip()

    def root_of_order(sales_order):
        if not sales_order:
            return None
        return frappe.db.get_value("Sales Order", sales_order, "apparel_sales_contract") or sales_order

    def root_of_card(card):
        return root_of_order(frappe.db.get_value("Production Card", card, "sales_order"))

    def serial(root, code):
        return draw(root + "-" + code + "-", 2)

    dt = doc.doctype
    if doc.get("arinox_name"):
        return
    name = None
    if dt == "Sales Contract":
        prefix = company_prefix(doc.company, "apparel_contract_prefix", "") or frappe.db.get_single_value("Apparel Settings", "contract_prefix") or "SC"
        name = draw(dated(prefix.strip(), doc.contract_date), 3)
    elif dt == "Fabric Requisition":
        name = draw(dated(company_prefix(doc.company, "apparel_fr_prefix", "FR"), doc.fr_date), 3)
    elif dt == "Trim Requisition":
        name = draw(dated(company_prefix(doc.company, "apparel_tr_prefix", "TR"), doc.tr_date), 3)
    elif dt == "Production Card":
        name = draw(dated(company_prefix(doc.company, "apparel_pc_prefix", "PC"), doc.issue_date), 3)
    elif dt == "Factory Allocation":
        name = "FA-" + doc.sales_order
    elif dt == "Packing List":
        name = serial(root_of_card(doc.production_card), "PL")
    elif dt == "Final Inspection":
        name = serial(root_of_card(doc.production_card), "FI")
    elif dt == "Finishing Receipt":
        name = serial(root_of_card(doc.production_card), "FIN")
    elif dt == "Subcontract Challan":
        name = serial(root_of_card(doc.production_card), "SC")
    elif dt == "Subcontract Return":
        name = serial(root_of_card(frappe.db.get_value("Subcontract Challan", doc.challan, "production_card")), "SR")
    elif dt == "Subcontract Settlement":
        name = serial(root_of_card(frappe.db.get_value("Subcontract Challan", doc.challan, "production_card")), "SS")
    elif dt == "Buyer Claim":
        name = serial(frappe.db.get_value("Sales Invoice", doc.sales_invoice, "apparel_sales_contract") or doc.sales_invoice, "CL")
    if name:
        doc.arinox_name = name


run(doc)
