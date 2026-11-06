# Buyer Claim, After Save / After Submit / After Cancel: while a claim is undecided or being settled the invoice is Disputed so no reminders go out.
def run(doc):
    # include: lib_shipping.py
    # include: lib_claim.py
    sync_invoice(doc)


run(doc)
