# API arinox_ledger_rebuild_movements: recompute the ledger of one card from its submitted source documents (a repair tool; System Manager only). Answers the rows written.
# Each source document's rows are built here exactly as its own After Submit script builds them; the ledger is rewritten without the flow check.
def main():
    cint = frappe.utils.cint
    flt = frappe.utils.flt
    card = frappe.form_dict.get("card")
    roles = frappe.get_all("Role", pluck="name") if frappe.session.user == "Administrator" else frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")
    if "System Manager" not in roles:
        frappe.throw("Only a System Manager can rebuild the ledger.")
    frappe.get_doc("Production Card", card).check_permission("read")
    for mv in frappe.get_all("Production Movement", filters={"production_card": card}, pluck="name"):
        frappe.delete_doc("Production Movement", mv, force=1, ignore_permissions=True)
    written = [0]

    def post(rows, dt, name, date):
        if not rows:
            return
        run_script("arinox_engine", action="post", card=card, rows=json.dumps(rows), source_doctype=dt, source_name=name, posting_date=str(date), override=0, check=0)
        written[0] = written[0] + len(rows)

    for n in frappe.get_all("Production Adjustment", filters={"production_card": card, "docstatus": 1}, pluck="name"):
        d = frappe.get_doc("Production Adjustment", n)
        post([{"stage": d.stage, "colour": d.colour, "size": d.size, "qty": flt(d.qty), "purpose": d.purpose or "Bulk", "process": d.subcontract_process, "source_row": d.name}], d.doctype, d.name, d.posting_date)
    for n in frappe.get_all("Lay Report", filters={"production_card": card, "docstatus": 1}, pluck="name"):
        d = frappe.get_doc("Lay Report", n)
        rows = []
        if d.component == "Shell":
            for s in d.sizes:
                rows.append({"stage": "CUT", "colour": d.colour, "size": s.size, "qty": cint(s.pieces_cut), "purpose": d.purpose, "shade_band": d.shade_band, "line": d.line, "source_row": s.name})
            for r in d.panel_rejects:
                rows.append({"stage": "CUT_REJECT", "colour": d.colour, "size": r.size, "qty": cint(r.qty), "purpose": d.purpose, "shade_band": d.shade_band, "fault_source": r.fault_source, "source_row": r.name})
        post(rows, d.doctype, d.name, d.lay_date)
    for n in frappe.get_all("Line Input", filters={"production_card": card, "docstatus": 1}, pluck="name"):
        d = frappe.get_doc("Line Input", n)
        post([{"stage": "SEW_IN", "colour": r.colour, "size": r.size, "qty": cint(r.qty), "purpose": d.purpose, "line": d.line, "shade_band": r.shade_band, "source_row": r.name}
              for r in d.bundles if (r.component or "Shell") == "Shell"], d.doctype, d.name, d.input_date)
    for n in frappe.db.sql("select distinct parent from `tabDaily Line Report Output` where production_card = %s", (card,), pluck=True):
        d = frappe.get_doc("Daily Line Report", n)
        if d.docstatus != 1:
            continue
        post([{"stage": "SEW_OUT", "colour": r.colour, "size": r.size, "qty": cint(r.qty), "purpose": r.purpose or "Bulk", "line": d.line, "source_row": r.name}
              for r in d.outputs if r.production_card == card], d.doctype, d.name, d.report_date)
    for n in frappe.get_all("Line QC Report", filters={"production_card": card, "docstatus": 1}, pluck="name"):
        d = frappe.get_doc("Line QC Report", n)
        rows = []
        if d.audit_type == "Finishing":
            for p in d.passes:
                rows.append({"stage": "FIN_A", "colour": p.colour, "size": p.size, "qty": cint(p.qty), "line": d.line, "source_row": p.name})
        for r in d.dispositions:
            stage = None
            if r.disposition == "Reject":
                stage = "FIN_REJECT" if d.audit_type == "Finishing" else "SEW_REJECT"
            elif r.disposition == "B-Grade":
                stage = "FIN_B"
            if stage:
                rows.append({"stage": stage, "colour": r.colour, "size": r.size, "qty": cint(r.qty), "line": d.line, "fault_source": r.fault_source, "source_row": r.name})
        post(rows, d.doctype, d.name, d.report_date)
    for n in frappe.get_all("Subcontract Challan", filters={"production_card": card, "docstatus": 1}, pluck="name"):
        d = frappe.get_doc("Subcontract Challan", n)
        post([{"stage": "SC_OUT", "colour": r.colour, "size": r.size, "qty": r.qty, "process": d.subcontract_process, "supplier": d.supplier, "shade_band": r.shade_band, "source_row": r.name}
              for r in d.rows], d.doctype, d.name, d.challan_date)
    for n in frappe.db.sql("select distinct parent from `tabSubcontract Return Row` where production_card = %s", (card,), pluck=True):
        d = frappe.get_doc("Subcontract Return", n)
        if d.docstatus != 1:
            continue
        rows = []
        for r in d.rows:
            base = {"colour": r.colour, "size": r.size, "process": d.subcontract_process, "supplier": d.supplier, "shade_band": r.shade_band, "source_row": r.name}
            if r.good_qty:
                x = dict(base)
                x.update({"stage": "SC_BACK_GOOD", "qty": r.good_qty})
                rows.append(x)
            if r.reject_vendor_qty:
                x = dict(base)
                x.update({"stage": "SC_BACK_REJECT_VENDOR", "qty": r.reject_vendor_qty, "fault_source": "Subcontractor"})
                rows.append(x)
            if r.reject_factory_qty:
                x = dict(base)
                x.update({"stage": "SC_BACK_REJECT_FACTORY", "qty": r.reject_factory_qty, "fault_source": (frappe.db.get_value("Apparel Defect Code", r.defect_code, "fault_source") if r.defect_code else None) or "Unknown"})
                rows.append(x)
        post(rows, d.doctype, d.name, d.return_date)
    for n in frappe.get_all("Finishing Receipt", filters={"production_card": card, "docstatus": 1}, pluck="name"):
        d = frappe.get_doc("Finishing Receipt", n)
        post([{"stage": "FIN_IN", "colour": r.colour, "size": r.size, "qty": r.qty, "line": d.line, "supplier": d.supplier, "shade_band": r.shade_band, "source_row": r.name} for r in d.rows],
             d.doctype, d.name, d.receipt_date)
    for n in frappe.get_all("Packing List", filters={"production_card": card, "docstatus": 1}, pluck="name"):
        d = frappe.get_doc("Packing List", n)
        sums = {}
        order = []
        for ct in d.contents:
            k = ct.colour + "\t" + ct.size
            if k not in sums:
                sums[k] = 0
                order.append(k)
            sums[k] = sums[k] + cint(ct.pieces_total)
        post([{"stage": "PACKED", "colour": k.split("\t")[0], "size": k.split("\t")[1], "qty": sums[k]} for k in order], d.doctype, d.name, d.packing_date)
    # Delivery Notes are ERPNext documents: their rows carry the card
    for n in frappe.db.sql("select distinct parent from `tabDelivery Note Item` where apparel_production_card = %s and docstatus = 1", (card,), pluck=True):
        d = frappe.get_doc("Delivery Note", n)
        sums = {}
        order = []
        for it in d.items:
            if it.get("apparel_production_card") != card or not it.get("so_detail"):
                continue
            cs = frappe.db.get_value("Sales Order Item", it.so_detail, ["apparel_colour", "apparel_size"])
            k = cs[0] + "\t" + cs[1]
            if k not in sums:
                sums[k] = 0
                order.append(k)
            sums[k] = sums[k] + cint(it.stock_qty or it.qty)
        post([{"stage": "SHIPPED", "colour": k.split("\t")[0], "size": k.split("\t")[1], "qty": sums[k]} for k in order], d.doctype, d.name, d.posting_date)
    frappe.flags.arinox_result = written[0]


main()
