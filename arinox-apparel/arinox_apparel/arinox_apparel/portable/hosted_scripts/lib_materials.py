# shared helpers from materials/status.py: the material gate that holds bulk production, and trim readiness (the rest of status.py is not ported yet)
def material_gate(sales_order, style_item, colour):
    """[blockers, warnings] for bulk production of a style x colour: every requisition line must have its accepted quantity in.
    Trims that only matter later (finishing, packing) never hold cutting."""
    flt = frappe.utils.flt
    fab = frappe.db.get_single_value("Apparel Settings", "material_gate_fabric") or "Block"
    trim = frappe.db.get_single_value("Apparel Settings", "material_gate_trims") or "Warn"
    min_pct = flt(frappe.db.get_single_value("Apparel Settings", "material_gate_min_pct") or 100)
    blockers = []
    warnings = []
    if fab != "Off":
        fab_lines = frappe.db.sql("""select c.parent, c.fabric_item, c.net_qty, c.accepted_qty from `tabFabric Requisition Item` c join `tabFabric Requisition` p on p.name = c.parent
            where p.docstatus = 1 and p.status not in ('Superseded', 'Cancelled') and c.sales_order = %s and c.style_item = %s
            and upper(c.colour) = upper(%s) and c.net_qty > 0""", (sales_order, style_item, colour or ""), as_dict=True)
        if not fab_lines:
            # nothing to hold the gate on: say so, so an order never starts bulk with no fabric ordered by oversight (free-issue fabric is the one good reason)
            warnings.append("Fabric: no approved Fabric Requisition covers %s yet. Fine only if the buyer supplies the fabric." % (colour or "this colour"))
        for r in fab_lines:
            need = flt(r.net_qty) * min_pct / 100
            if flt(r.accepted_qty) + 0.0005 < need:
                msg = "Fabric %s: %s m of %s m accepted (%s)." % (r.fabric_item, flt(r.accepted_qty, 1), flt(r.net_qty, 1), r.parent)
                if fab == "Block":
                    blockers.append(msg)
                else:
                    warnings.append(msg)
    if trim != "Off":
        for r in frappe.db.sql("""select c.parent, c.trim_item, c.net_qty, c.accepted_qty, c.trim_category from `tabTrim Requisition Item` c join `tabTrim Requisition` p on p.name = c.parent
            left join `tabTrim Category` k on k.name = c.trim_category
            where p.docstatus = 1 and p.status not in ('Superseded', 'Cancelled') and c.sales_order = %s and c.style_item = %s
            and (c.colour is null or c.colour = '' or upper(c.colour) = upper(%s)) and c.net_qty > 0 and coalesce(k.needed_for, 'Sewing') in ('Cutting', 'Sewing')""",
                               (sales_order, style_item, colour or ""), as_dict=True):
            need = flt(r.net_qty) * min_pct / 100
            if flt(r.accepted_qty) + 0.0005 < need:
                msg = "Trim %s: %s of %s accepted (%s)." % (r.trim_item, flt(r.accepted_qty, 1), flt(r.net_qty, 1), r.parent)
                if trim == "Block":
                    blockers.append(msg)
                else:
                    warnings.append(msg)
    return [blockers, warnings]


def trim_readiness(sales_order, style_item, needed_for):
    """Available / Partial / Not Available for the trims of one need (Sewing or Packing); None when there are none."""
    flt = frappe.utils.flt
    rows = frappe.db.sql("""select c.net_qty, c.received_qty, c.accepted_qty from `tabTrim Requisition Item` c join `tabTrim Requisition` p on p.name = c.parent
        left join `tabTrim Category` k on k.name = c.trim_category where p.docstatus = 1 and p.status not in ('Superseded', 'Cancelled')
        and c.sales_order = %s and c.style_item = %s and c.net_qty > 0 and coalesce(k.needed_for, 'Sewing') = %s""", (sales_order, style_item, needed_for), as_dict=True)
    if not rows:
        return None
    min_pct = flt(frappe.db.get_single_value("Apparel Settings", "material_gate_min_pct") or 100)
    if len([r for r in rows if flt(r.accepted_qty) + 0.0005 >= flt(r.net_qty) * min_pct / 100]) == len(rows):
        return "Available"
    if [r for r in rows if flt(r.received_qty) > 0 or flt(r.accepted_qty) > 0]:
        return "Partial"
    return "Not Available"
