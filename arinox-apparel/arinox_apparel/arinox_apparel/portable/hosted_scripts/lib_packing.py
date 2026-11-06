# shared helpers: carton planning and the packing-list rules that need no document (production/packing.py, production/maths.py)
def carton_cbm(length_cm, width_cm, height_cm):
    return float(length_cm) * float(width_cm) * float(height_cm) / 1000000.0


def over_short_pct(shipped, ordered):
    o = float(ordered or 0)
    if not o:
        return None
    return (float(shipped) - o) / o * 100.0


def full_packs(qty_by_size, ratio_by_size):
    """Complete ratio packs available: min over sizes of floor(qty / ratio)."""
    packs = None
    for size in ratio_by_size:
        r = ratio_by_size[size]
        if not r:
            continue
        n = int(frappe.utils.floor(float(qty_by_size.get(size, 0)) / float(r)))
        if packs is None or n < packs:
            packs = n
    return packs or 0


def gs1_check_digit(body):
    """GS1 mod-10 check digit for a numeric body (the 17-digit SSCC body)."""
    digits = [int(c) for c in str(body)]
    digits.reverse()
    total = 0
    i = 0
    for d in digits:
        total = total + d * (3 if i % 2 == 0 else 1)
        i = i + 1
    return (10 - total % 10) % 10


def sscc_number(prefix, serial):
    """18-digit SSCC: extension digit 0 + company prefix + serial padded to 17 digits, then the GS1 check digit."""
    prefix = str(prefix)
    room = 16 - len(prefix)
    if not prefix.isdigit() or len(prefix) < 7 or len(prefix) > 10:
        frappe.throw("The GS1 company prefix must be 7 to 10 digits.")
    if len(str(serial)) > room:
        frappe.throw("The SSCC serial %s no longer fits after the prefix." % serial)
    body = "0" + prefix + str(serial).zfill(room)
    return body + str(gs1_check_digit(body))


def check_ranges(ranges):
    """ranges: [(from, to)] in any order. Problems: a row ending before it starts, overlaps, gaps."""
    problems = []
    rows = sorted([(int(r[0]), int(r[1])) for r in ranges])
    for r in rows:
        if r[1] < r[0]:
            problems.append("Carton range %s~%s ends before it starts." % (r[0], r[1]))
    for i in range(len(rows) - 1):
        a = rows[i]
        b = rows[i + 1]
        if b[0] <= a[1]:
            problems.append("Carton %s is in two rows (%s~%s and %s~%s)." % (b[0], a[0], a[1], b[0], b[1]))
        elif b[0] != a[1] + 1:
            problems.append("Cartons %s to %s are missing between %s~%s and %s~%s." % (a[1] + 1, b[0] - 1, a[0], a[1], b[0], b[1]))
    return problems


def tail_cartons(pool, rule, capacity):
    """Fill the leftover pieces into cartons of `capacity` pieces by the tail rule. Pool items are [colour, size, qty]."""
    out = []
    if rule == "Own Carton":
        for p in pool:
            out.append([[p[0], p[1], p[2]]])
        return out
    groups = [pool]
    if rule == "Mixed Size Only":
        by = {}
        order = []
        for p in pool:
            if p[0] not in by:
                by[p[0]] = []
                order.append(p[0])
            by[p[0]].append(p)
        groups = [by[c] for c in order]
    for group in groups:
        cur = []
        room = capacity
        for p in group:
            q = p[2]
            while q > 0:
                take = min(q, room)
                cur.append([p[0], p[1], take])
                q = q - take
                room = room - take
                if room == 0:
                    out.append(cur)
                    cur = []
                    room = capacity
        if cur:
            out.append(cur)
    return out


