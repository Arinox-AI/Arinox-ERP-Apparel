import json

import frappe
from frappe.utils import add_days, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true


def floors():
	"""Two factories with two lines each (mirrors the app's make_floors)."""
	wh = frappe.db.get_value("Warehouse", {"company": fx.company(), "is_group": 0}, "name")
	out = {}
	for floor in ("HT Factory A", "HT Factory B"):
		if not frappe.db.exists("Plant Floor", floor):
			frappe.get_doc({"doctype": "Plant Floor", "floor_name": floor, "company": fx.company(), "warehouse": wh}).insert()
		out[floor] = []
		for n in (1, 2):
			ws = "%s Line %s" % (floor, n)
			if not frappe.db.exists("Workstation", ws):
				frappe.get_doc({"doctype": "Workstation", "workstation_name": ws, "plant_floor": floor, "production_capacity": 1}).insert()
			out[floor].append(ws)
	return out


def order(rows=None, tolerance=10, item_code=None, days=60):
	"""Navy 700 + Black 500, 10% band: the app's make_order quantities. `rows` = [(colour, size, qty, ship_to)] to override."""
	rows = rows or [("Navy", "S", 300, None), ("Navy", "M", 400, None), ("Black", "S", 500, None)]
	wh = frappe.db.get_value("Warehouse", {"company": fx.company(), "is_group": 0}, "name")
	items = [{"item_code": (item_code or {}).get(c) if isinstance(item_code, dict) else (item_code or fx.item()), "qty": q, "rate": 10, "delivery_date": add_days(nowdate(), days), "warehouse": wh, "apparel_colour": c, "apparel_size": s,
			  "apparel_ship_to": ship, "apparel_qty_tolerance_pct": tolerance,
			  "apparel_in_warehouse_date": add_days(nowdate(), 90)} for c, s, q, ship in rows]
	so = frappe.get_doc({"doctype": "Sales Order", "customer": fx.customer(), "company": fx.company(), "delivery_date": add_days(nowdate(), days), "items": items})
	so.insert()
	so.submit()
	return so


def lines(f, navy=700, black=500, **extra):
	fa, fb = list(f)
	pcd = add_days(nowdate(), 40)
	return [dict({"style_item": fx.item(), "colour": "Navy", "qty": navy, "factory": fa, "line": f[fa][0], "pcd": pcd}, **extra),
			{"style_item": fx.item(), "colour": "Black", "qty": black, "factory": fb, "line": f[fb][0], "pcd": pcd}]


def save(so, rows, **kw):
	return fx.engine_call("arinox_factory_allocation_save_allocation", sales_order=so.name, lines=json.dumps(rows, default=str), **kw)["arinox_result"]


@test("allocation")
def allocation_round_trip_and_status():
	f = floors()
	so = order()
	name = save(so, lines(f), agent_notes="Navy to A, Black to B")
	fa = frappe.get_doc("Factory Allocation", name)
	eq(name, "FA-" + so.name)
	eq(fa.status, "Planned")
	eq((fa.order_qty, fa.allocated_qty), (1200, 1200))
	eq(fa.planned_by, "AI Agent")
	eq((fa.customer, fa.company), (fx.customer(), fx.company()))
	true(all(r.ex_factory_date for r in fa.lines))
	# replacing with a partial plan flips the status, same record
	eq(save(so, lines(f, navy=300, black=100)), name)
	eq(frappe.get_doc("Factory Allocation", name).status, "Partly Planned")


@test("allocation")
def an_allocation_with_no_rows_is_unplanned():
	so = order()
	fa = frappe.get_doc({"doctype": "Factory Allocation", "sales_order": so.name}).insert()
	eq((fa.status, fa.allocated_qty, fa.order_qty), ("Unplanned", 0, 1200))


@test("allocation")
def allocation_over_order_plus_tolerance_is_rejected():
	f = floors()
	so = order()
	save(so, lines(f, navy=770))                                       # Navy 700 pcs has a 10% band: 770 is the cap
	true(throws(lambda: save(so, lines(f, navy=771)), "more than the order"))


