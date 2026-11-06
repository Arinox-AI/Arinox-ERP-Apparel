# shared helpers: the sample-approval rules (defaults, Apparel Settings rows, Sample Requirement overrides), the split-PO exemption,
# the style dates a due date is counted from, and the scope of the samples that apply to an order (sample_approval.py)
APPROVED = ("Approved", "Approved with Comments")
GATE_OK = ("Approved", "Approved with Comments", "Not Required")
MANAGER_ROLES = ("Apparel Merchandising Manager", "System Manager")
# type: (gate, per_colour, due_basis, days_offset); used until Apparel Settings has its own rule rows. Same values as the seeded table.
DEFAULT_RULES = {
    "Proto": ("No", 0, "PCD", 90), "Fit": ("Required", 0, "PCD", 45), "Size Set": ("If Raised", 0, "PCD", 30), "Lab Dip": ("Required", 1, "PCD", 60),
    "Strike Off": ("If Raised", 1, "PCD", 60), "Desk Loom": ("If Raised", 1, "PCD", 60), "Bulk Fabric": ("Required", 1, "PCD", 25),
    "Bulk Trim": ("Required", 0, "PCD", 25), "PP": ("Required", 0, "PCD", 14), "Garment Test (GPT)": ("If Raised", 0, "PCD", 14),
    "TOP": ("No", 1, "Ex-Factory", 10), "Salesman": ("No", 0, "PCD", 30), "Photo Sample": ("No", 0, "PCD", 30),
    "Customer Sample": ("No", 0, "After Fit Approval", 10), "Fabric Test (FPT)": ("If Raised", 1, "PCD", 21),
}


def norm(colour):
    return (colour or "").strip().upper()


def make_rule(gate="No", per_colour=0, due_basis="PCD", days_before=0, qty=0, sample_size=None, split_po_exempt=0, chargeback_amount=0):
    return {"gate": gate or "No", "per_colour": frappe.utils.cint(per_colour), "due_basis": due_basis or "PCD", "days_before": frappe.utils.cint(days_before),
            "qty": frappe.utils.cint(qty), "sample_size": sample_size, "split_po_exempt": frappe.utils.cint(split_po_exempt),
            "chargeback_amount": frappe.utils.flt(chargeback_amount)}


def get_rules(customer, sales_order, style_item):
    """sample type -> rule. Defaults, then Apparel Settings rows, then Sample Requirement overrides. Overrides are scoped to a customer,
    an order and/or a style; the most specific one wins field by field. A blank field in an override keeps the value below it."""
    rules = {}
    for t in DEFAULT_RULES:
        d = DEFAULT_RULES[t]
        rules[t] = make_rule(d[0], d[1], d[2], d[3])
    for r in frappe.get_all("Apparel Sample Rule", filters={"parent": "Apparel Settings", "parenttype": "Apparel Settings"}, order_by="idx asc",
                            fields=["sample_type", "gate", "per_colour", "due_basis", "days_before", "qty", "sample_size", "split_po_exempt", "chargeback_amount"]):
        rules[r.sample_type] = make_rule(r.gate, r.per_colour, r.due_basis, r.days_before, r.qty, r.sample_size, r.split_po_exempt, r.chargeback_amount)
    if sales_order and not customer:
        customer = frappe.db.get_value("Sales Order", sales_order, "customer")
    scored = []
    for q in frappe.get_all("Sample Requirement", filters={"enabled": 1}, fields=["*"]):
        score = 0
        for field, value, weight in (("sales_order", sales_order, 4), ("style_item", style_item, 2), ("customer", customer, 1)):
            if q.get(field):
                if q.get(field) != value:
                    score = None
                    break
                score += weight
        if score:
            scored.append([score, q])
    for entry in sorted(scored, key=lambda x: x[0]):
        q = entry[1]
        rule = rules.get(q.sample_type)
        if not rule:
            rule = make_rule()
            rules[q.sample_type] = rule
        if q.gate:
            rule["gate"] = q.gate
        if q.per_colour:
            rule["per_colour"] = 1 if q.per_colour == "Yes" else 0
        if q.due_basis:   # basis and offset travel together
            rule["due_basis"] = q.due_basis
            rule["days_before"] = frappe.utils.cint(q.days_before)
        if frappe.utils.cint(q.qty):
            rule["qty"] = frappe.utils.cint(q.qty)
        if q.sample_size:
            rule["sample_size"] = q.sample_size
        if frappe.utils.cint(q.split_po_exempt):
            rule["split_po_exempt"] = 1
        if frappe.utils.flt(q.chargeback_amount):
            rule["chargeback_amount"] = frappe.utils.flt(q.chargeback_amount)
    return rules


def is_split_po(sales_order):
    """An order that ships to more than one destination."""
    dests = []
    for d in frappe.get_all("Sales Order Item", filters={"parent": sales_order}, pluck="apparel_ship_to"):
        if (d or "").strip() and (d or "").strip().upper() not in dests:
            dests.append((d or "").strip().upper())
    return len(dests) > 1


def effective_gate(rule, sales_order):
    """The gate after the split-PO exemption."""
    if rule["gate"] != "No" and rule["split_po_exempt"] and sales_order and is_split_po(sales_order):
        return "No"
    return rule["gate"]


def scope_filters(sales_order, style_item):
    """Samples that apply to this order: this Sales Order's, or ones raised before any order existed."""
    return {"style_item": style_item, "sales_order": ["in", [sales_order, "", None]]}


def get_style_dates(sales_order, style_item, colour):
    """[PCD, ex-factory, in-warehouse] for a style x colour. PCD from the Factory Allocation, then the contract line; the others from the Sales Order lines."""
    pcd = None
    ex_factory = None
    in_warehouse = None
    if not sales_order:
        return [pcd, ex_factory, in_warehouse]
    fa = frappe.db.get_value("Factory Allocation", {"sales_order": sales_order}, "name")
    if fa:
        for r in frappe.get_all("Factory Allocation Line", filters={"parent": fa, "style_item": style_item}, fields=["colour", "pcd"], order_by="pcd"):
            if r.pcd and (not colour or norm(r.colour) == norm(colour)):
                pcd = r.pcd
                break
    contract = frappe.db.get_value("Sales Order", sales_order, "apparel_sales_contract")
    if not pcd and contract:
        for r in frappe.get_all("Sales Contract Item", filters={"parent": contract, "style_item": style_item}, fields=["colour", "pcd"], order_by="pcd"):
            if r.pcd and (not colour or norm(r.colour) == norm(colour)):
                pcd = r.pcd
                break
    for it in frappe.get_all("Sales Order Item", filters={"parent": sales_order}, order_by="delivery_date",
                             fields=["item_code", "apparel_colour", "delivery_date", "apparel_in_warehouse_date"]):
        if frappe.db.get_value("Item", it.item_code, "variant_of") == style_item or it.item_code == style_item:
            if colour and norm(it.apparel_colour) != norm(colour):
                continue
            ex_factory = ex_factory or it.delivery_date
            in_warehouse = in_warehouse or it.apparel_in_warehouse_date
            if ex_factory and in_warehouse:
                break
    return [pcd, ex_factory, in_warehouse]


def fit_approved_on(sales_order, style_item):
    """Latest approval date of the Fit samples of this style that apply to the order."""
    f = scope_filters(sales_order, style_item)
    f["sample_type"] = "Fit"
    f["status"] = ["in", list(APPROVED)]
    rows = [r for r in frappe.get_all("Sample Approval", filters=f, pluck="approved_on") if r]
    return max(rows) if rows else None