def plan_cartons(items, pack_type, pcs_per_carton, ratio, tail_rule, start):
    """items: [[colour, size, pieces]] in packing order; ratio: {size: pieces per pack}.
    Returns rows {carton_from, carton_to, tail, pieces_per_carton, contents: [[colour, size, qty_per_carton]]}."""
    cap = int(pcs_per_carton or 0)
    if cap <= 0:
        frappe.throw("Pieces per carton must be above zero.")
    full = []
    pool = []
    items = [[i[0], i[1], int(i[2])] for i in items if int(i[2]) > 0]
    if pack_type == "Solid Colour Solid Size":
        for i in items:
            n = i[2] // cap
            rem = i[2] % cap
            if n:
                full.append([[[i[0], i[1], cap]], n])
            if rem:
                pool.append([i[0], i[1], rem])
    elif pack_type == "Solid Colour Assorted Size":
        ratio = dict([(s, int(ratio[s])) for s in (ratio or {}) if int(ratio[s])])
        if not ratio:
            frappe.throw("Enter the ratio for assorted packs.")
        pack = sum([ratio[s] for s in ratio])
        if cap % pack:
            frappe.throw("Pieces per carton (%s) must be a multiple of the pack size (%s)." % (cap, pack))
        per_carton = cap // pack
        colours = []
        for i in items:
            if i[0] not in colours:
                colours.append(i[0])
        for c in colours:
            by_size = {}
            for i in items:
                if i[0] == c:
                    by_size[i[1]] = i[2]
            cartons = full_packs(by_size, ratio) // per_carton
            if cartons:
                full.append([[[c, s, ratio[s] * per_carton] for s in ratio], cartons])
            for i in items:
                if i[0] == c:
                    used = cartons * per_carton * ratio.get(i[1], 0)
                    if i[2] - used > 0:
                        pool.append([c, i[1], i[2] - used])
    elif pack_type == "Assorted":
        pool = items
    else:
        frappe.throw("Unknown pack type %s." % pack_type)
    rows = []
    n = int(start)
    for f in full:
        rows.append({"carton_from": n, "carton_to": n + f[1] - 1, "tail": 0, "pieces_per_carton": sum([c[2] for c in f[0]]), "contents": f[0]})
        n = n + f[1]
    tail_flag = 0 if pack_type == "Assorted" else 1
    for contents in tail_cartons(pool, (tail_rule or "Mixed Colour and Size") if pack_type != "Assorted" else "Mixed Colour and Size", cap):
        rows.append({"carton_from": n, "carton_to": n, "tail": tail_flag, "pieces_per_carton": sum([c[2] for c in contents]), "contents": contents})
        n = n + 1
    return rows


def size_summary(packed, ordered):
    """Lines 'colour size: packed / ordered (+x %)' and the total, like the company's OVERAGES / SHORTAGES rows."""
    lines = []
    tp = 0
    to = 0
    for key in sorted(set(packed) | set(ordered)):
        p = packed.get(key, 0)
        o = ordered.get(key, 0)
        tp = tp + p
        to = to + o
        pc = over_short_pct(p, o)
        lines.append("%s %s: %s / %s" % (key[0], key[1], int(p), int(o)) + ((" (%+.2f %%)" % pc) if pc is not None else ""))
    total = over_short_pct(tp, to)
    lines.append("Total: %s / %s" % (int(tp), int(to)) + ((" (%+.2f %%)" % total) if total is not None else ""))
    return ["\n".join(lines), total]


def packed_by_key(card, exclude, states, ship_to):
    """Pieces on other packing lists of the card by (colour, size). states: docstatus values to count."""
    cond = " and p.ship_to = %(ship_to)s" if ship_to else ""
    rows = frappe.db.sql(
        "select c.colour, c.size, sum(c.pieces_total) from `tabPacking List Content` c join `tabPacking List` p on p.name = c.parent "
        "where p.production_card = %(card)s and p.docstatus in %(states)s and p.name != %(exclude)s" + cond + " group by c.colour, c.size",
        {"card": card, "states": tuple(states), "exclude": exclude or "", "ship_to": ship_to})
    out = {}
    for r in rows:
        out[(r[0], r[1])] = r[2] or 0
    return out
