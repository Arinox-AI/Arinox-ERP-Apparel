# shared helpers from tna/planner.py (+ backfill from tna/events.py): planning dates for an Order TNA, building and re-planning its milestones.
# Needs lib_samples.py (rules) and lib_tna.py (refresh) included first.
def holiday_dates(company):
    """List of non-working dates from the Company's default Holiday List; None when the company has no list."""
    hl = frappe.db.get_value("Company", company, "default_holiday_list") if company else None
    if not hl:
        return None
    return [frappe.utils.getdate(d) for d in frappe.get_all("Holiday", filters={"parent": hl}, pluck="holiday_date")]


def working_day(d, holidays, direction):
    """Move `d` to the next (direction 1) or previous (-1) working day. With no Holiday List only Sundays are off."""
    d = frappe.utils.getdate(d)
    i = 0
    while i < 60:
        off = (d in holidays) if holidays is not None else d.weekday() == 6
        if not off:
            return d
        d = frappe.utils.getdate(frappe.utils.add_days(d, direction))
        i = i + 1
    return d


def plan_dates(rows, order_received, ex_factory, qty, holidays, pcd, overrides, na):
    """rows: dicts with code, basis, after, offset_days, duration_rule, daily_output (in template order). Returns [dates, unresolved codes], dates = code -> {planned, start}
    in template order. A not-applicable milestone passes its predecessor's date through (offset 0) so a skipped step adds no days. `pcd` and `overrides` pin dates."""
    cint = frappe.utils.cint
    getdate = frappe.utils.getdate
    ov = {}
    for k in (overrides or {}):
        if overrides[k]:
            ov[k] = getdate(overrides[k])
    if pcd and "PCD" not in ov:
        ov["PCD"] = getdate(pcd)
    dates = {}
    pending = list(rows)
    p = 0
    while p < len(rows) + 2:
        p = p + 1
        moved = False
        for r in list(pending):
            if r["basis"] == "Order Received":
                base = order_received
            elif r["basis"] == "Ex-Factory":
                base = ex_factory
            elif r["basis"] == "PCD":
                base = (dates.get("PCD") or {}).get("planned") or pcd
            else:
                base = (dates.get(r.get("after")) or {}).get("planned")
            if base is None:
                continue
            offset = cint(r.get("offset_days"))
            if r.get("duration_rule") == "Qty / Daily Output" and cint(r.get("daily_output")):
                offset = max(1, frappe.utils.ceil(frappe.utils.flt(qty) / cint(r["daily_output"])))
            if r["code"] in na:
                offset = 0
            if r["code"] in ov:
                planned = ov[r["code"]]
            else:
                planned = working_day(frappe.utils.add_days(getdate(base), offset), holidays, -1 if offset < 0 else 1)
            start = getdate(base) if r["basis"] == "After Milestone" else planned
            dates[r["code"]] = {"planned": planned, "start": min(start, planned)}
            pending.remove(r)
            moved = True
        if not pending or not moved:
            break
    out = {}
    for r in rows:
        if r["code"] in dates:
            out[r["code"]] = dates[r["code"]]
    return [out, [r["code"] for r in pending]]


def feasibility(dates, ex_factory):
    """[feasible, note]: the last milestone before Ex-Factory must not land after the ex-factory date."""
    if not dates or not ex_factory:
        return [True, None]
    body = {}
    for c in dates:
        if c != "EX_FACTORY":
            body[c] = dates[c]["planned"]
    if not body:
        return [True, None]
    code = sorted(body, key=lambda c: body[c])[-1]
    late = frappe.utils.date_diff(body[code], ex_factory)
    if late > 0:
        return [False, "Plan is %s days late against ex-factory (%s lands on %s)." % (late, code, body[code])]
    return [True, None]


def tech_pack_for(style_item):
    name = frappe.db.get_value("Tech Pack", {"style_item": style_item, "docstatus": 1}, "name", order_by="creation desc")
    return frappe.get_doc("Tech Pack", name) if name else None


def style_of(item_code):
    return frappe.db.get_value("Item", item_code, "variant_of") or item_code


def applies(mtype, sales_order, style_item, customer):
    """Whether a milestone type applies to this style on this order."""
    when = mtype.applies_when or "Always"
    if when == "Always":
        return True
    if when == "Washed Only":
        tp = tech_pack_for(style_item)
        text = ("%s %s" % ((tp.wash_description or "") if tp else "", (tp.wash_code or "") if tp else "")).strip().lower()
        if text and "no wash" not in text:
            return True
        return bool(frappe.db.exists("Sample Approval", {"style_item": style_item, "is_washed": 1}))
    if when == "Printed Only":
        cs_name = None
        for it in frappe.get_all("Sales Order Item", filters={"parent": sales_order}, fields=["item_code", "apparel_cost_sheet"]):
            if it.apparel_cost_sheet and style_of(it.item_code) == style_item:
                cs_name = it.apparel_cost_sheet
                break
        if not cs_name:
            return False
        for ch in frappe.get_doc("Cost Sheet", cs_name).charges:
            if (ch.cost_head or "").lower() == "printing" and not ch.not_applicable and frappe.utils.flt(ch.rate):
                return True
        return False
    rule = get_rules(customer, sales_order, style_item).get(mtype.sample_type)
    return bool(rule) and effective_gate(rule, sales_order) != "No"


