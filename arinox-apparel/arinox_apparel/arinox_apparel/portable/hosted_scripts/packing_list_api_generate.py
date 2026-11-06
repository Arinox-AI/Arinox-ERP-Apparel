# API arinox_packing_list_generate_cartons: the carton rows and contents for an unsaved Packing List (form sends it as JSON in `doc`).
# `quantities` ({"colour|size": pieces}) overrides what is packable; otherwise everything finished into A-grade and not yet packed is used.
def main():
    # include: lib_packing.py
    cint = frappe.utils.cint
    d = json.loads(frappe.form_dict.get("doc") or "{}")
    if cint(d.get("docstatus")):
        frappe.throw("Only a draft can be regenerated.")
    items = []
    given = frappe.form_dict.get("quantities")
    if given:
        q = json.loads(given) if isinstance(given, str) else given
        for k in q:
            parts = k.split("|", 1)
            items.append([parts[0], parts[1], cint(q[k])])
    else:
        card = d.get("production_card")
        res = run_script("arinox_engine", action="totals", card=card)
        t = res.get("arinox_result") or {}
        drafts = packed_by_key(card, d.get("name"), [0], None)
        others = packed_by_key(card, d.get("name"), [0, 1], d.get("ship_to"))
        so = frappe.db.get_value("Production Card", card, "sales_order")
        so_items = frappe.get_all("Sales Order Item", {"parent": so}, ["apparel_colour", "apparel_size", "apparel_ship_to", "qty", "apparel_qty_tolerance_pct"])
        for l in frappe.get_all("Production Card Line", {"parent": card}, ["colour", "size"], order_by="idx"):
            key = (l.colour, l.size)
            base = l.colour + "|" + l.size + "|"
            avail = t.get(base + "FIN_A", 0) - t.get(base + "SAMPLE_OUT", 0) - t.get(base + "PACKED", 0) - drafts.get(key, 0)
            rows = [i for i in so_items if i.apparel_colour == l.colour and i.apparel_size == l.size and (not d.get("ship_to") or not i.apparel_ship_to or i.apparel_ship_to == d.get("ship_to"))]
            if rows:
                cap = sum([int(frappe.utils.floor(round(float(i.qty or 0) * (1 + float(i.apparel_qty_tolerance_pct or 0) / 100.0), 6))) for i in rows])
                avail = min(avail, cap - others.get(key, 0))
            if avail > 0:
                items.append([l.colour, l.size, int(avail)])
    if not items:
        frappe.throw("Nothing is available to pack: finish pieces into A-grade first.")
    ratio = {}
    for r in d.get("ratios") or []:
        ratio[r.get("size")] = cint(r.get("pieces_per_pack"))
    plan = plan_cartons(items, d.get("pack_type"), cint(d.get("pcs_per_carton")), ratio, d.get("tail_carton_rule"), cint(d.get("carton_start") or 1))
    cartons = []
    contents = []
    for row in plan:
        cartons.append({"carton_from": row["carton_from"], "carton_to": row["carton_to"], "tail": row["tail"], "carton_type": d.get("carton_type")})
        for c in row["contents"]:
            contents.append({"carton_from": row["carton_from"], "colour": c[0], "size": c[1], "qty_per_carton": c[2]})
    frappe.flags.arinox_result = {"arinox_doc": {"cartons": cartons, "contents": contents}, "rows": len(plan), "plan": plan}


main()
