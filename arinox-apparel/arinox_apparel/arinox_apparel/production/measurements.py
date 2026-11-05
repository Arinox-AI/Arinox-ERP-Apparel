"""Garment measurement checks shared by the pilot run and later inspections. Same rule as Phase B's Sample Approval:
up to five readings per point, in tolerance only when every reading is."""

from frappe.utils import cint, flt


def compute(rows):
	for m in rows:
		readings = [flt(v) for v in (m.actual, m.reading_2, m.reading_3, m.reading_4, m.reading_5) if v not in (None, "")]
		if not readings or m.spec is None:
			m.deviation, m.in_tolerance = 0, 0
			continue
		devs = [round(r - flt(m.spec), 3) for r in readings]
		m.deviation = max(devs, key=abs)
		lo, hi = -abs(flt(m.tol_minus)), abs(flt(m.tol_plus))
		m.in_tolerance = 1 if all(lo <= d <= hi for d in devs) else 0
