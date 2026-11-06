# API arinox_sales_contract_make_sales_contract: Quotation -> Sales Contract (unsaved). One line per quoted style and tech-pack colour, with the size rows pre-filled
# from the tech pack, the line quantity split across the sizes (see lib_contract_sizes.py). The contract template's terms and bands are applied the way the Apply Template button does.
# A Quotation carries few of a contract's fields, so what it lacks is filled in this order, never over a value already set: the Quotation (contact, address,
# terms), the contract template, the customer's most recent earlier contract (terms, bands, brand, division, contact, merchant), then the Customer,
# Tech Pack and Cost Sheet (customer name, payment terms, season, division, in-warehouse date).
def main():
    # include: lib_contract_sizes.py
    cint = frappe.utils.cint
    flt = frappe.utils.flt
    q = frappe.get_doc("Quotation", frappe.form_dict.get("source_name"))
    q.check_permission("read")
    if q.docstatus != 1:
        frappe.throw("Submit the Quotation first.")
    if q.quotation_to != "Customer":
        frappe.throw("The Quotation must be addressed to a Customer.")

    template = (frappe.db.get_value("Sales Contract Template", {"customer": q.party_name, "is_default": 1, "enabled": 1}, "name")
                or frappe.db.get_value("Sales Contract Template", {"customer": q.party_name, "enabled": 1}, "name")
                or frappe.db.get_single_value("Apparel Settings", "default_contract_template"))
    fixed = []      # header fields set by the Quotation or the template: the earlier contract never replaces these
    sc = frappe.new_doc("Sales Contract")
    sc.update({"customer": q.party_name, "quotation": q.name, "price_negotiation": q.get("apparel_price_negotiation"), "opportunity": q.opportunity,
               "currency": q.currency, "company": q.company, "contract_template": template})
    if template:
        res = run_script("arinox_sales_contract_api_apply_template", doc=json.dumps({"contract_template": template})).get("arinox_result")
        terms = (res or {}).get("arinox_doc") or {}
        for f in terms:
            if f != "tolerance_bands":
                sc.set(f, terms[f])
                if terms[f]:
                    fixed.append(f)
        if terms.get("tolerance_bands"):
            fixed.append("tolerance_bands")
        sc.set("tolerance_bands", [])
        for b in terms.get("tolerance_bands") or []:
            sc.append("tolerance_bands", b)
    if q.incoterm:
        sc.incoterm = q.incoterm
        fixed.append("incoterm")
    if q.payment_terms_template:
        fixed = fixed + ["payment_terms_template", "payment_basis", "payment_days"]
        sc.payment_terms_template = q.payment_terms_template
        first = frappe.db.get_value("Payment Terms Template Detail", {"parent": q.payment_terms_template}, ["credit_days", "due_date_based_on"], as_dict=True)
        if first and not sc.payment_basis:
            sc.payment_days = cint(first.credit_days)
            sc.payment_basis = "Days after Invoice Date"

    # ---- what the Quotation does carry that the contract has a place for
    cust = frappe.db.get_value("Customer", q.party_name, ["customer_name", "payment_terms"], as_dict=True)
    if cust:
        sc.customer_name = cust.customer_name
    if q.get("customer_address"):
        sc.customer_address = q.customer_address
        fixed.append("customer_address")
    if q.get("contact_display"):
        sc.buyer_contact = q.contact_display
        fixed.append("buyer_contact")
    if q.get("tc_name"):
        sc.terms_and_conditions = q.tc_name
        sc.terms = q.get("terms")
        fixed = fixed + ["terms_and_conditions", "terms"]
    if q.owner:
        sc.merchant = frappe.db.get_value("User", q.owner, "full_name")      # the merchandiser is whoever raised the quotation
        fixed.append("merchant")
    if cust and cust.payment_terms and not sc.payment_terms_template:
        fixed = fixed + ["payment_terms_template", "payment_basis", "payment_days"]
        sc.payment_terms_template = cust.payment_terms
        first_term = frappe.db.get_value("Payment Terms Template Detail", {"parent": cust.payment_terms}, ["credit_days"], as_dict=True)
        if first_term and not sc.payment_basis:
            sc.payment_days = cint(first_term.credit_days)
            sc.payment_basis = "Days after Invoice Date"

    # ---- this customer's most recent earlier contract fills whatever is still blank (the same buyer repeats the same terms)
    earlier = frappe.get_all("Sales Contract", filters={"customer": q.party_name, "docstatus": ["<", 2]}, order_by="contract_date desc, creation desc", limit_page_length=1, pluck="name")
    if earlier:
        prev = frappe.get_doc("Sales Contract", earlier[0])
        for f in ("brand", "division", "buyer_contact", "merchant", "customer_address", "bank_account", "incoterm", "named_place", "shipment_mode", "country_of_origin",
                  "freight_by", "insurance_by", "port_of_loading", "port_of_discharge", "days_ex_factory_to_etd", "transit_days", "delay_days_allowed",
                  "late_shipment_terms", "quantity_claim_days", "quality_claim_days", "objection_days", "discrepancy_days", "aql_level", "inspection_terms",
                  "packing_instructions", "payment_basis", "payment_days", "payment_terms_template", "documents_list", "terms_and_conditions", "terms", "arbitration"):
            if f in fixed or not prev.get(f):
                continue
            current = sc.get(f)
            default = frappe.db.get_value("DocField", {"parent": "Sales Contract", "fieldname": f}, "default")
            if not current or (default not in (None, "") and str(current) == str(default)):      # blank, or still the form's own default
                sc.set(f, prev.get(f))
        if not sc.tolerance_bands and "tolerance_bands" not in fixed:
            for b in prev.tolerance_bands:
                sc.append("tolerance_bands", {"from_qty": b.from_qty, "to_qty": b.to_qty, "tolerance_pct": b.tolerance_pct})

    for qi in q.items:
        cs = frappe.get_doc("Cost Sheet", qi.apparel_cost_sheet) if qi.get("apparel_cost_sheet") else None
        style_item = qi.get("apparel_style_item") or (cs.style_item if cs else None) or qi.item_code
        tp = frappe.get_doc("Tech Pack", cs.tech_pack) if cs and cs.tech_pack else None
        colours = [c.colour for c in tp.colours] if tp and tp.colours else [None]
        if not sc.season:
            sc.season = (tp.season if tp else None) or (cs.season if cs else None)
        if tp and not sc.division:
            sc.division = tp.division
        # dates for the line: the buyer's own lead time for this style (contract date -> ex-factory, and -> PCD) from their most recent earlier
        # contract that has them, else the contract's production lead days. A date the merchandiser can change; ETD and in-warehouse follow below.
        ex_lead = None
        pcd_lead = None
        for r in frappe.get_all("Sales Contract Item", filters={"style_item": style_item, "parenttype": "Sales Contract", "ex_factory_date": ["is", "set"]},
                                fields=["parent", "ex_factory_date", "pcd"], order_by="creation desc", limit_page_length=20):
            pc = frappe.db.get_value("Sales Contract", r.parent, ["customer", "contract_date", "docstatus"], as_dict=True)
            if pc and pc.customer == q.party_name and pc.docstatus < 2 and pc.contract_date:
                ex_lead = frappe.utils.date_diff(r.ex_factory_date, pc.contract_date)
                if r.pcd:
                    pcd_lead = frappe.utils.date_diff(r.pcd, pc.contract_date)
                break
        if ex_lead is None and cint(sc.production_lead_days):
            ex_lead = cint(sc.production_lead_days)
        for colour in colours:
            line_qty = qi.qty if len(colours) == 1 else 0
            sc.append("items", {"style_item": style_item, "style_no": qi.get("apparel_style_no") or (cs.style_no if cs else qi.item_name), "colour": colour,
                                "qty": line_qty, "rate": qi.rate, "description": qi.description,
                                "cost_sheet": cs.name if cs else None, "tech_pack": tp.name if tp else None,
                                "in_warehouse_date": cs.in_warehouse_date if cs else None,
                                "ex_factory_date": frappe.utils.add_days(sc.contract_date, ex_lead) if ex_lead is not None and ex_lead > 0 else None,
                                "pcd": frappe.utils.add_days(sc.contract_date, pcd_lead) if pcd_lead is not None and pcd_lead > 0 else None})
            names = [z.size for z in tp.sizes] if tp else []
            ratios = {}
            for z in (tp.sizes if tp else []):
                ratios[z.size] = z.ratio
            split = size_split(line_qty, names, ratios, q.party_name, style_item, colour)[0] if names else {}
            for size in names:
                sc.append("sizes", {"style_item": style_item, "colour": colour, "size": size, "qty": split.get(size, 0)})
    # the figures the save script would work out, so the form opens with prices, tolerances and totals instead of zeros
    total_qty = 0
    total_amount = 0
    for it in sc.items:
        it.amount = flt(cint(it.qty) * flt(it.rate), 2)
        it.tolerance_pct = 0
        for b in sorted(sc.tolerance_bands, key=lambda b: cint(b.from_qty)):
            if cint(it.qty) >= cint(b.from_qty) and (not cint(b.to_qty) or cint(it.qty) <= cint(b.to_qty)):
                it.tolerance_pct = flt(b.tolerance_pct)
                break
        if it.ex_factory_date and not it.etd:
            it.etd = frappe.utils.add_days(it.ex_factory_date, cint(sc.days_ex_factory_to_etd))
        if it.etd and not it.in_warehouse_date:
            it.in_warehouse_date = frappe.utils.add_days(it.etd, cint(sc.transit_days))
        total_qty = total_qty + cint(it.qty)
        total_amount = total_amount + flt(it.amount)
    sc.total_qty = total_qty
    sc.total_amount = flt(total_amount, 2)
    sc.sku_count = len(sc.items)
    frappe.flags.arinox_result = sc.as_dict()


main()