def pick_template(customer, product_type, shipment_mode):
    """Most specific template: customer + product type, customer, product type, then the default."""
    best = None
    score = -1
    for t in frappe.get_all("TNA Template", fields=["name", "customer", "product_type", "shipment_mode", "is_default"]):
        s = 0
        for f, v, w in (("customer", customer, 4), ("product_type", product_type, 2), ("shipment_mode", shipment_mode, 1)):
            if t.get(f):
                if t.get(f) != v:
                    s = None
                    break
                s += w
        if s is None:
            continue
        if not (t.customer or t.product_type or t.shipment_mode) and not frappe.utils.cint(t.is_default):
            continue
        if s > score:
            best = t.name
            score = s
    return best or frappe.db.get_single_value("Apparel Settings", "default_tna_template")


def order_groups(sales_order):
    """Sales Order lines grouped to style x colour x ex-factory date (a list of dicts)."""
    groups = {}
    for it in frappe.get_all("Sales Order Item", filters={"parent": sales_order}, fields=["item_code", "qty", "apparel_colour", "apparel_ship_to", "delivery_date"], order_by="idx"):
        key = "%s|%s|%s" % (style_of(it.item_code), (it.apparel_colour or "").strip(), str(frappe.utils.getdate(it.delivery_date)) if it.delivery_date else "")
        g = groups.get(key)
        if not g:
            g = {"style_item": style_of(it.item_code), "colour": (it.apparel_colour or "").strip(), "ex_factory": it.delivery_date, "qty": 0, "ship_tos": []}
            groups[key] = g
        g["qty"] = g["qty"] + frappe.utils.cint(it.qty)
        st = (it.apparel_ship_to or "").strip()
        if st and st not in g["ship_tos"]:
            g["ship_tos"].append(st)
    return [groups[k] for k in groups]


def allocation_for(sales_order, style_item, colour):
    """[factory, pcd, sewing_end] from the Factory Allocation for a style x colour."""
    fa = frappe.db.get_value("Factory Allocation", {"sales_order": sales_order}, "name")
    if not fa:
        return [None, None, None]
    for r in frappe.get_all("Factory Allocation Line", filters={"parent": fa, "style_item": style_item}, fields=["colour", "factory", "pcd", "sewing_end"], order_by="pcd"):
        if not colour or not (r.colour or "").strip() or r.colour.strip().upper() == colour.strip().upper():
            return [r.factory, r.pcd, r.sewing_end]
    return [None, None, None]


def compute_plan(tna):
    """[dates, na codes, unresolved, rows] for an Order TNA document from its template."""
    t = frappe.get_doc("TNA Template", tna.template)
    rows = [{"code": r.milestone_type, "basis": r.basis, "after": r.after_milestone, "offset_days": r.offset_days, "duration_rule": r.duration_rule,
             "daily_output": r.daily_output, "owner_role": r.owner_role} for r in t.milestones]
    so = frappe.db.get_value("Sales Order", tna.sales_order, ["customer", "company"], as_dict=True)
    na = []
    for r in rows:
        if applies(frappe.get_cached_doc("TNA Milestone Type", r["code"]), tna.sales_order, tna.style_item, so.customer):
            continue
        na.append(r["code"])
    al = allocation_for(tna.sales_order, tna.style_item, tna.colour)
    overrides = {}
    if al[2]:
        overrides["BULK_FINISH"] = al[2]
    res = plan_dates(rows, tna.order_received_date, tna.ex_factory_date, tna.order_qty, holiday_dates(so.company), tna.pcd or al[1], overrides, na)
    return [res[0], na, res[1], rows]


