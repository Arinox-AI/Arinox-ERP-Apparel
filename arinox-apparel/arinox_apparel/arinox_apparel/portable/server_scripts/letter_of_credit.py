# Letter of Credit (Before Save): presentation deadline, latest shipment, amount used.
u = frappe.utils
notes = []
doc.on_board_date = None
doc.presentation_deadline = None
if doc.get("shipment"):
    on_board = frappe.db.get_value("Shipment", doc.shipment, "apparel_on_board_date")
    if on_board:
        doc.on_board_date = on_board
        deadline = u.add_days(on_board, u.cint(doc.presentation_days) or 21)
        if doc.expiry_date and u.getdate(deadline) > u.getdate(doc.expiry_date):
            deadline = doc.expiry_date
        doc.presentation_deadline = deadline
        if doc.latest_shipment_date and u.getdate(on_board) > u.getdate(doc.latest_shipment_date):
            notes.append(f"Shipped on {on_board}, after the latest shipment date {doc.latest_shipment_date}.")

drawn = 0
for r in frappe.get_all("Sales Invoice", {"apparel_letter_of_credit": doc.name, "docstatus": 1}, ["grand_total"]):
    drawn = drawn + u.flt(r.grand_total)
doc.drawn_amount = drawn
limit = u.flt(doc.amount) * (1 + u.flt(doc.tolerance_pct) / 100.0)
doc.available_amount = max(0, limit - drawn)
if drawn > limit + 0.005:
    notes.append(f"Invoiced {drawn} against a credit of {doc.amount} (+{doc.tolerance_pct} %).")
if doc.status == "Open" and doc.expiry_date and u.getdate(doc.expiry_date) < u.getdate(u.nowdate()):
    doc.status = "Expired"
    notes.append("The credit has expired.")
doc.check_note = "\n".join(notes)
if notes:
    frappe.msgprint("<br>".join(notes), indicator="orange", title="Letter of Credit")
