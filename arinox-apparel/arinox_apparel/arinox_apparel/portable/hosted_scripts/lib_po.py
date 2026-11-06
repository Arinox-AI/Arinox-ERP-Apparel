# shared helpers of the Purchase Order hooks (overrides/purchase_order.py): the requisition row behind a PO row, approval-hold messages, cost warnings. Needs lib_samples.py, lib_mat.py.
COPY_FIELDS = ("apparel_requisition_type", "apparel_requisition", "apparel_requisition_item", "apparel_style_no", "apparel_colour", "apparel_hold_reason")


def my_roles():
    return (frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role"))


def is_manager():
    return bool([r for r in my_roles() if r in MANAGER_ROLES])


def requisition_row(poi):
    """The FR / TR row behind a PO row (or None)."""
    if not poi.get("apparel_requisition"):
        return None
    dt = "Fabric Requisition Item" if poi.apparel_requisition_type == "FR" else "Trim Requisition Item"
    wording = "fabric_description" if poi.apparel_requisition_type == "FR" else "description"
    return frappe.db.get_value(dt, {"parent": poi.apparel_requisition, "material_request_item": poi.get("material_request_item")}, ["sales_order", "style_item", "colour", wording], as_dict=True)


def hold_blockers(doc):
    """Messages for rows whose lab dip (FR) or trim approval (TR) is still missing, re-checked now."""
    out = []
    for poi in doc.items:
        if not poi.get("apparel_hold_reason"):
            continue
        r = requisition_row(poi)
        if not r:
            continue
        if poi.apparel_requisition_type == "FR":
            stype = "Lab Dip"
            colour = r.colour
        else:
            stype = "Bulk Trim"
            colour = None
        ap = approval_info(r.sales_order, r.style_item, stype, colour, frappe.db.get_value("Sales Order", r.sales_order, "customer"))
        if not ap[1]:
            out.append("Row %s (%s): %s is %s." % (poi.idx, poi.item_code, stype, ap[0]))
    return out


def cost_warnings(doc):
    """PO rate against the Cost Sheet material rate (the line is found through the requisition row; yard/metre and the costing currency are converted)."""
    flt = frappe.utils.flt
    limit = flt(frappe.db.get_single_value("Apparel Settings", "cost_overrun_warn_pct") or 5)
    out = []
    for poi in doc.items:
        r = requisition_row(poi)
        if not r or not flt(poi.rate):
            continue
        cs = cost_sheet_for(r.sales_order, r.style_item)
        if not cs:
            continue
        names = [(poi.item_name or "").strip().lower(), (r.get("fabric_description") or r.get("description") or "").strip().lower()]
        for cm in cs.materials:
            if not (cm.item and cm.item == poi.item_code) and (cm.description or "").strip().lower() not in names:
                continue
            cost_rate = flt(cm.rate)
            if not cost_rate:
                break
            # bring the costed rate to the PO's currency and unit: the costing may be in RMB per yard and the PO in USD per metre
            if (cm.price_currency or cs.currency) != doc.currency:
                if doc.currency == cs.currency and flt(cm.exchange_rate):
                    cost_rate = cost_rate * flt(cm.exchange_rate)
                else:
                    break
            cost_unit = cm.rate_uom or cm.uom
            if cost_unit != poi.uom:
                if cost_unit == "Yard" and poi.uom == "Meter":
                    cost_rate = cost_rate / 0.9144
                elif cost_unit == "Meter" and poi.uom == "Yard":
                    cost_rate = cost_rate * 0.9144
                else:
                    break
            if flt(poi.rate) > cost_rate * (1 + limit / 100):
                out.append("Row %s: rate %s is more than %s%% above the costed %s." % (poi.idx, poi.rate, limit, flt(cost_rate, 4)))
            break
    return out


def stamp_po(doc):
    """Booked / PI / ETD milestones for every style x colour on the order."""
    seen = []
    for poi in doc.items:
        r = requisition_row(poi)
        if not r:
            continue
        k = [r.sales_order, r.style_item, r.colour, poi.apparel_requisition_type]
        if k in seen:
            continue
        seen.append(k)
        so = k[0]
        style = k[1]
        colour = k[2]
        if k[3] == "FR":
            stamp_safe(so, style, colour, "FABRIC_BOOKED", frappe.utils.nowdate(), "Purchase Order", doc.name, False, False)
            if doc.get("apparel_mill_ready_date"):
                stamp_safe(so, style, colour, "BULK_FABRIC_READY_MILL", doc.apparel_mill_ready_date, "Purchase Order", doc.name, False, False)
            if doc.get("apparel_etd_actual"):
                stamp_safe(so, style, colour, "FABRIC_ETD", doc.apparel_etd_actual, "Purchase Order", doc.name, False, False)
            elif doc.get("apparel_etd_revised") or doc.get("apparel_etd_planned"):
                stamp_safe(so, style, colour, "FABRIC_ETD", doc.get("apparel_etd_revised") or doc.apparel_etd_planned, "Purchase Order", doc.name, False, True)
        elif doc.get("apparel_pi_date"):
            stamp_safe(so, style, colour, "TRIM_PI", doc.apparel_pi_date, "Purchase Order", doc.name, False, False)
