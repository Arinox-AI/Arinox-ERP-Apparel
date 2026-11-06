# shared helpers of the Fabric and Trim Requisition: the garment quantity of an order colour, default terms, trim category rules, and the line builders that read
# the Tech Pack and Sales Order. Needs lib_samples.py, lib_allocation.py, lib_mat.py.
def default_terms():
    return ("<ol><li>Delivery: as per the schedule above.</li><li>Partial shipments: not allowed.</li><li>Quality: as per the buyer's quality standards.</li>"
            "<li>Quantity: as per our internal buying standards. Over and above the allowance, uncut fabric will be returned to the supplier.</li>"
            "<li>Quantity is in metres.</li><li>Bulk shrinkage should be as per the approved fabric data sheet.</li>"
            "<li>Cuttable width and GSM must match the approved fabric data sheet.</li></ol>")


def uniq(items):
    out = []
    for i in items:
        if i not in out:
            out.append(i)
    return out


def order_colour_qty(sales_order, style_item, colour):
    cl = colour_level(get_order_lines(sales_order))
    row = cl.get((style_item, (colour or "").strip().upper()))
    return frappe.utils.cint(row["qty"]) if row else 0


def fr_lines_for_sales_order(sales_order, customer, company):
    """FR line dicts for one Sales Order from the Tech Pack materials (FR types only)."""
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    so = frappe.db.get_value("Sales Order", sales_order, ["docstatus", "customer", "company"], as_dict=True)
    if not so or so.docstatus != 1 or so.customer != customer or so.company != company:
        frappe.throw("Sales Order %s must be submitted and belong to this buyer and company." % sales_order)
    fr_types = fr_material_types()
    out = []
    cl = colour_level(get_order_lines(sales_order))
    for key in cl:
        style = key[0]
        o = cl[key]
        tp = tech_pack_for(style)
        if not tp:
            frappe.msgprint("Style %s has no submitted Tech Pack; no fabric lines were made for it." % style)
            continue
        cs = cost_sheet_for(sales_order, style)
        all_colours = [c.colour for c in tp.colours]
        for m in tp.materials:
            if m.material_type not in fr_types or not colour_matches(m.colour, o["colour"], all_colours):
                continue
            cons = flt(m.consumption)
            uom = m.uom or "Meter"
            source = "Tech Pack"
            costed = None
            if cs:
                for cm in cs.materials:
                    if cm.material_type == m.material_type and (cm.is_selected or cm.is_selected is None) and (
                            (cm.item and cm.item == m.item) or (cm.description or "").strip().lower() == (m.description or "").strip().lower()):
                        costed = flt(cm.consumption)
                        if not cons:
                            cons = costed
                            uom = cm.uom or uom
                            source = "Cost Sheet"
                        break
            width = parse_width_cm(m.width) or 0
            role = {"Lining": "Lining", "Contrast Fabric": "Contrast"}.get(m.material_type, "Shell")
            gsm = parse_width_cm(m.gsm) if m.gsm else 0
            out.append({"sales_order": sales_order, "style_item": style, "style_no": tp.style_no, "style_name": tp.style_name, "colour": o["colour"], "material_role": role,
                        "tech_pack_material": m.name, "fabric_item": m.item, "fabric_description": m.description, "fabric_colour": m.colour or o["colour"],
                        "supplier": m.nominated_supplier, "nominated_by_buyer": 1 if m.nominated_supplier else 0, "cuttable_width_cm": width, "gsm": gsm,
                        "garment_qty": cint(o["qty"]), "consumption": cons, "consumption_uom": uom, "consumption_source": source, "costed_consumption": costed})
    return out


def material_type_for(category):
    c = (category or "").lower()
    if "label" in c:
        return "Label"
    if "packaging" in c:
        return "Packaging"
    return "Trim"


def guess_category(material_type, description):
    """Trim Category for a Tech Pack material row, from its type and words in the description."""
    d = (description or "").lower()
    for words, cat in ((("size label", "size tab", "size tag"), "Size Label"), (("care", "wash care"), "Care Label"), (("thread",), "Thread"),
                       (("fusing", "interlining", "keo"), "Fusing / Interlining"), (("security",), "Security Tag"), (("hang tag", "hangtag", "price ticket"), "Hang Tag"),
                       (("button",), "Button"), (("zip", "hook", "fastener", "velcro"), "Zipper / Hooks / Fasteners"), (("elastic", "tape", "drawcord", "cord"), "Elastic / Tape"),
                       (("label",), "Woven Label"), (("carton", "poly", "bag", "tissue", "silica", "sticker", "hanger"), "Packaging")):
        if [w for w in words if w in d]:
            return cat
    return "Packaging" if material_type == "Packaging" else "Others"