def build_milestones(tna):
    plan = compute_plan(tna)
    dates = plan[0]
    na = plan[1]
    rows = plan[3]
    if plan[2]:
        frappe.msgprint("These milestones could not be dated (missing base): %s" % ", ".join(plan[2]), indicator="orange")
    meta = {}
    for r in rows:
        meta[r["code"]] = r
    names = {}
    seq = 0
    for r in rows:
        code = r["code"]
        if code not in dates:
            continue
        seq = seq + 10
        mt = frappe.get_cached_doc("TNA Milestone Type", code)
        ms = frappe.get_doc({"doctype": "TNA Milestone", "order_tna": tna.name, "milestone_type": code, "sequence": seq, "label": mt.label, "department": mt.department,
                             "is_critical": mt.is_critical, "planned_start": dates[code]["start"], "planned_date": dates[code]["planned"], "not_applicable": 1 if code in na else 0})
        ms.flags.ignore_permissions = True
        ms.insert()
        names[code] = ms.name
    for code in names:
        after = meta[code]["after"] if meta[code]["basis"] == "After Milestone" else None
        if after and after in names:
            frappe.db.set_value("TNA Milestone", names[code], "depends_on_tasks", names[after], update_modified=False)
    live = {}
    for c in dates:
        if c not in na:
            live[c] = dates[c]
    fe = feasibility(live, tna.ex_factory_date)
    tna.db_set({"plan_feasible": 1 if fe[0] else 0, "feasibility_note": fe[1]})
    refresh_order_tna(tna.name)


def replan(order_tna):
    """Recompute planned dates after the PCD or the sewing window changed. Before the baseline is locked the planned dates move;
    after it, only the revised dates do (the baseline stays as agreed)."""
    tna = frappe.get_doc("Order TNA", order_tna)
    if tna.status == "Cancelled":
        return
    al = allocation_for(tna.sales_order, tna.style_item, tna.colour)
    if al[0] and tna.factory != al[0]:
        tna.db_set("factory", al[0])
        tna.factory = al[0]
        for n in frappe.get_all("TNA Milestone", filters={"order_tna": order_tna}, pluck="name"):
            frappe.db.set_value("TNA Milestone", n, "factory", al[0], update_modified=False)
    if al[1] and (not tna.pcd or frappe.utils.getdate(tna.pcd) != frappe.utils.getdate(al[1])):
        tna.db_set("pcd", al[1])
        tna.pcd = al[1]
    plan = compute_plan(tna)
    dates = plan[0]
    locked = frappe.utils.cint(tna.baseline_locked)
    getdate = frappe.utils.getdate
    for ms in frappe.get_all("TNA Milestone", filters={"order_tna": order_tna}, fields=["name", "milestone_type", "actual_date", "planned_date", "revised_date", "not_applicable"]):
        d = dates.get(ms.milestone_type)
        if not d or ms.actual_date:
            continue
        if locked:
            if getdate(d["planned"]) != getdate(ms.planned_date):
                frappe.db.set_value("TNA Milestone", ms.name, {"revised_date": d["planned"], "revision_reason": "Factory allocation / plan change"}, update_modified=False)
            elif ms.revised_date:
                frappe.db.set_value("TNA Milestone", ms.name, {"revised_date": None}, update_modified=False)
        else:
            frappe.db.set_value("TNA Milestone", ms.name, {"planned_date": d["planned"], "planned_start": d["start"], "revised_date": None}, update_modified=False)
    live = {}
    for c in dates:
        if c not in plan[1]:
            live[c] = dates[c]
    fe = feasibility(live, tna.ex_factory_date)
    tna.db_set({"plan_feasible": 1 if fe[0] else 0, "feasibility_note": fe[1]})
    refresh_order_tna(order_tna)


def backfill(order_tna):
    """A T&A made after the fact picks up what already happened (needs the arinox_tna script)."""
    tna = frappe.get_doc("Order TNA", order_tna)

    def st(code, date, dt, name):
        run_script("arinox_tna", action="stamp", sales_order=tna.sales_order, style_item=tna.style_item, colour=tna.colour, code=code, date=str(date), source_doctype=dt, source_name=name,
                   partial=0, planned=0)

    st("ORDER_RECEIVED", tna.order_received_date, "Sales Order", tna.sales_order)
    tp = frappe.db.get_value("Tech Pack", {"style_item": tna.style_item, "docstatus": 1}, ["name", "received_on", "buyer_bom_file"], as_dict=True, order_by="creation")
    if tp:
        st("TECH_PACK_RECEIVED", tp.received_on or frappe.utils.nowdate(), "Tech Pack", tp.name)
        if tp.buyer_bom_file:
            st("BOM_RECEIVED", tp.received_on or frappe.utils.nowdate(), "Tech Pack", tp.name)
    run_script("arinox_tna", action="samples", order_tna=tna.name)
    run_script("arinox_tna", action="refind", order_tna=tna.name)
    for m in frappe.get_all("PP Meeting", filters={"sales_order": tna.sales_order, "style_item": tna.style_item, "docstatus": 1}, fields=["name", "meeting_date", "meeting_type"]):
        st("PILOT_RUN" if m.meeting_type == "Pilot Run" else "PP_MEETING", m.meeting_date, "PP Meeting", m.name)
    refresh_order_tna(tna.name)