@test("allocation")
def line_must_belong_to_the_factory():
	f = floors()
	bad = lines(f)
	bad[0]["line"] = f[list(f)[1]][0]
	true(throws(lambda: save(order(), bad), "does not belong to factory"))


@test("allocation")
def allocation_dates_must_be_in_order():
	f = floors()
	so = order()
	true(throws(lambda: save(so, lines(f, sewing_start=add_days(nowdate(), 30))), "is after"))                          # before the PCD
	true(throws(lambda: save(so, lines(f, sewing_start=add_days(nowdate(), 60), sewing_end=add_days(nowdate(), 50))), "is after"))


@test("allocation")
def allocation_needs_a_submitted_order_and_a_known_style_and_colour():
	f = floors()
	so = order()
	bad = lines(f)
	bad[0]["colour"] = "Purple"
	true(throws(lambda: save(so, bad), "is not on Sales Order"))
	bad = lines(f, navy=0)
	true(throws(lambda: save(so, bad), "above zero"))
	draft = frappe.get_doc({"doctype": "Sales Order", "customer": fx.customer(), "company": fx.company(), "delivery_date": add_days(nowdate(), 60),
							"items": [{"item_code": fx.item(), "qty": 5, "rate": 10, "delivery_date": add_days(nowdate(), 60),
									   "warehouse": frappe.db.get_value("Warehouse", {"company": fx.company(), "is_group": 0}, "name")}]}).insert()
	true(throws(lambda: save(draft, lines(f)), "must be submitted"))


@test("allocation")
def planning_context_has_what_the_agent_needs():
	f = floors()
	so = order()
	save(so, lines(f))
	ctx = fx.engine_call("arinox_factory_allocation_get_planning_context", sales_order=so.name)["arinox_result"]
	eq({o["colour"] for o in ctx["order_lines"]}, {"Navy", "Black"})
	fa = list(f)[0]
	true(fa in [x["name"] for x in ctx["factories"]])
	true(ctx["current_allocation"])
	true([x for x in ctx["factories"] if x["name"] == fa][0]["lines"])


@test("allocation")
def get_order_lines_gives_one_row_per_colour():
	so = order()
	rows = fx.engine_call("arinox_factory_allocation_get_lines_from_order", sales_order=so.name)["arinox_result"]
	eq(sorted((r["colour"], r["qty"]) for r in rows), [("Black", 500), ("Navy", 700)])


@test("allocation")
def allocation_can_be_split_by_ship_to():
	f = floors()
	fa, fb = list(f)
	so = order([("Navy", "S", 500, "DC1"), ("Navy", "M", 200, "DC2"), ("Black", "S", 500, None)])
	pcd = add_days(nowdate(), 40)

	def ship_lines(dc2=200):
		return [{"style_item": fx.item(), "colour": "Navy", "ship_to": "DC1", "qty": 500, "factory": fa, "line": f[fa][0], "pcd": pcd},
				{"style_item": fx.item(), "colour": "Navy", "ship_to": "DC2", "qty": dc2, "factory": fa, "line": f[fa][1], "pcd": pcd},
				{"style_item": fx.item(), "colour": "Black", "qty": 500, "factory": fb, "line": f[fb][0], "pcd": pcd}]

	doc = frappe.get_doc("Factory Allocation", save(so, ship_lines()))
	eq(doc.status, "Planned")
	eq([(r.ship_to, r.order_qty) for r in doc.lines], [("DC1", 500), ("DC2", 200), (None, 500)])
	true(throws(lambda: save(so, ship_lines(dc2=221)), "more than the order"))                    # DC2 order is 200 + 10%: 220
	bad = ship_lines()
	bad[0]["ship_to"] = "DC9"
	true(throws(lambda: save(so, bad), "no order line for ship-to"))
