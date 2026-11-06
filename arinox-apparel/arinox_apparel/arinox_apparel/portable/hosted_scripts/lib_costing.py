# shared helpers: cost heads, the costing parameter that applies, and the charge rows built from it (cost_sheet.py)
def get_cost_heads():
    return frappe.get_all("Cost Head", filters={"enabled": 1}, fields=["name", "head_group", "calc_type", "material_scope", "sequence", "is_mandatory"], order_by="sequence asc")


def find_costing_parameter(customer, product_type, on_date, currency):
    """Most specific enabled parameter valid on the date: customer+type > customer > type > generic."""
    on = frappe.utils.getdate(on_date or frappe.utils.nowdate())
    filters = {"enabled": 1, "effective_from": ["<=", on]}
    if currency:
        filters["currency"] = currency
    rows = frappe.get_all("Costing Parameter", filters=filters, fields=["name", "customer", "product_type", "effective_from", "effective_to"], order_by="effective_from desc")
    best = None
    best_score = -1
    for r in rows:
        if r.effective_to and frappe.utils.getdate(r.effective_to) < on:
            continue
        if r.customer and r.customer != customer:
            continue
        if r.product_type and r.product_type != product_type:
            continue
        score = (2 if r.customer else 0) + (1 if r.product_type else 0)
        if score > best_score:
            best = r.name
            best_score = score
    return best


def charge_rows(param):
    """One charge row per enabled non-material cost head, with the parameter's rates."""
    rates = {}
    if param:
        for r in frappe.get_all("Costing Parameter Rate", filters={"parent": param, "parenttype": "Costing Parameter"}, fields=["cost_head", "rate", "not_applicable"]):
            rates[r.cost_head] = r
    out = []
    for head in get_cost_heads():
        if head.calc_type == "From Materials":
            continue
        r = rates.get(head.name)
        out.append({"cost_head": head.name, "calc_type": head.calc_type, "sequence": head.sequence, "head_group": head.head_group,
                    "rate": frappe.utils.flt(r.rate) if r else 0, "not_applicable": r.not_applicable if r else 0, "source": "Parameter" if r else "Manual"})
    return out
