# Production Adjustment, Before Submit: a negative adjustment cannot take off more than the ledger holds.
def run(doc):
    qty = frappe.utils.flt(doc.qty)
    if qty < 0:
        out = run_script("arinox_engine", action="total", card=doc.production_card, stage=doc.stage, colour=doc.colour, size=doc.size,
                         purpose=doc.purpose or "Bulk")
        have = out.get("arinox_total") or 0
        if have + qty < -0.000000001:
            frappe.throw("Only %s recorded for %s; cannot take off %s." % (have, doc.stage, abs(qty)))


run(doc)
