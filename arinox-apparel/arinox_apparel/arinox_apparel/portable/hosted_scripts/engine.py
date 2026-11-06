# API Server Script `arinox_engine`: the production ledger and its flow rules, in one place, for a site that cannot import code.
# Document scripts call it with run_script("arinox_engine", action=..., ...). The app's reference implementation is
# production/ledger.py + production/flow.py; the same tests are the specification.
#
# actions:  post   card, rows (JSON), source_doctype, source_name, posting_date, override (0/1), check (0/1)
#           unpost source_doctype, source_name
#           total  card, stage, colour, size, purpose        -> frappe.flags.arinox_total
#           check  card, rows (JSON), override                -> raises if a row exceeds its limit
#           bulk_gate sales_order, style, colour, stage ("pilot" or "bulk")  -> arinox_result {applies, style, colour, blockers, warnings}
#                  (production/gate.py: buyer approvals, PP meeting, materials, and for "bulk" the pilot run)
# Everything sits inside main(): in the sandbox module-level functions cannot see each other.

def main():
    form = frappe.form_dict
    action = form.get("action")
    STAGES = ("CUT", "CUT_REJECT", "SEW_IN", "SEW_OUT", "SEW_REJECT", "SC_OUT", "SC_BACK_GOOD", "SC_BACK_REJECT_VENDOR",
              "SC_BACK_REJECT_FACTORY", "FIN_IN", "FIN_A", "FIN_B", "FIN_REJECT", "SAMPLE_OUT", "PACKED", "SHIPPED")
    REJECT_STAGES = ("CUT_REJECT", "SEW_REJECT", "SC_BACK_REJECT_VENDOR", "SC_BACK_REJECT_FACTORY", "FIN_REJECT")
    CUT_PURPOSES = ("Bulk", "Pilot", "Sample")
    STATUS_BY_STAGE = (("SHIPPED", "Shipped"), ("PACKED", "Packed"), ("FIN_IN", "In Finishing"), ("SC_OUT", "At Subcontractor"),
                       ("SEW_IN", "In Sewing"), ("CUT", "In Cutting"))

    def num(n):
        if float(n) == int(n):
            return str(int(n))
        return str(round(n, 2))

    def sval(field, default):
        v = frappe.db.get_single_value("Apparel Settings", field)
        if v is None or v == "":
            return default
        return v

    def repair_accepted(card, colour, size):
        r = frappe.db.sql(
            "select ifnull(sum(r.accepted_for_repair), 0) from `tabSubcontract Return Row` r "
            "join `tabSubcontract Return` p on p.name = r.parent "
            "where p.docstatus = 1 and r.production_card = %s and r.colour = %s and r.size = %s", (card, colour, size))
        return r[0][0] or 0

    def make_flow(card):
        """Totals of one card, loaded once; limit() and apply() answer and absorb rows so a document's rows count together."""
        doc = frappe.get_doc("Production Card", card)
        T = {}
        for r in frappe.db.sql(
                "select colour, size, stage, ifnull(purpose, ''), ifnull(subcontract_process, ''), sum(qty) from `tabProduction Movement` "
                "where production_card = %s group by colour, size, stage, purpose, subcontract_process", card):
            T[r[0], r[1], r[2], r[3], r[4]] = r[5] or 0
        lines = {}
        for l in doc.lines:
            lines[l.colour, l.size] = l
        route = sorted(doc.processes, key=lambda p: (0 if p.position == "Before Sewing" else 1, int(p.sequence or 0), p.idx))

        def t(colour, size, stage, purpose=None, process=None):
            total = 0
            for k in T:
                if k[0] == colour and k[1] == size and k[2] == stage:
                    if (purpose is None or k[3] == purpose) and (process is None or k[4] == process):
                        total = total + T[k]
            return total

        def apply(row):
            k = (row["colour"], row["size"], row["stage"], row.get("purpose") or "Bulk", row.get("process") or "")
            T[k] = T.get(k, 0) + row["qty"]

        def good_cut(colour, size):
            return t(colour, size, "CUT") - t(colour, size, "CUT_REJECT")

        def route_for(colour, position):
            out = []
            for p in route:
                c = (p.colour or "").strip()
                if p.position == position and (not c or c.upper() == colour.strip().upper()):
                    out.append(p)
            return out

        def back_good(colour, size, process):
            return t(colour, size, "SC_BACK_GOOD", process=process)

        def after_output(colour, size):
            after = route_for(colour, "After Sewing")
            if after:
                return back_good(colour, size, after[-1].subcontract_process)
            return t(colour, size, "SEW_OUT")

        def limit(row):
            """(max qty the row may add, 'block' or 'warn'), or (None, None) when no rule applies."""
            stage = row["stage"]
            colour = row["colour"]
            size = row["size"]
            purpose = row.get("purpose") or "Bulk"
            process = row.get("process") or ""
            if stage == "CUT":
                line = lines.get((colour, size))
                if purpose == "Re-cut":
                    lost = 0
                    for s in REJECT_STAGES:
                        lost = lost + t(colour, size, s)
                    return lost - t(colour, size, "CUT", purpose="Re-cut"), "block"
                if not line:
                    frappe.throw("%s %s is not on production card %s." % (colour, size, card))
                cap = (line.planned_cut_qty or 0) + int(sval("cut_cap_extra_pcs", 3))
                done = 0
                for p in CUT_PURPOSES:
                    done = done + t(colour, size, "CUT", purpose=p)
                mode = sval("cut_cap_mode", "Block")
                if mode == "Off":
                    return None, None
                return cap - done, ("warn" if mode == "Warn" else "block")
            if stage == "SEW_IN":
                avail = good_cut(colour, size)
                for p in route_for(colour, "Before Sewing"):
                    avail = min(avail, back_good(colour, size, p.subcontract_process))
                return avail - t(colour, size, "SEW_IN"), "block"
            if stage == "SEW_OUT" or stage == "SEW_REJECT":
                return t(colour, size, "SEW_IN") - t(colour, size, "SEW_OUT") - t(colour, size, "SEW_REJECT"), "block"
            if stage == "SC_OUT":
                full = route_for(colour, "Before Sewing") + route_for(colour, "After Sewing")
                names = [p.subcontract_process for p in full]
                if process not in names:
                    frappe.throw("%s is not on the route of production card %s for colour %s." % (process, card, colour))
                i = names.index(process)
                before = full[i].position == "Before Sewing"
                if i == 0 or full[i - 1].position != full[i].position:
                    prior = good_cut(colour, size) if before else t(colour, size, "SEW_OUT")
                else:
                    prior = back_good(colour, size, full[i - 1].subcontract_process)
                return prior - t(colour, size, "SC_OUT", process=process), "block"
            if stage == "FIN_IN":
                return after_output(colour, size) + repair_accepted(card, colour, size) - t(colour, size, "FIN_IN"), "block"
            if stage == "FIN_A" or stage == "FIN_B" or stage == "FIN_REJECT":
                return t(colour, size, "FIN_IN") - t(colour, size, "FIN_A") - t(colour, size, "FIN_B") - t(colour, size, "FIN_REJECT"), "block"
            if stage == "SAMPLE_OUT" or stage == "PACKED":
                return t(colour, size, "FIN_A") - t(colour, size, "SAMPLE_OUT") - t(colour, size, "PACKED"), "block"
            if stage == "SHIPPED":
                return t(colour, size, "PACKED") - t(colour, size, "SHIPPED"), "block"
            return None, None   # SC_BACK_* are limited per challan row by the Subcontract Return itself

        def check(rows, override):
            problems = []
            for row in rows:
                if row["qty"] > 0 and not override:
                    lim = limit(row)
                    if lim[0] is not None and row["qty"] > lim[0] + 0.000000001:
                        msg = "%s: %s %s %s - %s entered, %s available." % (
                            row["stage"], row["colour"], row["size"], row.get("process") or "", num(row["qty"]), num(max(lim[0], 0)))
                        if lim[1] == "warn":
                            frappe.msgprint(msg, indicator="orange", title="Production Flow")
                        else:
                            problems.append(msg)
                apply(row)
            if problems:
                frappe.throw("<br>".join(problems), title="Production Flow")

        return {"check": check, "t": t}

    def clean_rows(rows):
        out = []
        for r in rows:
            if not r.get("qty"):
                continue
            if r["stage"] not in STAGES:
                frappe.throw("Unknown production stage %s." % r["stage"])
            row = dict(r)
            row["colour"] = (r.get("colour") or "").strip()
            row["size"] = (r.get("size") or "").strip()
            row["qty"] = float(r["qty"])
            if not row.get("purpose"):
                row["purpose"] = "Bulk"
            out.append(row)
        return out

    def refresh_card_status(card):
        """Card status follows the furthest stage that has quantities. Closed, Superseded and Cancelled cards are left alone."""
        row = frappe.db.get_value("Production Card", card, ["docstatus", "status"], as_dict=True)
        if not row or row.docstatus != 1 or row.status in ("Superseded", "Cancelled", "Closed"):
            return
        present = [r[0] for r in frappe.db.sql("select distinct stage from `tabProduction Movement` where production_card = %s", card)]
        status = "Issued"
        for pair in STATUS_BY_STAGE:
            if pair[0] in present:
                status = pair[1]
                break
        if status != row.status:
            frappe.db.set_value("Production Card", card, "status", status, update_modified=False)

    def post():
        card = form.get("card")
        rows = clean_rows(json.loads(form.get("rows") or "[]"))
        if not rows:
            return
        if form.get("check") is None or int(form.get("check")):
            make_flow(card)["check"](rows, int(form.get("override") or 0))
        head = frappe.db.get_value("Production Card", card, ["sales_order", "style_item"], as_dict=True)
        when = frappe.utils.getdate(form.get("posting_date") or frappe.utils.nowdate())
        for r in rows:
            mv = frappe.get_doc({
                "doctype": "Production Movement", "production_card": card, "sales_order": head.sales_order, "style_item": head.style_item,
                "colour": r["colour"], "size": r["size"], "stage": r["stage"], "purpose": r["purpose"],
                "subcontract_process": r.get("process") or None, "qty": r["qty"], "posting_date": when, "line": r.get("line") or None,
                "supplier": r.get("supplier") or None, "shade_band": r.get("shade_band") or None,
                "fault_source": r.get("fault_source") or None, "source_doctype": form.get("source_doctype"),
                "source_name": form.get("source_name"), "source_row": r.get("source_row")})
            mv.insert(ignore_permissions=True, ignore_links=True)    # the source document is mid-submit; the ledger never blocks on it
        refresh_card_status(card)

    def unpost():
        src = form.get("source_doctype")
        name = form.get("source_name")
        cards = [r[0] for r in frappe.db.sql(
            "select distinct production_card from `tabProduction Movement` where source_doctype = %s and source_name = %s", (src, name))]
        for mv in frappe.get_all("Production Movement", {"source_doctype": src, "source_name": name}, pluck="name"):
            frappe.delete_doc("Production Movement", mv, force=1, ignore_permissions=True)
        for c in cards:
            refresh_card_status(c)

    def transfer():
        """A revision of a production card keeps the history: every ledger row and stage document that points at the old card is
        pointed at the new one. Submitted documents are not edited, only their link moves."""
        old = form.get("old")
        new = form.get("new")
        if not old or old == new:
            return
        done = []
        for dt in frappe.get_all("DocField", {"fieldname": "production_card", "fieldtype": "Link", "options": "Production Card"}, pluck="parent"):
            if dt == "Production Card" or dt == "Production Card Line" or dt in done:
                continue
            done.append(dt)
            for n in frappe.get_all(dt, {"production_card": old}, pluck="name"):
                frappe.db.set_value(dt, n, "production_card", new, update_modified=False)

    def totals():
        out = {}
        for r in frappe.db.sql("select colour, size, stage, sum(qty) from `tabProduction Movement` where production_card = %s group by colour, size, stage", form.get("card")):
            out[r[0] + "|" + r[1] + "|" + r[2]] = r[3] or 0
        frappe.flags.arinox_result = out

    def bulk_gate():
        # include: lib_samples.py
        # include: lib_pp.py
        # include: lib_materials.py
        cint = frappe.utils.cint
        sales_order = form.get("sales_order")
        style = form.get("style")
        colour = form.get("colour")
        stage = form.get("stage") or "bulk"
        if not style or not sales_order:
            frappe.flags.arinox_result = {"applies": False, "blockers": [], "warnings": []}
            return
        rules = get_rules(None, sales_order, style)
        samples = frappe.get_all("Sample Approval", filters=scope_filters(sales_order, style), fields=["name", "sample_type", "status", "colour"])
        blockers = []
        for stype in rules:
            rule = rules[stype]
            gate = effective_gate(rule, sales_order)
            if gate == "No":
                continue
            mine = [x for x in samples if x.sample_type == stype and (not rule["per_colour"] or not (x.colour or "").strip() or norm(x.colour) == norm(colour))]
            where = stype + (" (%s)" % colour if rule["per_colour"] and colour else "")
            if gate == "Required" and not mine:
                blockers.append("%s: no approval record yet." % where)
            for x in mine:
                if x.status not in GATE_OK:
                    blockers.append("%s: %s is %s." % (where, x.name, x.status))
        if cint(frappe.db.get_single_value("Apparel Settings", "require_pp_meeting")):
            held = cutting_actions_open(sales_order, style)
            if not held[0]:
                blockers.append("PP Meeting: not held (no submitted PP Meeting for this style on this order).")
            for r in held[1]:
                blockers.append("PP Meeting: cutting comment still open: %s" % (r.comment or "")[:80])
        mat = material_gate(sales_order, style, colour)
        blockers = blockers + mat[0]
        if stage == "bulk":
            # the pilot run, only when a live production card requires one
            cards = frappe.get_all("Production Card", filters={"sales_order": sales_order, "style_item": style, "docstatus": 1, "status": ["not in", ("Superseded", "Cancelled")]},
                                   fields=["name", "pilot_required", "pilot_waiver"], order_by="creation desc", limit=1)
            if cards and cint(cards[0].pilot_required) and not cint(cards[0].pilot_waiver):
                runs = frappe.get_all("Pilot Run", filters={"production_card": cards[0].name, "docstatus": 1}, fields=["name", "status"])
                if not runs:
                    blockers.append("Pilot Run: no pilot run recorded for production card %s." % cards[0].name)
                else:
                    good = []
                    for r in runs:
                        if r.status not in ("Approved", "Approved with Comments"):
                            continue
                        cols = [norm(c) for c in frappe.get_all("Pilot Run Colour", filters={"parent": r.name}, pluck="colour")]
                        if not cols or not colour or norm(colour) in cols:
                            good.append(r.name)
                    if not good:
                        blockers.append("Pilot Run: no approved pilot run for %s (production card %s)." % (colour or "this colour", cards[0].name))
        frappe.flags.arinox_result = {"applies": True, "style": style, "colour": colour, "blockers": blockers, "warnings": mat[1]}

    if action == "totals":
        totals()
    elif action == "transfer":
        transfer()
    elif action == "post":
        post()
    elif action == "unpost":
        unpost()
    elif action == "check":
        make_flow(form.get("card"))["check"](clean_rows(json.loads(form.get("rows") or "[]")), int(form.get("override") or 0))
    elif action == "total":
        f = make_flow(form.get("card"))
        frappe.flags.arinox_total = f["t"](form.get("colour"), form.get("size"), form.get("stage"), form.get("purpose") or None)
    elif action == "bulk_gate":
        bulk_gate()
    else:
        frappe.throw("arinox_engine: unknown action %s" % action)


main()
