# shared helpers: the AQL row for a lot size, and the seeded carton draw (production/packing.draw_cartons, without `random`)
def aql_row(plan, lot_size):
    """The plan row whose lot range holds `lot_size`, or None."""
    for r in frappe.get_all("AQL Plan Row", {"parent": plan}, ["lot_from", "lot_to", "code_letter", "sample_size", "critical_ac", "critical_re", "major_ac", "major_re", "minor_ac", "minor_re", "confirmed"], order_by="lot_from"):
        if frappe.utils.cint(r.lot_from) <= lot_size and lot_size <= frappe.utils.cint(r.lot_to):
            return r
    return None


def next_random(state):
    """One step of a linear congruential generator (31 bits). The same seed always gives the same draw."""
    return (state * 1103515245 + 12345) % 2147483648


def draw_cartons(cartons, how_many, seed):
    """Pick `how_many` of `cartons` = [[packing_list, carton_no, is_tail]] without repeats, the same draw for the same seed. A tail carton is
    always included when the lot has one, because mixed cartons are where packing errors hide."""
    pool = sorted(cartons)
    how_many = min(int(how_many), len(pool))
    state = int(seed) % 2147483648
    bag = list(pool)
    picked = []
    while len(picked) < how_many:
        state = next_random(state)
        picked.append(bag.pop((state // 65536) % len(bag)))
    tails = [c for c in pool if c[2]]
    if tails and how_many:
        has_tail = False
        for c in picked:
            if c[2]:
                has_tail = True
        if not has_tail:
            state = next_random(state)
            picked[-1] = tails[(state // 65536) % len(tails)]
    return sorted(picked)
