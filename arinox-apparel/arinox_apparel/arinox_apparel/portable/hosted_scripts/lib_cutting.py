# shared helpers from production/cutting.py and production/stock.py: roll suggestion for a cut plan, bundle numbering for a lay, kit components, and the Stock Entries
# of the production floor (fabric issue, remnant return). Needs lib_mat.py (to_metres) for the cut plan only.
OK_STATUS = ("Accepted", "Accepted by Lot")


def setting(field):
    return frappe.db.get_single_value("Apparel Settings", field)


def roll_available(batch, warehouse, item_code):
    """Metres of a roll (Batch) in a warehouse. 0 when the warehouse is unknown."""
    if not warehouse:
        return 0
    return frappe.utils.flt(frappe.call("erpnext.stock.doctype.batch.batch.get_batch_qty", batch_no=batch, warehouse=warehouse, item_code=item_code))


def roll_info(batch):
    b = frappe.db.get_value("Batch", batch, ["item", "apparel_roll_no", "apparel_dye_lot", "apparel_shade_band", "apparel_width_cm", "apparel_inspection_status",
                                              "apparel_shrinkage_warp_pct", "apparel_shrinkage_weft_pct"], as_dict=True)
    if not b:
        frappe.throw("Roll %s not found." % batch)
    return b


def required_components(card, colour):
    """Fabric roles that make up a garment of this colour on the production card (Shell, Lining, ...)."""
    roles = frappe.get_all("Production Card Fabric", filters={"parent": card, "colour": colour}, pluck="material_role")
    out = []
    for r in (roles or ["Shell"]):
        if r not in out:
            out.append(r)
    return sorted(out)


def suggest_rolls(plan_name):
    """Allocate the rolls in the Cutting WIP warehouse to the lays of a cut plan: group by shade band, then width, then longest roll first. Nothing is saved."""
    flt = frappe.utils.flt
    plan = frappe.get_doc("Cut Plan", plan_name)
    wh = setting("cutting_wip_warehouse")
    pool = []
    for b in frappe.get_all("Batch", filters={"item": plan.fabric_item, "disabled": 0},
                            fields=["name", "apparel_roll_no", "apparel_shade_band", "apparel_width_cm", "apparel_inspection_status", "apparel_dye_lot"]):
        if b.apparel_inspection_status not in OK_STATUS:
            continue
        avail = roll_available(b.name, wh, plan.fabric_item)
        if avail > 0:
            pool.append({"batch": b.name, "roll_no": b.apparel_roll_no, "shade": b.apparel_shade_band or "", "width": flt(b.apparel_width_cm), "length": avail, "dye_lot": b.apparel_dye_lot})
    out = []
    short = []
    spread = flt(setting("max_width_spread_cm") or 1)
    for lay in sorted(plan.lays, key=lambda l: l.lay_no):
        need = flt(lay.planned_plies) * flt(lay.marker_length_m)
        cands = [r for r in pool if (not (lay.shade_band or "").strip() or r["shade"] == lay.shade_band)
                 and (not flt(lay.width_group_cm) or abs(r["width"] - flt(lay.width_group_cm)) <= spread)
                 and (not flt(lay.marker_width_cm) or not r["width"] or r["width"] >= flt(lay.marker_width_cm))]
        if not (lay.shade_band or "").strip() and cands:    # no shade named: keep to the shade band of the longest roll
            first = sorted(cands, key=lambda r: -r["length"])[0]
            cands = [r for r in cands if r["shade"] == first["shade"] and abs(r["width"] - first["width"]) <= spread]
        cands = sorted(cands, key=lambda r: -r["length"])
        taken = []
        got = 0.0
        for r in cands:
            if got >= need - 1e-9:
                break
            use = min(r["length"], need - got)
            plies = int(frappe.utils.floor(use / flt(lay.marker_length_m))) if flt(lay.marker_length_m) else 0
            if plies <= 0:
                continue
            metres = plies * flt(lay.marker_length_m)
            taken.append({"batch": r["batch"], "roll_no": r["roll_no"], "plies": plies, "metres": round(metres, 3), "shade": r["shade"], "width": r["width"]})
            got = got + metres
            r["length"] = r["length"] - metres
        out.append({"lay_no": lay.lay_no, "needed_m": round(need, 3), "allocated_m": round(got, 3), "rolls": taken})
        if got < need - 1e-9:
            short.append({"lay_no": lay.lay_no, "short_m": round(need - got, 3)})
    left = [{"batch": r["batch"], "roll_no": r["roll_no"], "metres": round(r["length"], 3), "shade": r["shade"]} for r in pool if r["length"] > 1e-9]
    return {"lays": out, "unallocated": left, "short": short}


