# shared helpers from production/summary.py: quantities read back from the ledger for reports. Needs lib_cutting.py (moved_qty).
def live_cards(sales_order, style_item):
    filters = {"docstatus": 1, "status": ["not in", ("Superseded", "Cancelled")]}
    if sales_order:
        filters["sales_order"] = sales_order
    if style_item:
        filters["style_item"] = style_item
    return frappe.get_all("Production Card", filters=filters, pluck="name")


def stage_qty(sales_order, style_item, colour, stages, purpose, process):
    """Sum of ledger quantity for stages of one order x style x colour across its live cards."""
    cards = live_cards(sales_order, style_item)
    if not cards:
        return 0
    cond = ""
    args = [tuple(cards), tuple(stages)]
    if colour:
        cond = cond + " and upper(colour) = upper(%s)"
        args.append(colour)
    if purpose:
        cond = cond + " and purpose = %s"
        args.append(purpose)
    if process:
        cond = cond + " and subcontract_process = %s"
        args.append(process)
    return frappe.utils.flt(frappe.db.sql("select ifnull(sum(qty), 0) from `tabProduction Movement` where production_card in %s and stage in %s" + cond, tuple(args))[0][0])


def good_cut(sales_order, style_item, colour):
    return stage_qty(sales_order, style_item, colour, ["CUT"], None, None) - stage_qty(sales_order, style_item, colour, ["CUT_REJECT"], None, None)


def fabric_usage(sales_order, style_item, colour, fabric_item):
    """[good garments cut, metres drawn net of remnants returned, actual consumption per garment] for one fabric."""
    cut = good_cut(sales_order, style_item, colour)
    net = 0.0
    for card in live_cards(sales_order, style_item):
        net = net + moved_qty(card, "Fabric Issue", fabric_item) - moved_qty(card, "Remnant Return", fabric_item)
    return [cut, net, (net / cut) if cut and net else None]
