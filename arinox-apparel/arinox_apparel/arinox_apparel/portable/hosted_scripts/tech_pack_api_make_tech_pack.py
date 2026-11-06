# API arinox_tech_pack_make_tech_pack: Opportunity -> new Tech Pack (unsaved, returned as a document for the form to open).
def main():
    opp = frappe.get_doc("Opportunity", frappe.form_dict.get("source_name"))
    opp.check_permission("read")
    if opp.opportunity_from != "Customer":
        frappe.throw("Convert the Lead to a Customer before recording a Tech Pack for it.")
    tp = frappe.new_doc("Tech Pack")
    tp.customer = opp.party_name
    tp.opportunity = opp.name
    tp.product_type = opp.get("apparel_product_type")
    tp.season = opp.get("apparel_season")
    tp.source_reference = opp.get("apparel_source_email")
    frappe.flags.arinox_result = tp.as_dict()


main()
