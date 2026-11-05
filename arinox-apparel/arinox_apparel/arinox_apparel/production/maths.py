"""Pure production maths. No database access, so every function is tested directly with the numbers
from the company's own sheets (see doctypes/PHASE_D_PRODUCTION_PLAN.md section 12)."""

import math
from datetime import timedelta

YARD_M = 0.9144


def planned_cut(order_qty, extra_pct):
	"""Cut quantity for one colour x size: order quantity plus the extra cut, rounded UP to whole pieces.
	The reference card shows fractions (163.8); a garment count is never fractional."""
	order_qty = float(order_qty or 0)
	if order_qty <= 0:
		return 0
	return int(math.ceil(round(order_qty * (1 + float(extra_pct or 0) / 100.0), 6)))


def max_ship_qty(order_qty, tolerance_pct):
	"""Largest shipment the contract tolerance allows (floor: never ship above the band)."""
	return int(math.floor(round(float(order_qty or 0) * (1 + float(tolerance_pct or 0) / 100.0), 6)))


def required_fabric(cut_qty, consumption):
	return round(float(cut_qty or 0) * float(consumption or 0), 6)


def ratio(numerator, denominator):
	"""Safe division; None when the denominator is zero so a report shows a blank, not an error."""
	denominator = float(denominator or 0)
	if not denominator:
		return None
	return float(numerator or 0) / denominator


def pct(numerator, denominator):
	r = ratio(numerator, denominator)
	return None if r is None else r * 100.0


def lay_consumption(laid_m, pieces_cut):
	"""Fabric laid per garment cut: sum(marker length x plies) / pieces cut."""
	return ratio(laid_m, pieces_cut)


def actual_consumption(issued_m, returned_m, good_cut):
	"""Fabric actually drawn from the store per good garment cut, end bits and waste included."""
	return ratio(float(issued_m or 0) - float(returned_m or 0), good_cut)


def weighted_marker_efficiency(rows):
	"""rows: iterable of (efficiency_pct, plies). Weighted by plies."""
	total = sum(p for _e, p in rows)
	if not total:
		return None
	return sum(e * p for e, p in rows) / total


# ---- sewing ------------------------------------------------------------------------------------------------------------

def day_target(operators, working_minutes, efficiency_pct, total_sam):
	"""Garments per day = operators x working minutes x efficiency / SAM.
	(The company's OB sheet agrees with this; its PCS/HR column wrongly divides by 9.5 hours.)"""
	if not total_sam:
		return 0.0
	return float(operators) * float(working_minutes) * (float(efficiency_pct) / 100.0) / float(total_sam)


def hour_target(operators, working_minutes, efficiency_pct, total_sam):
	if not working_minutes:
		return 0.0
	return day_target(operators, working_minutes, efficiency_pct, total_sam) / (float(working_minutes) / 60.0)


def pcs_per_machine_per_day(working_minutes, efficiency_pct, total_sam):
	if not total_sam:
		return 0.0
	return float(working_minutes) * (float(efficiency_pct) / 100.0) / float(total_sam)


def operation_target_per_hour(sam, efficiency_pct):
	"""Pieces per hour one operator can do on an operation of `sam` minutes."""
	if not sam:
		return 0.0
	return 60.0 * (float(efficiency_pct) / 100.0) / float(sam)


def efficiency_pct(produced_minutes, available_minutes):
	return pct(produced_minutes, available_minutes)


def learning_factor(day_no, curve):
	"""curve: list of (day_no, pct_of_target). Day beyond the table uses the last row; no table = 100 %."""
	rows = sorted((int(d), float(p)) for d, p in curve or [])
	if not rows:
		return 1.0
	chosen = rows[0][1]
	for d, p in rows:
		if day_no >= d:
			chosen = p
	return chosen / 100.0


def dhu(defects, checked):
	return pct(defects, checked)


def rft(passed_first_time, total):
	return pct(passed_first_time, total)


def traffic_colour(defects, rules):
	"""rules: list of (colour, defects_from). The highest threshold reached wins; below all = Green."""
	chosen = "Green"
	best = -1
	for colour, frm in rules or []:
		if defects >= int(frm) and int(frm) > best:
			chosen, best = colour, int(frm)
	return chosen


# ---- subcontracting ----------------------------------------------------------------------------------------------------

def penalty(sent, reject_vendor, threshold_pct, unit_value, scope="All Damaged"):
	"""Penalty for vendor-damaged pieces. Returns (reject_pct, penalised_qty, amount).
	Applies only when the vendor-fault rate is ABOVE the threshold."""
	rate = pct(reject_vendor, sent)
	if rate is None or rate <= float(threshold_pct):
		return rate, 0, 0.0
	if scope == "Excess Only":
		qty = max(0, int(reject_vendor) - int(math.floor(float(sent) * float(threshold_pct) / 100.0 + 1e-9)))
	else:
		qty = int(reject_vendor)
	return rate, qty, qty * float(unit_value or 0)


def add_working_days(start, days, holidays=(), skip_sunday=True):
	"""Date `days` working days after `start` (the day of receipt is day 0). Sundays and `holidays` are skipped."""
	holidays = set(holidays)
	d = start
	left = int(days)
	while left > 0:
		d = d + timedelta(days=1)
		if (skip_sunday and d.weekday() == 6) or d in holidays:
			continue
		left -= 1
	return d


# ---- packing -----------------------------------------------------------------------------------------------------------

def carton_cbm(length_cm, width_cm, height_cm):
	return float(length_cm) * float(width_cm) * float(height_cm) / 1_000_000.0


def cartons_needed(qty, pcs_per_carton):
	if not pcs_per_carton:
		return 0
	return int(math.ceil(float(qty) / float(pcs_per_carton)))


def full_packs(qty_by_size, ratio_by_size):
	"""Complete ratio packs available: min over sizes of floor(qty / ratio)."""
	packs = None
	for size, r in ratio_by_size.items():
		if not r:
			continue
		n = int(math.floor(float(qty_by_size.get(size, 0)) / float(r)))
		packs = n if packs is None else min(packs, n)
	return packs or 0


def inspect_cartons(total_cartons, rule="Square Root", fixed_pct=10):
	if total_cartons <= 0:
		return 0
	if rule == "Fixed Pct":
		return max(1, int(math.ceil(total_cartons * float(fixed_pct) / 100.0)))
	return int(math.ceil(math.sqrt(total_cartons)))


def over_short_pct(shipped, ordered):
	return pct(float(shipped) - float(ordered), ordered)


def gs1_check_digit(body):
	"""GS1 mod-10 check digit for a numeric body (GTIN-12/13/14 body or the 17-digit SSCC body)."""
	digits = [int(c) for c in str(body)]
	total = 0
	for i, d in enumerate(reversed(digits)):
		total += d * (3 if i % 2 == 0 else 1)
	return (10 - total % 10) % 10


def valid_gs1(code):
	code = str(code or "")
	if not code.isdigit() or len(code) < 8:
		return False
	return gs1_check_digit(code[:-1]) == int(code[-1])
