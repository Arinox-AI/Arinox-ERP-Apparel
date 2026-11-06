# Cut Bundle, Before Save: a bundle quantity cannot be changed; void the lay and cut it again.
def run(doc):
    if not doc.is_new() and doc.has_value_changed("qty") and doc.status != "Voided":
        frappe.throw("A bundle quantity cannot be changed. Void the lay and cut it again.")


run(doc)
