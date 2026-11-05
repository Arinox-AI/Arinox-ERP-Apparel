# API: arinox_close_production(production_card, reason): Production Manager closes a production card.
# Nothing may be left in draft, every challan must be returned or short-closed, and shipped must reach the lower tolerance.
u = frappe.utils
card_name = frappe.form_dict.get("production_card")
reason = (frappe.form_dict.get("reason") or "").strip()
roles = frappe.get_all("Has Role", {"parent": frappe.session.user, "parenttype": "User"}, pluck="role")
if "Apparel Production Manager" not in roles and "System Manager" not in roles:
    frappe.throw("Only a Production Manager can close production.")
card = frappe.get_doc("Production Card", card_name)
if card.docstatus != 1 or card.status in ("Closed", "Superseded", "Cancelled"):
    frappe.throw(f"Production card {card_name} is {card.status}.")

problems = []
for dt in ["Cut Plan", "Lay Report", "Recut Request", "Pilot Run", "Line Input", "Line QC Report", "Subcontract Challan",
           "Finishing Receipt", "Packing List", "Final Inspection", "Production Adjustment"]:
    n = frappe.db.count(dt, {"production_card": card_name, "docstatus": 0})
    if n:
        problems.append(f"{n} draft {dt}")
for r in frappe.get_all("Subcontract Challan", {"production_card": card_name, "docstatus": 1, "status": ["in", ["Open", "Partly Returned"]]}, ["name", "status"]):
    problems.append(f"challan {r.name} is {r.status}")
shipped = 0
for r in frappe.get_all("Production Movement", {"production_card": card_name, "stage": "SHIPPED"}, ["qty"]):
    shipped = shipped + u.flt(r.qty)
lower = 0
for l in card.lines:
    tol = 0
    for i in frappe.get_all("Sales Order Item", {"parent": card.sales_order, "apparel_colour": l.colour, "apparel_size": l.size}, ["apparel_qty_tolerance_pct"]):
        tol = u.flt(i.apparel_qty_tolerance_pct)
    lower = lower + u.flt(l.order_qty) * (1 - tol / 100.0)
if shipped + 0.5 < lower and not reason:
    problems.append(f"shipped {int(shipped)} is below the lower limit {int(lower)}; write the reason to close short")
if problems:
    frappe.throw("<br>".join(problems), title="Production cannot be closed yet")

frappe.db.set_value("Production Card", card_name, "status", "Closed")
card.add_comment("Comment", f"Production closed. Shipped {int(shipped)} of {int(lower)} minimum. {reason}")
frappe.flags.status = "Closed"   # an API Server Script returns frappe.flags
frappe.flags.shipped = shipped
frappe.flags.lower_limit = lower
