# shared helpers from materials/purchasing.py: supplier terms (quantity bands, late-delivery penalty) and the roll-up of purchase, receipt and inspection
# quantities back to the requisitions. Needs lib_mat.py. Row keys and the status rule of both requisitions live here too.
def fr_row_key(r):
    return "|".join([r.sales_order or "", r.style_item or "", (r.colour or "").strip().upper(), r.material_role or "", r.fabric_item or ""])


def tr_row_key(r):
    return "|".join([r.sales_order or "", r.style_item or "", (r.colour or "").strip().upper(), (r.size or "").strip().upper(), r.trim_category or "",
                     r.trim_item or r.description or "", (r.trim_colour or "").strip().upper()])


def requisition_status(doc):
    """The status of a requisition from its docstatus and its lines."""
    flt = frappe.utils.flt
    if doc.docstatus == 0:
        return "Draft"
    if doc.docstatus == 2:
        return "Cancelled"
    if doc.status == "Superseded":
        return "Superseded"
    need = [r for r in doc.items if flt(r.net_qty) > 0]
    if not need or len([r for r in need if flt(r.received_qty) + 0.0005 >= flt(r.net_qty)]) == len(need):
        return "Received"
    if [r for r in need if flt(r.received_qty) > 0]:
        return "Partly Received"
    if len([r for r in need if flt(r.ordered_qty) + 0.0005 >= flt(r.net_qty)]) == len(need):
        return "Ordered"
    if [r for r in need if flt(r.ordered_qty) > 0]:
        return "Partly Ordered"
    return "Approved"


def pick_band(bands, qty):
    """The Purchase Qty Band row covering `qty` (to_qty 0 = no upper limit); None when no band applies."""
    flt = frappe.utils.flt
    for b in sorted(bands, key=lambda b: flt(b.from_qty)):
        if flt(b.from_qty) <= flt(qty) and (not flt(b.to_qty) or flt(qty) <= flt(b.to_qty)):
            return b
    return None


def qty_tolerance(terms, ordered_qty):
    if not terms:
        return 0.0
    b = pick_band(terms.qty_bands, ordered_qty)
    return frappe.utils.flt(b.tolerance_pct) if b else 0.0


def delay_penalty(terms, delay_days):
    """[penalty %, action] for a delay under `terms`. Days <= 0 or inside a 0% band return 0."""
    cint = frappe.utils.cint
    if not terms or cint(delay_days) <= 0:
        return [0.0, None]
    for b in sorted(terms.delay_bands, key=lambda b: cint(b.from_days)):
        if cint(b.from_days) <= cint(delay_days) and (not cint(b.to_days) or cint(delay_days) <= cint(b.to_days)):
            return [frappe.utils.flt(b.penalty_pct), b.action]
    return [0.0, None]


def terms_for(po_or_supplier_terms, supplier):
    """The terms doc: the explicit one, else the supplier's, else the default in Apparel Settings."""
    name = po_or_supplier_terms or (frappe.db.get_value("Supplier", supplier, "apparel_purchase_terms") if supplier else None) or frappe.db.get_single_value("Apparel Settings", "default_purchase_terms")
    return frappe.get_doc("Material Purchase Terms", name) if name else None


def key_totals(requisition_type, chain, key):
    """[ordered, received] in stock units for a line key across a revision chain, from the purchase orders that reference its Material Request rows."""
    rows = frappe.db.sql("select coalesce(sum(p.stock_qty), 0), coalesce(sum(p.received_qty * p.conversion_factor), 0) from `tabPurchase Order Item` p "
                         "join `tabPurchase Order` o on o.name = p.parent join `tabMaterial Request Item` m on m.name = p.material_request_item "
                         "where o.docstatus = 1 and m.apparel_requisition_type = %s and m.apparel_requisition in %s and m.apparel_requisition_item = %s",
                         (requisition_type, tuple(chain), key))
    return [frappe.utils.flt(rows[0][0]), frappe.utils.flt(rows[0][1])]


def inspection_totals(requisition_type, chain, key):
    """[accepted, rejected] in stock units for a line key, from the submitted inspections of the goods received for it."""
    if requisition_type == "FR":
        table = "Fabric Inspection"
        acc = "i.accepted_m"
        rej = "i.rejected_m"
    else:
        table = "Trim Inspection"
        acc = "i.accepted_qty"
        rej = "i.rejected_qty"
    rows = frappe.db.sql("select coalesce(sum(%s), 0), coalesce(sum(%s), 0) from `tab%s` i join `tabPurchase Receipt Item` r on r.name = i.purchase_receipt_item "
                         "join `tabPurchase Order Item` p on p.name = r.purchase_order_item join `tabMaterial Request Item` m on m.name = p.material_request_item "
                         "where i.docstatus = 1 and m.apparel_requisition_type = %%s and m.apparel_requisition in %%s and m.apparel_requisition_item = %%s" % (acc, rej, table),
                         (requisition_type, tuple(chain), key))
    return [frappe.utils.flt(rows[0][0]), frappe.utils.flt(rows[0][1])]


def refresh_requisition(requisition_type, name):
    """Recompute ordered and received quantities and the status of one requisition; returns the document (None when not approved)."""
    if requisition_type == "FR":
        dt = "Fabric Requisition"
        prev_field = "previous_fr"
        key_of = fr_row_key
    else:
        dt = "Trim Requisition"
        prev_field = "previous_tr"
        key_of = tr_row_key
    if not frappe.db.exists(dt, name):
        return None
    doc = frappe.get_doc(dt, name)
    if doc.docstatus != 1:
        return None
    chain = revision_chain(dt, prev_field, name)
    for r in doc.items:
        ot = key_totals(requisition_type, chain, key_of(r))
        it = inspection_totals(requisition_type, chain, key_of(r))
        r.db_set({"ordered_qty": ot[0], "received_qty": ot[1], "accepted_qty": it[0], "rejected_qty": it[1]}, update_modified=False)
        r.ordered_qty = ot[0]
        r.received_qty = ot[1]
        r.accepted_qty = it[0]
        r.rejected_qty = it[1]
    status = requisition_status(doc)
    doc.status = status
    doc.db_set("status", status, update_modified=False)
    return doc


def refresh_for_documents(doc):
    """Refresh every requisition referenced by the items of a PO, PR or inspection document; returns a list of [type, name]."""
    seen = []
    for it in doc.get("items") or []:
        t = it.get("apparel_requisition_type")
        n = it.get("apparel_requisition")
        if not (t and n) and it.get("material_request_item"):
            v = frappe.db.get_value("Material Request Item", it.material_request_item, ["apparel_requisition_type", "apparel_requisition"])
            if v:
                t = v[0]
                n = v[1]
        if t in ("FR", "TR") and n and [t, n] not in seen:
            seen.append([t, n])
            refresh_requisition(t, n)
    return seen
