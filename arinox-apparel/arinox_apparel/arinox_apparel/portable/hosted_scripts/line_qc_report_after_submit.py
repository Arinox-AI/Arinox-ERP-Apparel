# Line QC Report, After Submit: A-grade passes (finishing), rejects and B-grade go to the ledger; a rejected piece marked "replace" raises a Recut Request.
def run(doc):
    cint = frappe.utils.cint
    rows = []
    if doc.audit_type == "Finishing":
        for p in doc.passes:
            rows.append({"stage": "FIN_A", "colour": p.colour, "size": p.size, "qty": cint(p.qty), "line": doc.line, "source_row": p.name})
    for r in doc.dispositions:
        stage = None
        if r.disposition == "Reject":
            stage = "FIN_REJECT" if doc.audit_type == "Finishing" else "SEW_REJECT"
        elif r.disposition == "B-Grade":
            stage = "FIN_B"
        if stage:
            rows.append({"stage": stage, "colour": r.colour, "size": r.size, "qty": cint(r.qty), "line": doc.line, "fault_source": r.fault_source, "source_row": r.name})
    run_script("arinox_engine", action="post", card=doc.production_card, rows=json.dumps(rows), source_doctype="Line QC Report", source_name=doc.name, posting_date=str(doc.report_date),
               override=0, check=1)
    wanted = {}
    order = []
    for r in doc.dispositions:
        if cint(r.replace) and r.disposition == "Reject":
            k = "%s|%s|%s" % (r.colour, r.size, r.defect_code)
            if k not in wanted:
                wanted[k] = 0
                order.append(k)
            wanted[k] = wanted[k] + cint(r.qty)
    for k in order:
        p = k.split("|")
        d = frappe.get_doc({"doctype": "Recut Request", "production_card": doc.production_card, "colour": p[0], "size": p[1], "qty": wanted[k], "reason": p[2], "remarks": "Raised by %s" % doc.name})
        d.flags.ignore_permissions = True
        try:
            d.insert()
        except Exception:
            frappe.log_error(title="Recut request from QC report failed", message=frappe.get_traceback())


run(doc)
