# shared helpers from materials/common.py: unit conversion, allowance rules, approvals lookup, stock claims, Material Request creation, roll-ups, T&A stamping.
# Needs lib_samples.py included first (rules). No regular expressions or math module in the sandbox, so widths are parsed by hand.
YARD_M = 0.9144
ALIASES = {"m": "m", "meter": "m", "metre": "m", "mtr": "m", "mtrs": "m", "meters": "m", "metres": "m", "yd": "yd", "yds": "yd", "yard": "yd", "yards": "yd",
           "kg": "kg", "kgs": "kg", "kilogram": "kg", "kilograms": "kg"}


def uom_kind(uom):
    return ALIASES.get((uom or "").strip().lower())


def to_metres(qty, uom, gsm, width_cm):
    """Quantity of fabric in `uom` to metres. kg needs GSM and cuttable width: m = kg*1000 / (gsm * width_m)."""
    flt = frappe.utils.flt
    kind = uom_kind(uom)
    if kind == "m":
        return flt(qty)
    if kind == "yd":
        return flt(qty) * YARD_M
    if kind == "kg":
        if not flt(gsm) or not flt(width_cm):
            frappe.throw("GSM and cuttable width are needed to convert kg to metres.")
        return flt(qty) * 1000 / (flt(gsm) * flt(width_cm) / 100)
    frappe.throw("Cannot convert UOM %s to metres. Use Meter, Yard or Kg for fabric." % uom)


def from_metres(metres, uom, gsm, width_cm):
    flt = frappe.utils.flt
    kind = uom_kind(uom)
    if kind == "m":
        return flt(metres)
    if kind == "yd":
        return flt(metres) / YARD_M
    if kind == "kg":
        if not flt(gsm) or not flt(width_cm):
            frappe.throw("GSM and cuttable width are needed to convert metres to kg.")
        return flt(metres) * (flt(gsm) * flt(width_cm) / 100) / 1000
    frappe.throw("Cannot convert metres to UOM %s." % uom)


