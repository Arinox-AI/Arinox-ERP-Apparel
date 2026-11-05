"""Sewing helpers: the active operation bulletin of a style, the learning-curve day on a line, and the import of the
company's OB workbook layout. Rules are data (Apparel Settings); no buyer or line is named here."""

import re

import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, getdate

from arinox_apparel.production import maths


def settings_value(field, default=None):
	v = frappe.db.get_single_value("Apparel Settings", field)
	return default if v in (None, "") else v


def active_ob(style_item):
	"""The Operation Bulletin in force for a style (newest Active one), or None."""
	rows = frappe.get_all("Operation Bulletin", {"style_item": style_item, "status": "Active"},
						  ["name", "total_sam", "operators", "working_minutes", "expected_efficiency_pct"], order_by="version desc, creation desc", limit=1)
	return rows[0] if rows else None


def learning_day(line, style_item, on_date):
	"""Day number of a style on a line, counted from its first Line Input there (1 on the first day)."""
	first = frappe.db.sql(
		"""select min(i.input_date) from `tabLine Input` i join `tabProduction Card` c on c.name = i.production_card
		where i.docstatus = 1 and i.line = %s and c.style_item = %s""", (line, style_item))[0][0]
	if not first:
		return 1
	return max(date_diff(getdate(on_date), getdate(first)) + 1, 1)


def curve():
	return [(r.day_no, r.pct_of_target) for r in frappe.get_all("Learning Curve Day", {"parent": "Apparel Settings", "parentfield": "learning_curve"}, ["day_no", "pct_of_target"])]


# ---- importing the OB workbook ------------------------------------------------------------------------------------------

def _num(v):
	try:
		return float(v)
	except (TypeError, ValueError):
		return None


def parse_ob_rows(rows):
	"""Rows of cells (lists) from one OB sheet -> {'header': {...}, 'operations': [...]}. Quirks of the sheets handled: header
	label/value pairs sit side by side; group headings (COLLAR, CUFF) are rows with no times; a part name can repeat; an
	operation number can be missing; the target and labour columns are ignored (they are recomputed)."""
	header, ops, cols = {}, [], None
	group = None
	for row in rows:
		cells = [("" if c is None else str(c).strip()) for c in row]
		upper = [c.upper() for c in cells]
		if cols is None:
			for i, c in enumerate(upper):
				if c.startswith("NO.OF WORKERS") or c.startswith("NO. OF WORKERS"):
					header["operators"] = next((cint(_num(x)) for x in cells[i + 1:] if _num(x)), None)
				elif c.startswith("WORKING TIME"):
					header["working_minutes"] = next((cint(_num(x)) for x in cells[i + 1:] if _num(x)), None)
				elif c.startswith("EXPECTED EFFICIENCY"):
					v = next((_num(x) for x in cells[i + 1:] if _num(x) is not None), None)
					header["expected_efficiency_pct"] = (v * 100 if v is not None and v <= 1 else v)
				elif c in ("BUYER", "BUYER 客户") or c.startswith("BUYER"):
					header["buyer_name"] = next((x for x in cells[i + 1:] if x), None)
				elif c.startswith("DESCRIPTION") and "PARTS" not in c:
					header["description"] = next((x for x in cells[i + 1:] if x), None)
				elif c.startswith("COLOUR") or c.startswith("COLOR"):
					header["colour"] = next((x for x in cells[i + 1:] if x), None)
			if any(c.startswith("OPRN") for c in upper):
				cols = {}
				for i, c in enumerate(upper):
					if c.startswith("OPRN"):
						cols["seq"] = i
					elif c.startswith("PARTS") or c == "DESCRIPTION":
						cols["op"] = i
					elif c.startswith("M/C SM") or c.startswith("MC SM"):
						cols["mc"] = i
					elif c.startswith("MANUAL"):
						cols["manual"] = i
					elif c.startswith("M/C TYPE") or c.startswith("MC TYPE"):
						cols["type"] = i
			continue
		if not any(cells):
			continue
		first = next((c for c in upper if c), "")
		if first.startswith("TOTAL"):
			nums = [_num(c) for c in cells[1:] if _num(c) is not None]
			header["sheet_machine_total"] = nums[0] if nums else None
			header["sheet_manual_total"] = nums[1] if len(nums) > 1 else None
			break
		name = cells[cols["op"]] if cols.get("op") is not None and cols["op"] < len(cells) else ""
		mc = _num(cells[cols["mc"]]) if cols.get("mc") is not None and cols["mc"] < len(cells) else None
		manual = _num(cells[cols["manual"]]) if cols.get("manual") is not None and cols["manual"] < len(cells) else None
		if not name:
			continue
		if not mc and not manual:
			group = name
			continue
		seq_cell = cells[cols["seq"]] if cols.get("seq") is not None and cols["seq"] < len(cells) else ""
		ops.append({
			"seq": cint(_num(seq_cell)) if _num(seq_cell) else len(ops) + 1, "part_group": group, "operation": name,
			"machine_sam": mc or 0, "manual_sam": manual or 0,
			"machine_type": cells[cols["type"]] if cols.get("type") is not None and cols["type"] < len(cells) else None,
		})
	return {"header": header, "operations": ops}


@frappe.whitelist()
def import_ob_workbook(style_item, file_url, sheet=None):
	"""Make a DRAFT Operation Bulletin from an uploaded OB workbook (one sheet per style)."""
	import openpyxl

	if not frappe.has_permission("Operation Bulletin", "create"):
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	f = frappe.get_doc("File", {"file_url": file_url})
	wb = openpyxl.load_workbook(f.get_full_path(), data_only=True, read_only=True)
	ws = wb[sheet] if sheet else wb.worksheets[0]
	parsed = parse_ob_rows([list(r) for r in ws.iter_rows(values_only=True)])
	if not parsed["operations"]:
		frappe.throw(_("No operations found. Check that the sheet has an OPRN NUM header row."))
	h = parsed["header"]
	mc, mn = sum(o["machine_sam"] for o in parsed["operations"]), sum(o["manual_sam"] for o in parsed["operations"])
	if h.get("sheet_machine_total") is not None and (abs(mc - h["sheet_machine_total"]) > 0.05 or abs(mn - (h.get("sheet_manual_total") or 0)) > 0.05):
		frappe.msgprint(_("The operation rows add up to {0} + {1} minutes but the sheet's TOTAL row says {2} + {3}. Check for repeated or missing rows.").format(
			round(mc, 2), round(mn, 2), h["sheet_machine_total"], h.get("sheet_manual_total")), indicator="orange", title=_("Operation Bulletin"))
	doc = frappe.get_doc({
		"doctype": "Operation Bulletin", "style_item": style_item, "operators": h.get("operators") or 1,
		"working_minutes": h.get("working_minutes") or cint(settings_value("work_minutes_per_day", 480)),
		"expected_efficiency_pct": h.get("expected_efficiency_pct") or flt(settings_value("planned_efficiency_pct", 65)),
		"description": h.get("description"), "colour": h.get("colour"), "source_file": file_url, "operations": parsed["operations"]})
	doc.insert()
	return doc.name