def tr_lines_for_sales_order(sales_order, customer, company):
    """TR line dicts for one Sales Order from the Tech Pack materials that are not fabric."""
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    so = frappe.db.get_value("Sales Order", sales_order, ["docstatus", "customer", "company"], as_dict=True)
    if not so or so.docstatus != 1 or so.customer != customer or so.company != company:
        frappe.throw("Sales Order %s must be submitted and belong to this buyer and company." % sales_order)
    fr_types = fr_material_types()
    by_colour = colour_level(get_order_lines(sales_order))
    size_qty = {}
    for it in frappe.get_all("Sales Order Item", filters={"parent": sales_order}, fields=["item_code", "qty", "apparel_colour", "apparel_size"]):
        k = (style_of(it.item_code), (it.apparel_size or "").strip())
        size_qty[k] = size_qty.get(k, 0) + cint(it.qty)
    styles = {}
    names = []
    for key in by_colour:
        sk = "s|" + key[0]       # a style code may start with an underscore, which the sandbox refuses as a key
        if sk not in styles:
            styles[sk] = []
            names.append(key[0])
        styles[sk].append(by_colour[key])
    out = []
    for style in names:
        colours = styles["s|" + style]
        tp = tech_pack_for(style)
        if not tp:
            frappe.msgprint("Style %s has no submitted Tech Pack; no trim lines were made for it." % style)
            continue
        cs = cost_sheet_for(sales_order, style)
        pcs = cint(cs.pcs_per_carton) if cs else 0
        total = sum([cint(c["qty"]) for c in colours])
        all_colours = [c.colour for c in tp.colours]
        for m in tp.materials:
            if m.material_type in fr_types:
                continue
            cat = guess_category(m.material_type, m.description)
            base = {"sales_order": sales_order, "style_item": style, "style_no": tp.style_no, "trim_category": cat, "trim_item": m.item, "buyer_item_code": m.buyer_item_code,
                    "description": m.description, "supplier": m.nominated_supplier, "nominated_by_buyer": 1 if m.nominated_supplier else 0,
                    "customer_provided": 1 if m.buyer_supplied else 0}
            is_length = uom_kind(m.uom) in ("m", "yd")
            cons = flt(m.consumption) or 1
            dtm = "dtm" in (m.description or "").lower() or (m.colour or "").strip().upper() == "DTM"
            if cat == "Size Label":
                for k in sorted(size_qty):
                    if k[0] == style and k[1]:
                        row = dict(base)
                        row.update({"size": k[1], "calc_basis": "Per Size", "garment_qty": size_qty[k], "qty_per_garment": cons if not is_length else 1})
                        out.append(row)
            elif cat == "Packaging" and "carton" in (m.description or "").lower():
                if not pcs:
                    frappe.msgprint("Style %s: set the pieces per carton on the Cost Sheet to get the carton line." % style)
                    continue
                row = dict(base)
                row.update({"calc_basis": "Per Carton", "garment_qty": total, "qty_per_garment": cons, "pcs_per_carton": pcs})
                out.append(row)
            elif dtm or ((m.colour or "").strip() and colour_matches(m.colour, "", all_colours) is False):
                for c in colours:
                    if not dtm and (m.colour or "").strip().upper() != (c["colour"] or "").strip().upper():
                        continue
                    row = dict(base)
                    row.update({"colour": c["colour"], "trim_colour": c["colour"], "garment_qty": cint(c["qty"])})
                    if is_length:
                        row.update({"calc_basis": "By Length", "consumption": cons, "consumption_uom": m.uom or "Meter"})
                    else:
                        row.update({"calc_basis": "Per Garment", "qty_per_garment": cons})
                    out.append(row)
            elif is_length:
                row = dict(base)
                row.update({"calc_basis": "By Length", "garment_qty": total, "consumption": cons, "consumption_uom": m.uom})
                out.append(row)
            else:
                row = dict(base)
                row.update({"calc_basis": "Per Garment", "garment_qty": total, "qty_per_garment": cons})
                out.append(row)
    return out
