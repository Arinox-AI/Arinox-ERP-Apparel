# Cost Sheet, Before Save (validate): revision number, sign-off rows, the costing parameter and charge rows, material and charge checks,
# then the whole build-up: materials -> cost heads in sequence -> FOB (grossed up for price-based charges) -> margin at the quoted price.
def run(doc):
    # include: lib_costing.py
    flt = frappe.utils.flt
    cint = frappe.utils.cint
    COSTING_MANAGER = "Apparel Costing Manager"
    FABRIC_TYPES = ("Fabric", "Lining", "Contrast Fabric")
    SIGNOFF_STEPS = ("Fabric Cost Checked", "First Costing Done", "Second Round Checked", "Final Checked & Approved")
    METRES_PER = {"meter": 1, "metre": 1, "mtr": 1, "m": 1, "yard": 0.9144, "yd": 0.9144, "yds": 0.9144, "cm": 0.01, "inch": 0.0254, "in": 0.0254}

    def to_metres(uom):
        return METRES_PER.get((uom or "Meter").strip().lower())

    def my_roles():
        return (frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role"))

    # ---- revision
    if doc.amended_from:
        prev = frappe.db.get_value("Cost Sheet", doc.amended_from, "revision_no") or 1
        doc.revision_no = prev + 1
    elif not doc.revision_no:
        doc.revision_no = 1
    if not doc.company:
        doc.company = frappe.db.get_value("Company", {}, "name")

    # ---- the four sign-off steps exist, in order, keeping who signed
    saved = {}
    for r in doc.signoffs:
        saved[r.step] = {"step": r.step, "signed_by": r.signed_by, "signed_on": r.signed_on, "remarks": r.remarks}
    rows = []
    for step in SIGNOFF_STEPS:
        rows.append(saved.get(step) or {"step": step})
    doc.set("signoffs", rows)

    # ---- parameter and charges
    if not doc.costing_parameter:
        doc.costing_parameter = find_costing_parameter(doc.customer, doc.product_type, doc.costing_date, doc.currency)
    if not doc.charges:
        doc.set("charges", charge_rows(doc.costing_parameter))
    # a mandatory head left out of the table is a cost left out: put the row back (rate from the parameter if it has one) so it is visible;
    # submit then asks for a rate or Not Applicable on it
    have_heads = [c.cost_head for c in doc.charges]
    for head in get_cost_heads():
        if head.is_mandatory and head.calc_type != "From Materials" and head.name not in have_heads:
            prm = frappe.db.get_value("Costing Parameter Rate", {"parent": doc.costing_parameter, "parenttype": "Costing Parameter", "cost_head": head.name}, ["rate", "not_applicable"], as_dict=True) if doc.costing_parameter else None
            doc.append("charges", {"cost_head": head.name, "rate": flt(prm.rate) if prm else 0, "not_applicable": prm.not_applicable if prm else 0, "source": "Parameter" if prm else "Manual"})

    # ---- materials
    groups = {}
    for m in doc.materials:
        if m.per_carton and not cint(doc.pcs_per_carton):
            frappe.throw("Row %s: set Pcs per Carton to cost a carton per piece." % m.idx)
        if flt(m.conversion_factor) < 0 or flt(m.exchange_rate) < 0:
            frappe.throw("Row %s: conversion factor and exchange rate cannot be negative." % m.idx)
        # the exchange rate converts ONE unit of the rate currency into the sheet currency (CNY -> USD is about 0.14, not 7.3). A currency worth
        # far less than one USD / EUR / GBP / CHF with a rate above 1 is the rate the wrong way round: it would cost the line many times over.
        if m.price_currency and m.price_currency != doc.currency and flt(m.exchange_rate) > 1 and doc.currency in ("USD", "EUR", "GBP", "CHF") and m.price_currency in ("VND", "INR", "JPY", "CNY", "HKD", "AED", "PKR", "BDT", "LKR", "THB", "IDR", "KRW"):
            frappe.throw("Row %s (%s): the exchange rate for %s is %s, which values 1 %s at more than 1 %s. Enter how many %s ONE %s is worth (about %s), not the other way round." % (m.idx, m.description, m.price_currency, flt(m.exchange_rate), m.price_currency, doc.currency, doc.currency, m.price_currency, flt(1 / flt(m.exchange_rate), 4)))
        if flt(m.wastage_pct) < 0 or flt(m.wastage_pct) >= 100:
            frappe.throw("Row %s: wastage %% must be between 0 and 100." % m.idx)
        if flt(m.wastage_pct) and not (m.wastage_reason or "").strip():
            frappe.throw("Row %s (%s): wastage %s%% needs a reason. Wastage is set per order, never by default." % (m.idx, m.description, flt(m.wastage_pct)))
        if m.option_group:
            key = m.option_group.strip().lower()
            if key not in groups:
                groups[key] = []
            groups[key].append(m)
        else:
            m.is_selected = 1
    for key in groups:
        g = groups[key]
        if len(g) > 4:
            frappe.throw("Option group %s has %s options. The maximum is 4." % (g[0].option_group, len(g)))
        selected = [r for r in g if r.is_selected]
        if len(g) > 1 and len(selected) != 1:
            frappe.throw("Option group %s: select exactly one option to price the garment (now %s)." % (g[0].option_group, len(selected)))
        if len(g) == 1:
            g[0].is_selected = 1

    # ---- charges
    seen = []
    for c in doc.charges:
        if c.cost_head in seen:
            frappe.throw("Cost head %s appears twice." % c.cost_head)
        seen.append(c.cost_head)
        head = frappe.db.get_value("Cost Head", c.cost_head, ["calc_type", "sequence", "head_group"], as_dict=True)
        c.calc_type = head.calc_type
        c.sequence = head.sequence
        c.head_group = head.head_group
        if c.calc_type == "From Materials":
            frappe.throw("%s is calculated from the materials table and cannot be a charge row." % c.cost_head)
        if c.not_applicable:
            c.rate = 0

    # ---- the maths
    fabric = 0.0
    other = 0.0
    fabric_m = 0.0
    unknown_length = False
    for m in doc.materials:
        cons = (1.0 / cint(doc.pcs_per_carton)) if m.per_carton else flt(m.consumption)
        qty = cons * (1 + flt(m.wastage_pct) / 100)
        factor = flt(m.conversion_factor) or 1
        fx = (flt(m.exchange_rate) or 1) if (m.price_currency and m.price_currency != doc.currency) else 1
        m.amount = flt(qty * factor * flt(m.rate) * fx, 6)
        if not m.is_selected:
            continue
        if m.material_type in FABRIC_TYPES:
            fabric = fabric + m.amount
            per_unit = to_metres(m.uom)
            if per_unit:
                fabric_m = fabric_m + qty * per_unit
            else:
                unknown_length = True
        else:
            other = other + m.amount
    doc.fabric_cost = flt(fabric, 6)
    doc.trim_cost = flt(other, 6)
    doc.material_cost = flt(fabric + other, 6)
    doc.fabric_metres = flt(fabric_m, 6)

    charges = sorted(doc.charges, key=lambda r: ((r.sequence or 0), r.idx))
    direct = 0.0
    for c in charges:
        rate = 0 if c.not_applicable else flt(c.rate)
        if c.calc_type == "Per Piece":
            c.amount = rate
        elif c.calc_type == "Per SAM Minute":
            c.amount = rate * flt(doc.sam)
        elif c.calc_type == "Per Metre of Fabric":
            if unknown_length:
                frappe.throw("A selected fabric row has a UOM that is not a length. Use Meter, Yard, cm or inch.")
            c.amount = rate * flt(doc.fabric_metres)
        elif c.calc_type == "Percent of Material":
            c.amount = doc.material_cost * rate / 100
        else:
            continue
        c.amount = flt(c.amount, 6)
        if c.head_group != "Profit":
            direct = direct + c.amount
    doc.product_cost = flt(doc.material_cost + direct, 6)

    running = doc.material_cost
    profit_amount = 0.0
    price_pct = 0.0
    profit_pct = 0.0
    price_rows = []
    for c in charges:
        rate = 0 if c.not_applicable else flt(c.rate)
        if c.calc_type in ("Per Piece", "Per SAM Minute", "Per Metre of Fabric", "Percent of Material"):
            pass
        elif c.calc_type == "Percent of Product Cost":
            c.amount = flt(doc.product_cost * rate / 100, 6)
        elif c.calc_type == "Percent of Subtotal":
            c.amount = flt(running * rate / 100, 6)
        elif c.calc_type == "Percent of Price":
            price_rows.append(c)
            if c.head_group == "Profit":
                profit_pct = profit_pct + rate
            else:
                price_pct = price_pct + rate
            continue
        if c.head_group == "Profit":
            profit_amount = profit_amount + c.amount
        else:
            running = running + c.amount

    doc.subtotal = flt(running, 6)
    doc.conversion_cost = flt(running - doc.material_cost, 6)
    doc.profit_amount = flt(profit_amount, 6)
    doc.price_cost_pct = price_pct
    doc.profit_pct = profit_pct
    total_pct = price_pct + profit_pct
    if total_pct >= 100:
        frappe.throw("Price-based charges add up to %s%%. They must be below 100%%." % total_pct)
    doc.computed_price = flt((doc.subtotal + doc.profit_amount) / (1 - total_pct / 100.0), 6)
    if not flt(doc.quoted_price):
        doc.quoted_price = flt(doc.computed_price, 2)
    for c in price_rows:
        c.amount = flt(flt(doc.quoted_price) * (0 if c.not_applicable else flt(c.rate)) / 100, 6)

    # margin at the quoted price: price-based charges other than profit scale with the price
    price = flt(doc.quoted_price)
    cost = flt(doc.subtotal) + price * flt(doc.price_cost_pct) / 100
    margin = price - cost
    doc.total_cost_at_quote = flt(cost, 6)
    doc.margin_amount = flt(margin, 6)
    doc.margin_pct = flt(margin / price * 100, 2) if price else 0
    doc.markup_pct = flt(margin / cost * 100, 2) if cost else 0
    floor = None
    if doc.costing_parameter:
        floor = frappe.db.get_value("Costing Parameter", doc.costing_parameter, "margin_floor_pct")
    if floor is None or floor == 0:
        floor = frappe.db.get_single_value("Apparel Settings", "default_margin_floor_pct")
    doc.margin_floor_pct = flt(floor)
    doc.below_floor = 1 if doc.margin_pct < flt(doc.margin_floor_pct) else 0
    doc.order_value = flt(doc.quoted_price) * (doc.order_qty or 0)
    if doc.local_currency and flt(doc.local_exchange_rate):
        doc.quoted_price_local = flt(flt(doc.quoted_price) * flt(doc.local_exchange_rate), 2)
    else:
        doc.quoted_price_local = 0

    # ---- approval: below the floor needs a Costing Manager; a price move after approval resets it
    if not doc.below_floor:
        if doc.approval_status == "Pending" or doc.approval_status == "Rejected":
            doc.approval_status = "Not Required"
    else:
        if doc.approval_status == "Approved":
            tol = flt(frappe.db.get_single_value("Apparel Settings", "approval_tolerance_pct"))
            old = flt(doc.approved_price)
            moved = True
            if old:
                moved = abs(flt(doc.quoted_price) - old) / old * 100 > tol
            if moved:
                doc.approval_status = "Pending"
                doc.approved_by = None
                doc.approved_on = None
                doc.approved_price = None
                frappe.msgprint("Quoted price changed after approval. Margin approval reset to Pending.", indicator="orange", alert=True)
        elif doc.approval_status == "Not Required":
            doc.approval_status = "Pending"

    # ---- advisory: lines left unpriced and BOM lines missing from this sheet. A save is never blocked by these.
    notes = []
    unpriced = [m for m in doc.materials if m.is_selected and flt(m.consumption) and not flt(m.rate)]
    if unpriced:
        names = [(u.description or u.material_type) for u in unpriced]
        notes.append("%s material line(s) have no rate and are costed at 0: %s%s." % (len(unpriced), ", ".join(names[:6]), " ..." if len(names) > 6 else ""))
    if doc.tech_pack:
        bom = len(frappe.get_all("Tech Pack Material", {"parent": doc.tech_pack, "parenttype": "Tech Pack"}, pluck="name"))
        if len(doc.materials) < bom:
            notes.append("The Tech Pack %s has %s material lines but this sheet has %s. Lines left out of a costing are costs left out of the price." % (doc.tech_pack, bom, len(doc.materials)))
    if notes:
        frappe.msgprint("<br>".join(notes), title="Check the costing", indicator="orange")


run(doc)
