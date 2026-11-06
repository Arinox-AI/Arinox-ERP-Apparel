# API arinox_freight_allocated_costs: the shipment's cost shared over the orders on board (by CBM at sea, by chargeable weight by air). Answers [[contract, share, cost]], basis, cost.
def main():
    # include: lib_shipping.py
    # include: lib_shipment.py
    shipment = frappe.form_dict.get("shipment")
    frappe.get_doc("Shipment", shipment).check_permission("read")
    res = allocated_costs(shipment)
    frappe.flags.arinox_result = {"rows": res[0], "basis": res[1], "cost": res[2]}


main()
