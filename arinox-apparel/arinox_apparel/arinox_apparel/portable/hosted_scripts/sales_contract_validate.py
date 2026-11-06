# Sales Contract, Before Save (validate): template, bank account, revision, tolerance bands, lines, price lock, sizes, totals.
def run(doc):
    cint = frappe.utils.cint
    flt = frappe.utils.flt
    TERM_FIELDS = ("incoterm", "named_place", "shipment_mode", "port_of_loading", "port_of_discharge", "days_ex_factory_to_etd", "transit_days",
                   "late_shipment_terms", "quantity_claim_days", "quality_claim_days", "aql_level", "inspection_terms", "packing_instructions",
                   "shipping_marks", "payment_terms_template", "terms_and_conditions", "arbitration", "country_of_origin", "freight_by",
                   "insurance_by", "delay_days_allowed", "objection_days", "discrepancy_days", "payment_basis", "payment_days", "documents_list")

    def in_band(qty, b):
        return qty >= cint(b.from_qty) and (not cint(b.to_qty) or qty <= cint(b.to_qty))

    def tolerance_for(qty):
        for b in sorted(doc.tolerance_bands, key=lambda b: cint(b.from_qty)):
            if in_band(qty, b):
                return flt(b.tolerance_pct)
        return 0

    def tolerance_covers(qty):
        for b in doc.tolerance_bands:
            if in_band(qty, b):
                return True
        return False

    if not doc.company:
        doc.company = frappe.db.get_value("Company", {}, "name")
    # ---- template: fill the terms the contract has not set, once
    if doc.contract_template and not doc.tolerance_bands:
        tpl = frappe.get_doc("Sales Contract Template", doc.contract_template)
        for f in TERM_FIELDS:
            if not doc.get(f):
                doc.set(f, tpl.get(f))
        for b in tpl.tolerance_bands:
            doc.append("tolerance_bands", {"from_qty": b.from_qty, "to_qty": b.to_qty, "tolerance_pct": b.tolerance_pct})
        if doc.terms_and_conditions and not doc.terms:
            doc.terms = frappe.db.get_value("Terms and Conditions", doc.terms_and_conditions, "terms")
    if not doc.bank_account and doc.company:
        default_bank = frappe.db.get_value("Company", doc.company, "default_bank_account")
        if default_bank and frappe.db.exists("Bank Account", default_bank):      # a default that names a missing account would block the submit
            doc.bank_account = default_bank
    if doc.amended_from:
        prev = frappe.db.get_value("Sales Contract", doc.amended_from, "revision_no") or 0
        doc.revision_no = cint(prev) + 1
        doc.revision_date = doc.revision_date or frappe.utils.nowdate()
    elif not doc.revision_no:
        doc.revision_no = 0

    # ---- bands must not overlap
    bands = sorted(doc.tolerance_bands, key=lambda b: cint(b.from_qty))
    for b in bands:
        if cint(b.to_qty) and cint(b.to_qty) < cint(b.from_qty):
            frappe.throw("Tolerance band row %s: To Qty is below From Qty." % b.idx)
    for i in range(len(bands) - 1):
        if not cint(bands[i].to_qty) or cint(bands[i].to_qty) >= cint(bands[i + 1].from_qty):
            frappe.throw("Tolerance bands %s and %s overlap." % (bands[i].idx, bands[i + 1].idx))

    # ---- lines
    max_skus = cint(frappe.db.get_single_value("Apparel Settings", "max_skus_per_contract")) or 8
    keys = []
    for it in doc.items:
        # a line is style x colour x buyer PO: the real S14 contract has one line per PO for the same style and colour
        key = (it.style_item, (it.colour or "").strip().upper(), (it.buyer_po_code or "").strip().upper())
        if key in keys:
            frappe.throw("Row %s: %s / %s is already on this contract for PO %s. One line per style, colour and PO." % (it.idx, it.style_item, it.colour, it.buyer_po_code or "-"))
        keys.append(key)
        if not it.style_no:
            it.style_no = frappe.db.get_value("Item", it.style_item, "item_name")
        it.amount = flt(cint(it.qty) * flt(it.rate), 2)
        it.tolerance_pct = tolerance_for(cint(it.qty))
        if doc.tolerance_bands and not tolerance_covers(cint(it.qty)):
            frappe.msgprint("Row %s: quantity %s is above the highest tolerance band, so no tolerance applies. Add a band for it." % (it.idx, cint(it.qty)), indicator="orange")
        if it.ex_factory_date and not it.etd:
            it.etd = frappe.utils.add_days(it.ex_factory_date, cint(doc.days_ex_factory_to_etd))
        if it.etd and not it.in_warehouse_date:
            it.in_warehouse_date = frappe.utils.add_days(it.etd, cint(doc.transit_days))
        if it.ex_factory_date and it.etd and frappe.utils.getdate(it.etd) < frappe.utils.getdate(it.ex_factory_date):
            frappe.throw("Row %s: ETD is before the ex-factory date." % it.idx)
        if it.etd and it.in_warehouse_date and frappe.utils.getdate(it.in_warehouse_date) < frappe.utils.getdate(it.etd):
            frappe.throw("Row %s: in-warehouse date is before ETD." % it.idx)
    if len(keys) > max_skus:
        frappe.throw("This contract has %s SKUs. The maximum is %s; put the rest on a new contract." % (len(keys), max_skus), title="Too Many SKUs")
    doc.sku_count = len(keys)

    # ---- price lock: the price agreed on the quotation is the price on the contract
    if doc.quotation:
        q = frappe.db.get_value("Quotation", doc.quotation, ["docstatus", "party_name", "currency"], as_dict=True)
        if not q or q.docstatus != 1:
            frappe.throw("Quotation %s must be submitted before it can become a contract." % doc.quotation)
        if q.party_name != doc.customer:
            frappe.throw("Quotation %s is for %s, not %s." % (doc.quotation, q.party_name, doc.customer))
        if q.currency != doc.currency:
            frappe.throw("Quotation %s is in %s, not %s." % (doc.quotation, q.currency, doc.currency))
        quoted = {}
        for r in frappe.get_all("Quotation Item", filters={"parent": doc.quotation}, fields=["apparel_cost_sheet", "rate"]):
            if r.apparel_cost_sheet:
                quoted[r.apparel_cost_sheet] = flt(r.rate)
        for it in doc.items:
            if not it.cost_sheet:
                continue
            if it.cost_sheet not in quoted:
                frappe.throw("Row %s: Cost Sheet %s is not on Quotation %s." % (it.idx, it.cost_sheet, doc.quotation))
            if abs(flt(it.rate) - quoted[it.cost_sheet]) > 0.0001:
                frappe.throw("Row %s: rate %s differs from the quoted %s. A contract carries the locked price; amend the Quotation to change it." % (it.idx, flt(it.rate), quoted[it.cost_sheet]),
                             title="Price Lock")

    # ---- sizes: each belongs to one contract line (style x colour x PO), once per ship-to
    def line_index(style_item, colour, po):
        """Index of the line a size row belongs to; None = no such line, -1 = several lines and no PO to tell them apart."""
        cands = []
        n = 0
        for it in doc.items:
            if it.style_item == style_item and (it.colour or "").strip().upper() == (colour or "").strip().upper():
                if not po or (it.buyer_po_code or "").strip().upper() == po.strip().upper():
                    cands.append(n)
            n = n + 1
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]
        return -1

    seen = []
    for s in doc.sizes:
        i = line_index(s.style_item, s.colour, s.buyer_po_no)
        if i is None:
            frappe.throw("Size row %s: %s / %s (PO %s) is not a line on this contract." % (s.idx, s.style_item, s.colour, s.buyer_po_no or "-"))
        if i == -1:
            frappe.throw("Size row %s: %s / %s is on several lines (one per PO). Enter the buyer PO on the size row." % (s.idx, s.style_item, s.colour))
        k2 = (i, s.size.strip().upper(), (s.ship_to or "").strip().upper())
        if k2 in seen:
            frappe.throw("Size row %s: size %s is entered twice for %s / %s to the same ship-to and PO." % (s.idx, s.size, s.style_item, s.colour))
        seen.append(k2)
        if cint(s.qty) < 0:
            frappe.throw("Size row %s: quantity cannot be negative." % s.idx)

    # ---- totals
    total = 0
    amount = 0
    for it in doc.items:
        total = total + cint(it.qty)
        amount = amount + flt(it.amount)
    doc.total_qty = total
    doc.total_amount = flt(amount, 2)
    if doc.docstatus == 0:
        doc.status = "Draft"


run(doc)