def numbers_in(text):
    """[[number, end_index], ...] for every number in the text."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text[i].isdigit():
            j = i
            while j < n and (text[j].isdigit() or (text[j] == "." and j + 1 < n and text[j + 1].isdigit())):
                j = j + 1
            out.append([float(text[i:j]), j])
            i = j
        else:
            i = i + 1
    return out


def parse_width_cm(text):
    """'132CM', 'CW 152 cm', '57"', '56in' -> cm. None when no width is found."""
    if not text:
        return None
    t = str(text).strip().lower()
    nums = numbers_in(t)
    if not nums:
        return None
    for nm in nums:
        rest = t[nm[1]:].lstrip()
        if rest.startswith("cm"):
            return nm[0]
        if rest.startswith('"') or rest.startswith("inch") or (rest.startswith("in") and not rest[2:3].isalpha()):
            return round(nm[0] * 2.54, 1)
    return nums[0][0]


def cw_in(text):
    """The number after 'CW' in a fabric description, or None."""
    t = (text or "").lower()
    k = t.find("cw")
    while k >= 0:
        rest = t[k + 2:].lstrip()
        nums = numbers_in(rest[:12])
        if nums and rest[:1].isdigit():
            return nums[0][0]
        k = t.find("cw", k + 2)
    return None


def round_up_to_pack(qty, pack_size):
    flt = frappe.utils.flt
    qty = flt(qty)
    if flt(pack_size) > 0 and qty > 0:
        return frappe.utils.ceil(round(qty / flt(pack_size), 9)) * flt(pack_size)
    return qty


def fr_material_types():
    raw = frappe.db.get_single_value("Apparel Settings", "fr_material_types") or "Fabric\nLining\nContrast Fabric"
    return [t.strip() for t in raw.splitlines() if t.strip()]


def get_allowance(material_type, trim_category, customer, item_group):
    """Most specific enabled Material Allowance Rule: customer 4, trim category 2, material type 1, item group 1 -> {allowance_pct, pack_size, min_order_qty}."""
    best = None
    best_score = 0
    for r in frappe.get_all("Material Allowance Rule", filters={"enabled": 1}, fields=["*"]):
        score = 0
        for field, value, weight in (("customer", customer, 4), ("trim_category", trim_category, 2), ("material_type", material_type, 1), ("item_group", item_group, 1)):
            if r.get(field):
                if r.get(field) != value:
                    score = None
                    break
                score += weight
        if score and score > best_score:
            best = r
            best_score = score
    if not best:
        return {"allowance_pct": 0, "pack_size": 0, "min_order_qty": 0}
    return {"allowance_pct": frappe.utils.flt(best.allowance_pct), "pack_size": frappe.utils.flt(best.pack_size), "min_order_qty": frappe.utils.flt(best.min_order_qty)}


def tech_pack_for(style_item):
    name = frappe.db.get_value("Tech Pack", {"style_item": style_item, "docstatus": 1}, "name", order_by="creation desc")
    return frappe.get_doc("Tech Pack", name) if name else None


def style_of(item_code):
    return frappe.db.get_value("Item", item_code, "variant_of") or item_code


def cost_sheet_for(sales_order, style_item):
    for it in frappe.get_all("Sales Order Item", filters={"parent": sales_order}, fields=["item_code", "apparel_cost_sheet"]):
        if it.apparel_cost_sheet and style_of(it.item_code) == style_item:
            return frappe.get_doc("Cost Sheet", it.apparel_cost_sheet)
    return None


def colour_matches(material_colour, garment_colour, all_colours):
    """A Tech Pack material row with a colour belongs to that garment colour only; blank belongs to all."""
    mc = (material_colour or "").strip().upper()
    if not mc:
        return True
    if mc == (garment_colour or "").strip().upper():
        return True
    return mc not in [(c or "").strip().upper() for c in all_colours]


def approval_info(sales_order, style_item, sample_type, colour, customer):
    """[status text, ok] for one sample type of a style x colour on an order. ok = the gate would let it pass."""
    rule = get_rules(customer, sales_order, style_item).get(sample_type)
    gate = effective_gate(rule, sales_order) if rule else "No"
    f = scope_filters(sales_order, style_item)
    f["sample_type"] = sample_type
    rows = frappe.get_all("Sample Approval", filters=f, fields=["name", "status", "colour"])
    if rule and rule["per_colour"]:
        rows = [r for r in rows if not (r.colour or "").strip() or norm(r.colour) == norm(colour)]
    if not rows:
        return ["Not Required", True] if gate == "No" else ["Not Raised", gate != "Required"]
    bad = [r for r in rows if r.status not in GATE_OK]
    if bad:
        return [bad[0].status, False]
    return ["Approved", True]


def free_stock(item_code, warehouse, parent_dt, child_dt, exclude):
    """Actual stock minus the stock already claimed by other approved requisitions (not superseded, not cancelled)."""
    flt = frappe.utils.flt
    if not item_code or not warehouse:
        return 0.0
    actual = flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"))
    item_field = "fabric_item" if parent_dt == "Fabric Requisition" else "trim_item"
    claimed = frappe.db.sql("select coalesce(sum(c.stock_used), 0) from `tab%s` c join `tab%s` p on p.name = c.parent where c.%s = %%s and c.stock_warehouse = %%s "
                            "and p.docstatus = 1 and p.status != 'Superseded' and p.name != %%s" % (child_dt, parent_dt, item_field), (item_code, warehouse, exclude or ""))[0][0]
    return actual - flt(claimed)


def item_has_uom(item_code, uom):
    stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
    return uom == stock_uom or bool(frappe.db.exists("UOM Conversion Detail", {"parent": item_code, "uom": uom}))


def mr_line(item_code, qty_stock, order_uom, order_qty):
    """[qty, uom, conversion_factor] for a Material Request row: the order UOM when the item has it, else stock UOM."""
    flt = frappe.utils.flt
    stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
    if order_uom and order_uom != stock_uom and flt(order_qty) > 0 and item_has_uom(item_code, order_uom):
        cf = flt(frappe.db.get_value("UOM Conversion Detail", {"parent": item_code, "uom": order_uom}, "conversion_factor")) or 1
        return [flt(order_qty), order_uom, cf]
    return [flt(qty_stock), stock_uom, 1]


def company_warehouse(field, company):
    """The warehouse named in Apparel Settings `field`, or its equivalent in `company` (created when missing)."""
    wh = frappe.db.get_single_value("Apparel Settings", field)
    if not wh or not company:
        return wh
    wc = frappe.db.get_value("Warehouse", wh, ["company", "warehouse_name"])
    if wc[0] == company:
        return wh
    abbr = frappe.db.get_value("Company", company, "abbr")
    name = "%s - %s" % (wc[1], abbr)
    if not frappe.db.exists("Warehouse", name):
        frappe.get_doc({"doctype": "Warehouse", "warehouse_name": wc[1], "company": company}).insert(ignore_permissions=True)
    return name


def create_material_requests(doc, lines, requisition_type, kind):
    """Group `lines` by (supplier, customer-provided) and make one Material Request per group. Returns the names."""
    cint = frappe.utils.cint
    getdate = frappe.utils.getdate
    if not lines:
        return []
    warehouse = company_warehouse("inspection_warehouse_fabric" if kind == "Fabric" else "inspection_warehouse_trim", doc.company)
    groups = {}
    order = []
    for ln in lines:
        k = "%s|%s" % (ln.get("supplier") or "", cint(ln.get("customer_provided")))
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(ln)
    names = []
    for k in order:
        rows = groups[k]
        supplier = rows[0].get("supplier") or ""
        provided = cint(rows[0].get("customer_provided"))
        mr = frappe.new_doc("Material Request")
        mr.material_request_type = "Customer Provided" if provided else "Purchase"
        mr.company = doc.company
        mr.transaction_date = frappe.utils.nowdate()
        dated = [getdate(r["required_by"]) for r in rows if r.get("required_by")]
        mr.schedule_date = min(dated) if dated else frappe.utils.nowdate()
        if provided:
            mr.customer = doc.customer
        mr.title = ("%s %s" % (doc.name, supplier or "no supplier"))[:140]
        for r in rows:
            mr.append("items", {"item_code": r["item_code"], "qty": r["qty"], "uom": r["uom"], "conversion_factor": r.get("conversion_factor") or 1,
                                "schedule_date": r.get("required_by") or mr.schedule_date, "warehouse": warehouse, "sales_order": r.get("sales_order"),
                                "description": (r.get("description") or "")[:500] or None, "apparel_requisition_type": requisition_type, "apparel_requisition": doc.name,
                                "apparel_requisition_item": r["key"], "apparel_style_no": r.get("style_no"), "apparel_colour": r.get("colour"),
                                "apparel_hold_reason": r.get("hold_reason")})
        mr.flags.ignore_permissions = True
        mr.insert()
        if cint(frappe.db.get_single_value("Apparel Settings", "auto_submit_material_request")):
            mr.submit()
        names.append(mr.name)
    return names


def requested_so_far(requisition_type, chain_names, key):
    """Stock qty already requested for this line key by every document in the revision chain."""
    if not chain_names:
        return 0.0
    rows = frappe.db.sql("select coalesce(sum(i.stock_qty), 0) from `tabMaterial Request Item` i join `tabMaterial Request` m on m.name = i.parent "
                         "where i.apparel_requisition_type = %s and i.apparel_requisition in %s and i.apparel_requisition_item = %s and m.docstatus < 2",
                         (requisition_type, tuple(chain_names), key))
    return frappe.utils.flt(rows[0][0])


def revision_chain(doctype, previous_field, name):
    """Names of this document and every earlier revision."""
    chain = []
    cur = name
    while cur and cur not in chain:
        chain.append(cur)
        cur = frappe.db.get_value(doctype, cur, previous_field)
    return chain


def stamp_safe(sales_order, style_item, colour, code, date, source_doctype, source_name, partial, planned):
    """Stamp a T&A milestone. Never raises: a T&A problem must not block a purchase, a receipt or a requisition."""
    try:
        run_script("arinox_tna", action="stamp", sales_order=sales_order, style_item=style_item, colour=colour, code=code, date=str(date), source_doctype=source_doctype,
                   source_name=source_name, partial=1 if partial else 0, planned=1 if planned else 0)
    except Exception:
        frappe.log_error(title="T&A stamp failed", message=frappe.get_traceback())


def stamp_safe_requisition(doc, code):
    """Stamp `code` for every style x colour on a requisition."""
    seen = []
    for r in doc.items:
        k = "%s|%s|%s" % (r.sales_order, r.style_item, (r.colour or "").strip().upper())
        if k in seen:
            continue
        seen.append(k)
        stamp_safe(r.sales_order, r.style_item, r.colour, code, frappe.utils.nowdate(), doc.doctype, doc.name, False, False)


def unstamp_safe(doctype, name):
    try:
        run_script("arinox_tna", action="unstamp", source_doctype=doctype, source_name=name)
    except Exception:
        frappe.log_error(title="T&A unstamp failed", message=frappe.get_traceback())
