# API Server Script `arinox_tna`: the time-and-action stamping used by many documents (tna/events.py + status.py), in one place because the sandbox cannot import.
# Callers: run_script("arinox_tna", action=..., ...) inside try/except (a T&A problem must never block a purchase, a receipt or an approval).
#   stamp    sales_order, style_item, colour, code, date, source_doctype, source_name, partial (0/1), planned (0/1)
#   unstamp  source_doctype, source_name
#   refresh  order_tna
#   samples  order_tna        (set the approval milestones from the Sample Approvals that apply)
#   refind   order_tna        (pick up FR / TR raised and fabric booked from documents that already exist)
def main():
    # include: lib_samples.py
    # include: lib_tna.py
    cint = frappe.utils.cint
    getdate = frappe.utils.getdate
    form = frappe.form_dict
    action = form.get("action")
    SAMPLE_CODES = {"Lab Dip": "LAB_DIP", "Fit": "FIT", "Bulk Trim": "TRIMS_APPROVED", "Bulk Fabric": "BULK_FABRIC_APPROVED", "Fabric Test (FPT)": "FPT_PASSED", "TOP": "TOP", "Size Set": "TOP"}
    PP_TYPES = ("PP", "Garment Test (GPT)")

    def tnas_for(sales_order, style_item, colour):
        filters = {"style_item": style_item, "status": ["!=", "Cancelled"]}
        if sales_order:
            filters["sales_order"] = sales_order
        rows = frappe.get_all("Order TNA", filters=filters, fields=["name", "colour", "sales_order", "style_item"])
        return [r for r in rows if not colour or not norm(r.colour) or norm(r.colour) == norm(colour)]

    def milestone(tna, code):
        name = frappe.db.get_value("TNA Milestone", {"order_tna": tna, "milestone_type": code}, "name")
        return frappe.get_doc("TNA Milestone", name) if name else None

    def save(ms):
        ms.flags.ignore_permissions = True
        ms.save()

    def stamp(sales_order, style_item, colour, code, date, source_doctype, source_name, partial, planned):
        for t in tnas_for(sales_order, style_item, colour):
            ms = milestone(t.name, code)
            if not ms or cint(ms.not_applicable):
                continue
            changed = False
            if planned:
                if not ms.actual_date and date and getdate(date) != getdate(ms.planned_date):
                    ms.revised_date = getdate(date)
                    ms.revision_reason = ms.revision_reason or "Supplier plan (%s)" % source_name
                    changed = True
            elif partial:
                if not ms.actual_date and not cint(ms.partial):
                    ms.partial = 1
                    ms.source_doctype = source_doctype
                    ms.source_name = source_name
                    changed = True
            else:
                same = ms.source_doctype == source_doctype and ms.source_name == source_name
                if not ms.actual_date or same:
                    ms.actual_date = getdate(date or frappe.utils.nowdate())
                    ms.partial = 0
                    ms.source_doctype = source_doctype
                    ms.source_name = source_name
                    changed = True
            if changed:
                save(ms)

    def refind(ms):
        """Best-effort: set `ms` from another live document of the right kind."""
        tna = frappe.db.get_value("Order TNA", ms.order_tna, ["sales_order", "style_item", "colour"], as_dict=True)
        found = None
        code = ms.milestone_type
        if code == "FR_RAISED" or code == "TR_RAISED":
            dt = "Fabric Requisition" if code == "FR_RAISED" else "Trim Requisition"
            child = "Fabric Requisition Item" if code == "FR_RAISED" else "Trim Requisition Item"
            r = frappe.db.sql("select p.name, date(p.approved_on) from `tab%s` p join `tab%s` c on c.parent = p.name where p.docstatus = 1 and p.status != 'Cancelled' "
                              "and c.sales_order = %%s and c.style_item = %%s and (c.colour is null or c.colour = '' or upper(c.colour) = upper(%%s)) order by p.approved_on limit 1" % (dt, child),
                              (tna.sales_order, tna.style_item, tna.colour or ""))
            found = [dt, r[0][0], r[0][1]] if r else None
        elif code == "FABRIC_BOOKED":
            r = frappe.db.sql("select o.name, o.transaction_date from `tabPurchase Order` o join `tabPurchase Order Item` i on i.parent = o.name where o.docstatus = 1 "
                              "and i.apparel_requisition_type = 'FR' and i.sales_order = %s and upper(i.apparel_colour) = upper(%s) order by o.creation limit 1", (tna.sales_order, tna.colour or ""))
            found = ["Purchase Order", r[0][0], r[0][1]] if r else None
        if found:
            ms.reload()
            ms.actual_date = getdate(found[2])
            ms.source_doctype = found[0]
            ms.source_name = found[1]
            save(ms)

    def unstamp(source_doctype, source_name):
        for name in frappe.get_all("TNA Milestone", filters={"source_doctype": source_doctype, "source_name": source_name}, pluck="name"):
            ms = frappe.get_doc("TNA Milestone", name)
            ms.actual_date = None
            ms.partial = 0
            ms.source_doctype = None
            ms.source_name = None
            save(ms)
            refind(ms)

    def sync_samples(tna_name):
        so = frappe.db.get_value("Order TNA", tna_name, ["sales_order", "style_item", "colour", "customer"], as_dict=True)

        def approval_ok(stype):
            """Does the gate let this sample type pass for the style x colour (an approval, or one not required / not raised and not Required)?"""
            rule = get_rules(so.customer, so.sales_order, so.style_item).get(stype)
            gate = effective_gate(rule, so.sales_order) if rule else "No"
            f = scope_filters(so.sales_order, so.style_item)
            f["sample_type"] = stype
            rows = frappe.get_all("Sample Approval", filters=f, fields=["name", "status", "colour"])
            if rule and rule["per_colour"]:
                rows = [r for r in rows if not (r.colour or "").strip() or norm(r.colour) == norm(so.colour)]
            if not rows:
                return gate != "Required"
            return len([r for r in rows if r.status not in GATE_OK]) == 0

        def dates_for(types):
            f = scope_filters(so.sales_order, so.style_item)
            f["sample_type"] = ["in", list(types)]
            f["status"] = ["in", list(APPROVED)]
            rows = frappe.get_all("Sample Approval", filters=f, fields=["name", "colour", "approved_on", "sample_type"])
            return [[r.name, r.approved_on] for r in rows if r.approved_on and (not norm(r.colour) or norm(r.colour) == norm(so.colour))]

        codes = []
        for t in SAMPLE_CODES:
            if SAMPLE_CODES[t] not in codes:
                codes.append(SAMPLE_CODES[t])
        codes.append("PP_GPT")
        for code in codes:
            ms = milestone(tna_name, code)
            if not ms or cint(ms.not_applicable):
                continue
            types = [t for t in SAMPLE_CODES if SAMPLE_CODES[t] == code] if code != "PP_GPT" else list(PP_TYPES)
            ok = len([t for t in types if approval_ok(t)]) == len(types)
            done = dates_for(types) if ok else []
            if code == "PP_GPT":
                ok = bool(dates_for(["PP"])) and approval_ok("Garment Test (GPT)")
                done = dates_for(PP_TYPES) if ok else []
            elif code == "TOP":
                ok = bool(done)
            if done and (ok or code != "PP_GPT"):
                best = sorted(done, key=lambda d: d[1])[-1]
                if not ms.actual_date or ms.source_doctype == "Sample Approval":
                    ms.actual_date = getdate(best[1])
                    ms.partial = 0
                    ms.source_doctype = "Sample Approval"
                    ms.source_name = best[0]
                    save(ms)
            elif ms.source_doctype == "Sample Approval" and ms.actual_date:
                ms.actual_date = None
                ms.source_doctype = None
                ms.source_name = None
                save(ms)

    if action == "stamp":
        stamp(form.get("sales_order"), form.get("style_item"), form.get("colour"), form.get("code"), form.get("date"), form.get("source_doctype"), form.get("source_name"),
              cint(form.get("partial")), cint(form.get("planned")))
        for t in tnas_for(form.get("sales_order"), form.get("style_item"), form.get("colour")):
            refresh_order_tna(t.name)
    elif action == "unstamp":
        unstamp(form.get("source_doctype"), form.get("source_name"))
    elif action == "refresh":
        refresh_order_tna(form.get("order_tna"))
    elif action == "refind":
        for code in ("FR_RAISED", "TR_RAISED", "FABRIC_BOOKED"):
            ms = milestone(form.get("order_tna"), code)
            if ms and not ms.actual_date and not cint(ms.not_applicable):
                refind(ms)
    elif action == "samples":
        sync_samples(form.get("order_tna"))
        refresh_order_tna(form.get("order_tna"))
    else:
        frappe.throw("arinox_tna: unknown action %s" % action)


main()
