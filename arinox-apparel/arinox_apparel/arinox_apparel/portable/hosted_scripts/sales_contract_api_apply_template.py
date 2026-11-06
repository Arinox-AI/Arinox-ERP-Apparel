# API arinox_sales_contract_apply_template: the terms and tolerance bands of the contract's template, for the form to fill in.
def main():
    d = json.loads(frappe.form_dict.get("doc") or "{}")
    if not d.get("contract_template"):
        return
    tpl = frappe.get_doc("Sales Contract Template", d.get("contract_template"))
    fields = ("incoterm", "named_place", "shipment_mode", "port_of_loading", "port_of_discharge", "days_ex_factory_to_etd", "transit_days", "late_shipment_terms",
              "quantity_claim_days", "quality_claim_days", "aql_level", "inspection_terms", "packing_instructions", "shipping_marks", "payment_terms_template",
              "terms_and_conditions", "arbitration", "country_of_origin", "freight_by", "insurance_by", "delay_days_allowed", "objection_days", "discrepancy_days",
              "payment_basis", "payment_days", "documents_list")
    out = {}
    for f in fields:
        out[f] = tpl.get(f)
    out["tolerance_bands"] = [{"from_qty": b.from_qty, "to_qty": b.to_qty, "tolerance_pct": b.tolerance_pct} for b in tpl.tolerance_bands]
    if tpl.get("terms_and_conditions"):
        out["terms"] = frappe.db.get_value("Terms and Conditions", tpl.terms_and_conditions, "terms")
    frappe.flags.arinox_result = {"arinox_doc": out}


main()
