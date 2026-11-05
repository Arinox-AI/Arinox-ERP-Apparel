"""Carton planning and the packing-list checks that need no database (plan sections 6 and 10.2).

A plan is a list of carton rows. Each row is a run of identical cartons (`carton_from` to `carton_to`) with its
contents, or one mixed tail carton. Numbers run on from `start` with no gap and no overlap."""

import math

from frappe import _
import frappe

from arinox_apparel.production import maths


def _tail_cartons(pool, rule, capacity):
	"""Fill the leftover pieces into cartons of `capacity` pieces by the tail rule. Pool items are (colour, size, qty)."""
	out = []
	if rule == "Own Carton":
		for c, s, q in pool:
			out.append([(c, s, q)])
		return out
	groups = [pool]
	if rule == "Mixed Size Only":
		by = {}
		for c, s, q in pool:
			by.setdefault(c, []).append((c, s, q))
		groups = list(by.values())
	for group in groups:
		cur, room = [], capacity
		for c, s, q in group:
			while q > 0:
				take = min(q, room)
				cur.append((c, s, take))
				q -= take
				room -= take
				if room == 0:
					out.append(cur)
					cur, room = [], capacity
		if cur:
			out.append(cur)
	return out


def plan_cartons(qty, pack_type, pcs_per_carton, ratio=None, tail_rule="Mixed Colour and Size", start=1):
	"""qty: {(colour, size): pieces} in the order they should be packed. ratio: {size: pieces per pack}.
	Returns a list of rows: {carton_from, carton_to, tail, pieces_per_carton, contents: [(colour, size, qty_per_carton)]}."""
	cap = int(pcs_per_carton or 0)
	if cap <= 0:
		raise ValueError(_("Pieces per carton must be above zero."))
	full, pool = [], []   # full: (contents, number of cartons)
	items = [(k[0], k[1], int(v)) for k, v in qty.items() if int(v) > 0]
	if pack_type == "Solid Colour Solid Size":
		for c, s, q in items:
			n, rem = divmod(q, cap)
			if n:
				full.append(([(c, s, cap)], n))
			if rem:
				pool.append((c, s, rem))
	elif pack_type == "Solid Colour Assorted Size":
		ratio = {s: int(r) for s, r in (ratio or {}).items() if int(r)}
		if not ratio:
			raise ValueError(_("Enter the ratio for assorted packs."))
		pack = sum(ratio.values())
		if cap % pack:
			raise ValueError(_("Pieces per carton ({0}) must be a multiple of the pack size ({1}).").format(cap, pack))
		per_carton = cap // pack
		colours = []
		for c, _s, _q in items:
			if c not in colours:
				colours.append(c)
		for c in colours:
			by_size = {s: q for cc, s, q in items if cc == c}
			cartons = maths.full_packs(by_size, ratio) // per_carton
			if cartons:
				full.append(([(c, s, r * per_carton) for s, r in ratio.items()], cartons))
			for cc, s, q in items:
				if cc == c:
					used = cartons * per_carton * ratio.get(s, 0)
					if q - used > 0:
						pool.append((c, s, q - used))
	elif pack_type == "Assorted":
		pool = items
	else:
		raise ValueError(_("Unknown pack type {0}.").format(pack_type))
	rows, n = [], int(start)
	for contents, count in full:
		rows.append({"carton_from": n, "carton_to": n + count - 1, "tail": 0, "pieces_per_carton": sum(q for _c, _s, q in contents), "contents": contents})
		n += count
	tail_flag = 0 if pack_type == "Assorted" else 1
	for contents in _tail_cartons(pool, tail_rule if pack_type != "Assorted" else "Mixed Colour and Size", cap):
		rows.append({"carton_from": n, "carton_to": n, "tail": tail_flag, "pieces_per_carton": sum(q for _c, _s, q in contents), "contents": contents})
		n += 1
	return rows


def check_ranges(ranges):
	"""ranges: [(from, to)] in any order. Returns a list of problems: not contiguous from the first number, overlapping
	or out of order. A sheet that lists 103~124 then 124~127 fails on carton 124."""
	problems = []
	rows = sorted((int(a), int(b)) for a, b in ranges)
	for a, b in rows:
		if b < a:
			problems.append(_("Carton range {0}~{1} ends before it starts.").format(a, b))
	for (a1, b1), (a2, b2) in zip(rows, rows[1:]):
		if a2 <= b1:
			problems.append(_("Carton {0} is in two rows ({1}~{2} and {3}~{4}).").format(a2, a1, b1, a2, b2))
		elif a2 != b1 + 1:
			problems.append(_("Cartons {0} to {1} are missing between {2}~{3} and {4}~{5}.").format(b1 + 1, a2 - 1, a1, b1, a2, b2))
	return problems


def sscc_number(prefix, serial, extension="0"):
	"""18-digit SSCC: extension digit + company prefix + serial, padded to 17 digits, then the GS1 check digit."""
	prefix = str(prefix)
	room = 16 - len(prefix)
	if not prefix.isdigit() or not 7 <= len(prefix) <= 10:
		raise ValueError(_("The GS1 company prefix must be 7 to 10 digits."))
	if len(str(serial)) > room:
		raise ValueError(_("The SSCC serial {0} no longer fits after the prefix.").format(serial))
	body = f"{extension}{prefix}{str(serial).zfill(room)}"
	return body + str(maths.gs1_check_digit(body))


def size_summary(packed, ordered):
	"""Lines 'colour size: packed vs ordered (+x %)' and the total, like the company's OVERAGES / SHORTAGES rows.
	packed, ordered: {(colour, size): qty}. Returns (text, total_pct)."""
	lines, tp, to = [], 0, 0
	for key in sorted(set(packed) | set(ordered)):
		p, o = packed.get(key, 0), ordered.get(key, 0)
		tp, to = tp + p, to + o
		pct = maths.over_short_pct(p, o)
		lines.append(f"{key[0]} {key[1]}: {p} / {o}" + (f" ({pct:+.2f} %)" if pct is not None else ""))
	total = maths.over_short_pct(tp, to)
	lines.append(f"Total: {tp} / {to}" + (f" ({total:+.2f} %)" if total is not None else ""))
	return "\n".join(lines), total


def draw_cartons(cartons, how_many, seed):
	"""Pick `how_many` cartons at random from `cartons` = [(packing_list, carton_no, is_tail)], the same draw for the same
	seed. A tail carton is always included when the lot has one, because mixed cartons are where packing errors hide."""
	import random

	pool = sorted(cartons)
	how_many = min(int(how_many), len(pool))
	rng = random.Random(seed)
	picked = rng.sample(pool, how_many)
	tails = [c for c in pool if c[2]]
	if tails and how_many and not any(c[2] for c in picked):
		picked[-1] = rng.choice(tails)
	return sorted(picked)
