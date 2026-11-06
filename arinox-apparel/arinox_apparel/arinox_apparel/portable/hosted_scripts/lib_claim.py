# shared helpers of the Buyer Claim: the claim window against arrival, and syncing the invoice's dispute flag. Needs lib_shipping.py.
NO_WINDOW = ("Chargeback", "Concession")


def window_check(claim_type, arrival, on_date, quality_days, quantity_days):
    """[days allowed, days since arrival, ok]. A claim after the window needs a reason to be accepted."""
    cint = frappe.utils.cint
    if claim_type in NO_WINDOW:
        return [0, 0, True]
    allowed = cint(quality_days if claim_type in ("Quality", "Wrong Item", "Other") else quantity_days)
    if not arrival or not allowed:
        return [allowed, 0, True]
    since = frappe.utils.date_diff(frappe.utils.getdate(on_date), frappe.utils.getdate(arrival))
    return [allowed, since, since <= allowed]


def sync_invoice(claim):
    """While a claim is undecided or being settled, the invoice is Disputed so no reminders go out."""
    if not claim.sales_invoice:
        return
    open_claims = frappe.db.count("Buyer Claim", {"sales_invoice": claim.sales_invoice, "docstatus": ["<", 2], "status": ["in", ["Open", "Under Review"]], "name": ["!=", claim.name if claim.docstatus == 2 else ""]})
    frappe.db.set_value("Sales Invoice", claim.sales_invoice, "apparel_dispute_reason", ("Open claim %s" % claim.name) if open_claims else "", update_modified=False)
