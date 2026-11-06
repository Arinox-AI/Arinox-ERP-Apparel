# API arinox_pp_meeting_load_from_requisitions: fabric required and received, shade count and trim readiness per colour, from the requisitions of this order and style.
def main():
    # include: lib_materials.py
    flt = frappe.utils.flt
    d = json.loads(frappe.form_dict.get("doc") or "{}")
    if d.get("name") and frappe.db.exists("PP Meeting", d.get("name")):
        frappe.get_doc("PP Meeting", d.get("name")).check_permission("write")
    rows = frappe.db.sql("""select c.colour, sum(c.net_qty) net, sum(c.accepted_qty) accepted, group_concat(distinct i.shade_bands_found) shades
        from `tabFabric Requisition Item` c join `tabFabric Requisition` p on p.name = c.parent
        left join `tabFabric Inspection` i on i.fabric_requisition = p.name and i.docstatus = 1 and i.colour = c.colour
        where p.docstatus = 1 and p.status not in ('Superseded', 'Cancelled') and c.sales_order = %s and c.style_item = %s group by c.colour""",
                         (d.get("sales_order"), d.get("style_item")), as_dict=True)
    colours = list(d.get("colours") or [])
    for r in rows:
        row = None
        for c in colours:
            if (c.get("colour") or "").strip().upper() == (r.colour or "").strip().upper():
                row = c
        if not row:
            row = {"colour": r.colour}
            colours.append(row)
        row["fabric_required_m"] = flt(r.net, 2)
        row["fabric_received_m"] = flt(r.accepted, 2)
        bands = []
        for b in (r.shades or "").replace(";", ",").split(","):
            if b.strip() and b.strip() not in bands:
                bands.append(b.strip())
        row["no_of_shades"] = len(bands) or row.get("no_of_shades")
    out = {"colours": colours}
    for field, need in (("sewing_trims", "Sewing"), ("packing_trims", "Packing")):
        status = trim_readiness(d.get("sales_order"), d.get("style_item"), need)
        if status:
            out[field] = status
    frappe.flags.arinox_result = {"arinox_doc": out, "count": len(rows)}


main()
