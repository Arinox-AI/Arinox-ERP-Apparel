# Opportunity (Apparel Inquiry), Before Validate: the delivery window must not end before it starts.
f = doc.get("apparel_delivery_from")
t = doc.get("apparel_delivery_to")
if f and t and frappe.utils.getdate(t) < frappe.utils.getdate(f):
    frappe.throw(
        "Delivery Window To (%s) is before Delivery Window From (%s). Correct the dates."
        % (frappe.utils.formatdate(t), frappe.utils.formatdate(f)),
        title="Delivery window",
    )