def next_ply(card):
    """First free ply number on a production card (sticker numbers never repeat on a card)."""
    return frappe.utils.cint(frappe.db.sql("select ifnull(max(ply_to), 0) from `tabCut Bundle` where production_card = %s", (card,))[0][0]) + 1


def chunks(first, last, size):
    """Ply ranges [[from, to], ...] of at most `size` plies covering first..last."""
    size = max(frappe.utils.cint(size), 1)
    out = []
    a = first
    while a <= last:
        b = min(a + size - 1, last)
        out.append([a, b])
        a = b + 1
    return out


def new_bundle(lay, card, size, body, ply_from, ply_to, qty, rolls, kit_key, short, bundle_no):
    if bundle_no is None:
        bundle_no = frappe.utils.cint(frappe.db.sql("select ifnull(max(bundle_no), 0) from `tabCut Bundle` where production_card = %s", (card,))[0][0]) + 1
    d = frappe.get_doc({"doctype": "Cut Bundle", "production_card": card, "lay_report": lay.name, "colour": lay.colour, "size": size, "component": lay.component or "Shell",
                        "purpose": lay.purpose, "bundle_no": bundle_no, "body_no": body, "ply_from": ply_from, "ply_to": ply_to, "qty": qty, "shade_band": lay.shade_band,
                        "roll_nos": rolls, "kit_key": kit_key, "status": "Cut", "is_short": frappe.utils.cint(short)})
    d.insert(ignore_permissions=True)
    return d.name


def make_bundles(lay):
    """Create the Cut Bundles of a submitted Lay Report. A paired (lining, pocketing) lay mirrors the ply ranges of its shell lay so every component of a garment
    carries the same ply number. Returns the bundle names."""
    cint = frappe.utils.cint
    card = lay.production_card
    size_bundle = cint(frappe.db.get_value("Production Card", card, "bundle_size")) or cint(setting("bundle_size")) or 20
    rolls = ", ".join([r.roll_no or r.batch for r in lay.rolls])
    names = []
    if lay.paired_with:
        src = frappe.get_all("Cut Bundle", filters={"lay_report": lay.paired_with, "status": ["!=", "Voided"]}, order_by="bundle_no",
                             fields=["size", "body_no", "ply_from", "ply_to", "qty", "kit_key", "is_short", "bundle_no"])
        for b in src:
            names.append(new_bundle(lay, card, b.size, b.body_no, b.ply_from, b.ply_to, b.qty, rolls, b.kit_key, b.is_short, None))
        return names
    first = next_ply(card)
    plies = cint(lay.total_plies)
    last = first + plies - 1
    n = cint(frappe.db.sql("select ifnull(max(bundle_no), 0) from `tabCut Bundle` where production_card = %s", (card,))[0][0])
    for s in lay.sizes:
        for body in range(1, max(cint(s.ratio), 1) + 1):
            for ab in chunks(first, last, size_bundle):
                qty = ab[1] - ab[0] + 1
                key = "%s|%s|%s-%s|%s" % (lay.colour, s.size, ab[0], ab[1], body)
                n = n + 1
                names.append(new_bundle(lay, card, s.size, body, ab[0], ab[1], qty, rolls, key, 1 if qty < size_bundle else 0, n))
    return names


def void_bundles(lay_name):
    """Cancel of a lay: bundles are voided (their numbers are never reused). Blocked once any bundle left the cutting room."""
    moved = frappe.get_all("Cut Bundle", filters={"lay_report": lay_name, "status": ["not in", ("Cut", "Voided")]}, pluck="name")
    if moved:
        frappe.throw("Bundles %s have already left the cutting room. Take them back before cancelling the lay." % ", ".join(moved[:5]))
    for n in frappe.get_all("Cut Bundle", filters={"lay_report": lay_name}, pluck="name"):
        frappe.db.set_value("Cut Bundle", n, "status", "Voided", update_modified=False)


def kit_missing(bundle_names):
    """For shell bundles about to go to a line: the kit keys whose lining / pocketing bundles are missing."""
    missing = []
    for n in bundle_names:
        b = frappe.db.get_value("Cut Bundle", n, ["production_card", "colour", "component", "kit_key"], as_dict=True)
        if b.component != "Shell":
            continue
        for comp in required_components(b.production_card, b.colour):
            if comp == "Shell":
                continue
            if not frappe.db.exists("Cut Bundle", {"production_card": b.production_card, "kit_key": b.kit_key, "component": comp, "status": ["!=", "Voided"]}):
                missing.append("%s (%s)" % (b.kit_key, comp))
    return missing


