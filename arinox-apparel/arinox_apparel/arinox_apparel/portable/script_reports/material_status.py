def main(filters):
    # include: lib_material_status.py

    def C(f, l, t="Data", w=110, o=None):
        d = {"fieldname": f, "label": l, "fieldtype": t, "width": w}
        if o:
            d["options"] = o
        return d

    columns = [C("status", "Status", w=130), C("days_late", "Days Late", "Int", 80), C("sales_order", "Sales Order", "Link", 120, "Sales Order"), C("customer", "Buyer", "Link", 120, "Customer"),
               C("style_no", "Style", w=100), C("colour", "Colour", w=100), C("type", "Type", w=50), C("item", "Material", "Link", 150, "Item"), C("supplier", "Supplier", "Link", 130, "Supplier"),
               C("requisition", "Requisition", w=110), C("required_by", "Required By", "Date", 100), C("net", "Needed", "Float", 90), C("ordered", "Ordered", "Float", 90),
               C("po", "Purchase Order", w=130), C("po_date", "PO Date", "Date", 90), C("etd_planned", "ETD Plan", "Date", 90), C("etd_revised", "ETD Revised", "Date", 90),
               C("etd_actual", "ETD Actual", "Date", 90), C("eta", "ETA", "Date", 90), C("received", "Received", "Float", 90), C("in_inspection", "In QC", "Float", 80),
               C("accepted", "Accepted", "Float", 90), C("rejected", "Rejected", "Float", 80), C("balance", "To Receive", "Float", 90), C("claim_deadline", "Claim By", "Date", 90)]
    return (columns, material_rows(filters))


data = list(main(filters))
