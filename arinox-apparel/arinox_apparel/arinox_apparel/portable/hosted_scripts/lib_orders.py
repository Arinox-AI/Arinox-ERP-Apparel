# shared helpers: the order matrix and style dates (production_card.order_matrix, sample_approval.get_style_dates)
def order_matrix(sales_order, style_item):
    """({(colour, size): {order_qty, tolerance_pct}}, earliest ex-factory date, [buyer POs]) for one style on an order."""
    cells = {}
    ex_factory = None
    pos = []
    for it in frappe.get_all("Sales Order Item", {"parent": sales_order},
                             ["item_code", "qty", "apparel_colour", "apparel_size", "apparel_buyer_po", "apparel_qty_tolerance_pct", "delivery_date"]):
        style = frappe.db.get_value("Item", it.item_code, "variant_of") or it.item_code
        if style != style_item:
            continue
        key = ((it.apparel_colour or "").strip(), (it.apparel_size or "").strip())
        if key not in cells:
            cells[key] = {"order_qty": 0, "tolerance_pct": 0}
        cells[key]["order_qty"] = cells[key]["order_qty"] + int(it.qty or 0)
        cells[key]["tolerance_pct"] = max(frappe.utils.flt(cells[key]["tolerance_pct"]), frappe.utils.flt(it.apparel_qty_tolerance_pct))
        if it.delivery_date and (not ex_factory or frappe.utils.getdate(it.delivery_date) < frappe.utils.getdate(ex_factory)):
            ex_factory = frappe.utils.getdate(it.delivery_date)
        if it.apparel_buyer_po and it.apparel_buyer_po not in pos:
            pos.append(it.apparel_buyer_po)
    return cells, ex_factory, pos


def get_pcd(sales_order, style_item):
    """Planned cut date from the Factory Allocation, then the contract line."""
    if not sales_order:
        return None
    fa = frappe.db.get_value("Factory Allocation", {"sales_order": sales_order}, "name")
    if fa:
        for r in frappe.get_all("Factory Allocation Line", {"parent": fa, "style_item": style_item}, ["pcd"], order_by="pcd"):
            if r.pcd:
                return r.pcd
    contract = frappe.db.get_value("Sales Order", sales_order, "apparel_sales_contract")
    if contract:
        for r in frappe.get_all("Sales Contract Item", {"parent": contract, "style_item": style_item}, ["pcd"], order_by="pcd"):
            if r.pcd:
                return r.pcd
    return None


def setting(field, default):
    v = frappe.db.get_single_value("Apparel Settings", field)
    if v is None or v == "":
        return default
    return v
