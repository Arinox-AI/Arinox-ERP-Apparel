# API arinox_final_inspection_pick_cartons: draw the cartons to open, at random from the lot's own carton numbers. The seed comes back so the
# draw is stored and can be repeated. The form sends the unsaved inspection as JSON in `doc`.
def main():
    # include: lib_inspection.py
    cint = frappe.utils.cint
    d = json.loads(frappe.form_dict.get("doc") or "{}")
    if cint(d.get("docstatus")):
        frappe.throw("Cartons can only be drawn on a draft.")
    lots = [l.get("packing_list") for l in (d.get("lots") or [])]
    if not lots:
        frappe.throw("Add the packing lists in the lot.")
    pool = []
    cartons = 0
    for pl in lots:
        for c in frappe.get_all("Packing List Carton", {"parent": pl}, ["carton_from", "carton_to", "tail"]):
            for n in range(cint(c.carton_from), cint(c.carton_to) + 1):
                pool.append([pl, n, cint(c.tail)])
                cartons = cartons + 1
    how_many = int(frappe.utils.ceil(cartons ** 0.5)) if cartons > 0 else 0
    now = frappe.utils.now_datetime()
    seed = frappe.form_dict.get("seed") or (now.microsecond * 997 + now.second * 31 + now.minute) % 2147483647 + 1
    picked = draw_cartons(pool, how_many, int(seed))
    sscc = {}
    for r in frappe.get_all("Packing List SSCC", {"parent": ["in", lots]}, ["parent", "carton_no", "sscc"]):
        sscc[(r.parent, r.carton_no)] = r.sscc
    rows = [{"packing_list": p[0], "carton_no": p[1], "sscc": sscc.get((p[0], p[1]))} for p in picked]
    frappe.flags.arinox_result = {"arinox_doc": {"cartons_picked": rows, "draw_seed": int(seed)}, "picked": len(rows)}


main()
