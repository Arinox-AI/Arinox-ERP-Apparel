# Purchase Receipt, After Cancel: the requisitions are refreshed again and the stamps cleared.
def run(doc):
    # include: lib_samples.py
    # include: lib_mat.py
    # include: lib_purchasing.py
    seen = []
    for pri in doc.items:
        if not pri.get("purchase_order_item"):
            continue
        poi = frappe.db.get_value("Purchase Order Item", pri.purchase_order_item, ["apparel_requisition", "apparel_requisition_type"], as_dict=True)
        if poi and poi.apparel_requisition and [poi.apparel_requisition_type, poi.apparel_requisition] not in seen:
            seen.append([poi.apparel_requisition_type, poi.apparel_requisition])
            refresh_requisition(poi.apparel_requisition_type, poi.apparel_requisition)
    unstamp_safe("Purchase Receipt", doc.name)


run(doc)
