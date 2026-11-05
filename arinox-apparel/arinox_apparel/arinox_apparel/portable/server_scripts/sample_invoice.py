# Sales Invoice (Before Save): a sample invoice joins the receivables follow-up like any other customer invoice.
if doc.get("apparel_is_sample_invoice"):
    if not doc.get("po_no"):
        doc.po_no = "SAMPLE"
    doc.apparel_due_basis = "Days after Invoice Date"
    doc.apparel_basis_date = doc.posting_date
    doc.apparel_basis_source = "Invoice"
    doc.apparel_expected_due_date = doc.get("due_date") or doc.posting_date