def make_transfer(company, rows, kind, card, remarks, submit):
    """Material Transfer for `rows` = dicts(item_code, qty, s_warehouse, t_warehouse, batch_no). Returns the name, or None when nothing moves.
    The entry is tagged with the production card and the kind so reports can sum it."""
    rows = [r for r in rows if frappe.utils.flt(r.get("qty")) > 0]
    if not rows:
        return None
    se = frappe.new_doc("Stock Entry")
    se.stock_entry_type = "Material Transfer"
    se.purpose = "Material Transfer"
    se.company = company
    se.apparel_production_card = card
    se.apparel_issue_kind = kind
    for r in rows:
        line = {"item_code": r["item_code"], "qty": r["qty"], "s_warehouse": r["s_warehouse"], "t_warehouse": r["t_warehouse"]}
        if r.get("batch_no"):
            line["batch_no"] = r["batch_no"]
            line["use_serial_batch_fields"] = 1
        se.append("items", line)
    se.remarks = remarks
    se.flags.ignore_permissions = True
    se.insert()
    if submit:
        se.submit()
    return se.name


def cancel_entry(name):
    if name and frappe.db.exists("Stock Entry", name):
        d = frappe.get_doc("Stock Entry", name)
        d.flags.ignore_permissions = True
        if d.docstatus == 1:
            d.cancel()
        elif d.docstatus == 0:
            frappe.delete_doc("Stock Entry", name, ignore_permissions=True, force=True)


def moved_qty(card, kind, item_code):
    """Quantity moved by submitted entries of this kind for a production card (optionally one item)."""
    cond = ""
    args = [card, kind]
    if item_code:
        cond = " and d.item_code = %s"
        args.append(item_code)
    return frappe.utils.flt(frappe.db.sql("select ifnull(sum(d.qty), 0) from `tabStock Entry Detail` d join `tabStock Entry` s on s.name = d.parent "
                                          "where s.docstatus = 1 and s.apparel_production_card = %s and s.apparel_issue_kind = %s" + cond, tuple(args))[0][0])


def refresh_issued(card):
    """Write the issued metres onto the fabric rows of an issued card."""
    done = []
    for row in frappe.get_all("Production Card Fabric", filters={"parent": card}, fields=["name", "fabric_item"], order_by="idx"):
        if not row.fabric_item or row.fabric_item in done:
            continue
        done.append(row.fabric_item)
        frappe.db.set_value("Production Card Fabric", row.name, "issued_m", moved_qty(card, "Fabric Issue", row.fabric_item), update_modified=False)


def issue_fabric_entry(card_name, rolls):
    """Issue rolls from the fabric store to Cutting WIP. rolls = [{batch_no, qty}]. Only accepted rolls leave the store."""
    card = frappe.get_doc("Production Card", card_name)
    if card.docstatus != 1:
        frappe.throw("Issue the production card first.")
    if not rolls:
        frappe.throw("Choose at least one roll to issue.")
    src = setting("store_warehouse_fabric")
    dst = setting("cutting_wip_warehouse")
    if not src or not dst:
        frappe.throw("Set the fabric store and Cutting WIP warehouses in Apparel Settings.")
    items = []
    fabrics = [f.fabric_item for f in card.fabrics]
    for r in rolls:
        b = frappe.db.get_value("Batch", r["batch_no"], ["item", "apparel_inspection_status", "apparel_roll_no"], as_dict=True)
        if not b:
            frappe.throw("Roll %s not found." % r["batch_no"])
        if b.apparel_inspection_status not in OK_STATUS:
            frappe.throw("Roll %s is %s. Only accepted rolls can be issued to cutting." % (b.apparel_roll_no or r["batch_no"], b.apparel_inspection_status or "not inspected"))
        if b.item not in fabrics:
            frappe.throw("Roll %s is %s, which is not a fabric of production card %s." % (b.apparel_roll_no or r["batch_no"], b.item, card.name))
        if frappe.utils.flt(r.get("qty")) <= 0:
            frappe.throw("Roll %s: enter the metres to issue (above zero)." % (b.apparel_roll_no or r["batch_no"]))
        items.append({"item_code": b.item, "qty": frappe.utils.flt(r["qty"]), "s_warehouse": src, "t_warehouse": dst, "batch_no": r["batch_no"]})
    name = make_transfer(card.company, items, "Fabric Issue", card.name, "Fabric issued to cutting for %s" % card.name, True)
    refresh_issued(card.name)
    return name
