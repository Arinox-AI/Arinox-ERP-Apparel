# Shipment, Before Validate: ERPNext's Shipment insists on pickup details a freight-forwarder booking does not have; give them sensible defaults.
def run(doc):
    if not [r for r in (doc.get("apparel_packing_lists") or []) if r.packing_list]:
        return
    doc.pickup_date = doc.pickup_date or frappe.utils.nowdate()
    doc.pickup_from = doc.pickup_from or "00:00:00"
    doc.pickup_to = doc.pickup_to or "23:59:00"
    doc.shipment_type = doc.shipment_type or "Goods"
    doc.pickup_type = doc.pickup_type or "Self delivery"


run(doc)
