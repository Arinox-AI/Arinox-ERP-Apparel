import frappe
from frappe.utils import add_days, nowdate

from arinox_apparel.portable.hosted_tests import fixtures as fx
from arinox_apparel.portable.hosted_tests.harness import eq, test, throws, true


def submitted_cost_sheet(quoted_price=None, **kw):
	cs = fx.cost_sheet(quoted_price=quoted_price, **kw)
	cs.submit()
	return cs


def negotiation(cs, **kw):
	"""Through the Cost Sheet button, as a merchandiser would."""
	name = fx.engine_call("arinox_cost_sheet_make_price_negotiation", source_name=cs.name)["arinox_result"]
	return frappe.get_doc("Price Negotiation", name)


def quotation_of(cs_or_pn, button="arinox_cost_sheet_make_quotation"):
	d = fx.engine_call(button, source_name=cs_or_pn.name)["arinox_result"]
	d.pop("name", None)
	return frappe.get_doc(d)


@test("negotiation")
def negotiation_and_quotation_from_cost_sheet():
	cs = submitted_cost_sheet()
	pn = negotiation(cs)
	eq(len(pn.styles), 1)
	eq(pn.rounds[0].direction, "Our Offer")
	eq(pn.rounds[0].price, cs.quoted_price)
	eq(pn.status, "Open")
	q = fx.engine_call("arinox_cost_sheet_make_quotation", source_name=cs.name)["arinox_result"]
	eq(q["items"][0]["apparel_cost_sheet"], cs.name)
	eq(q["items"][0]["rate"], cs.quoted_price)
	eq(q["items"][0]["item_code"], "APPAREL-STYLE")
	# the same costing joins the open negotiation instead of starting another
	eq(negotiation(cs).name, pn.name)
	eq(len(frappe.get_doc("Price Negotiation", pn.name).styles), 1)


@test("negotiation")
def only_a_submitted_costing_can_be_negotiated_or_quoted():
	cs = fx.cost_sheet()
	true(throws(lambda: fx.engine_call("arinox_cost_sheet_make_price_negotiation", source_name=cs.name), "Submit the Cost Sheet"))
	true(throws(lambda: fx.engine_call("arinox_cost_sheet_make_quotation", source_name=cs.name), "Submit the Cost Sheet"))


@test("negotiation")
def rounds_carry_the_margin_and_the_floor_flag_and_the_status_follows_the_styles():
	cs = submitted_cost_sheet()
	pn = negotiation(cs)
	pn.append("rounds", {"cost_sheet": cs.name, "direction": "Buyer Counter", "price": 12.0})
	pn.append("rounds", {"cost_sheet": cs.name, "direction": "Our Counter", "price": 13.9})
	pn.save()
	low = pn.rounds[1]
	eq(low.below_floor, 1)
	true(low.margin_pct < 10, "margin below the 10% floor")
	eq(pn.rounds[2].below_floor, 0)
	eq((pn.styles[0].buyer_last_offer, pn.styles[0].our_last_offer, pn.styles[0].style_status), (12.0, 13.9, "Open"))
	eq((pn.rounds[0].style_no, pn.rounds[1].recorded_by), (cs.style_no, frappe.session.user))
	pn.append("rounds", {"cost_sheet": cs.name, "direction": "Agreed", "price": 13.9, "qty": 1200})
	pn.save()
	eq((pn.status, pn.styles[0].agreed_price, pn.styles[0].style_status, pn.styles[0].qty), ("Agreed", 13.9, "Agreed", 1200))
	eq((pn.total_qty, pn.total_value), (1200, 16680))                 # 1200 pcs x 13.9, shown on the header
	true(pn.styles[0].margin_at_agreed >= 10, "agreed above the floor")


@test("negotiation")
def partly_agreed_dropped_and_manual_status():
	a = submitted_cost_sheet()
	b = submitted_cost_sheet(style_no="HT-COST-2")
	pn = negotiation(a)
	pn.append("rounds", {"cost_sheet": b.name, "direction": "Our Offer", "price": 14.0})
	pn.append("rounds", {"cost_sheet": a.name, "direction": "Agreed", "price": 14.0})
	pn.save()
	eq((len(pn.styles), pn.status), (2, "Partly Agreed"))
	pn.append("rounds", {"cost_sheet": b.name, "direction": "Dropped"})            # no price needed to drop a style
	pn.save()
	eq((pn.status, pn.styles[1].style_status), ("Agreed", "Dropped"))
	pn.status = "On Hold"
	pn.save()
	eq(pn.status, "On Hold")                                                     # a manual status is kept


@test("negotiation")
def a_round_must_match_the_customer_currency_and_a_live_costing_and_have_a_price():
	cs = submitted_cost_sheet()
	pn = negotiation(cs)
	pn.append("rounds", {"cost_sheet": cs.name, "direction": "Buyer Target"})
	true(throws(lambda: pn.save(), "enter the price"))
	pn = frappe.get_doc("Price Negotiation", pn.name)
	pn.currency = "EUR"
	true(throws(lambda: pn.save(), "not EUR"))
	pn = frappe.get_doc("Price Negotiation", pn.name)
	pn.customer = fx.customer("HT Buyer 2")
	true(throws(lambda: pn.save(), "another customer"))
	cs2 = submitted_cost_sheet(style_no="HT-COST-3")
	pn = frappe.get_doc("Price Negotiation", pn.name)
	cs2.reload()
	cs2.cancel()
	pn.append("rounds", {"cost_sheet": cs2.name, "direction": "Our Offer", "price": 14})
	true(throws(lambda: pn.save(), "cancelled"))


@test("negotiation")
def make_quotation_takes_the_agreed_price_and_skips_dropped_styles():
	a = submitted_cost_sheet()
	b = submitted_cost_sheet(style_no="HT-COST-2")
	pn = negotiation(a)
	pn.append("rounds", {"cost_sheet": b.name, "direction": "Our Offer", "price": 15.0, "qty": 50})
	pn.append("rounds", {"cost_sheet": a.name, "direction": "Agreed", "price": 13.9, "qty": 1200})
	pn.save()
	rows = fx.engine_call("arinox_price_negotiation_make_quotation", source_name=pn.name)["arinox_result"]["items"]
	eq([(r["apparel_cost_sheet"], r["rate"], r["qty"]) for r in rows], [(a.name, 13.9, 1200), (b.name, 15.0, 50)])
	pn.append("rounds", {"cost_sheet": b.name, "direction": "Dropped"})
	pn.save()
	rows = fx.engine_call("arinox_price_negotiation_make_quotation", source_name=pn.name)["arinox_result"]["items"]
	eq([r["apparel_cost_sheet"] for r in rows], [a.name])
	pn.append("rounds", {"cost_sheet": a.name, "direction": "Dropped"})
	pn.save()
	true(throws(lambda: fx.engine_call("arinox_price_negotiation_make_quotation", source_name=pn.name), "No live styles"))


@test("negotiation")
def submitting_the_quotation_logs_a_round():
	cs = submitted_cost_sheet()
	pn = negotiation(cs)
	pn.append("rounds", {"cost_sheet": cs.name, "direction": "Agreed", "price": 13.9, "qty": 1200})
	pn.save()
	q = quotation_of(pn, "arinox_price_negotiation_make_quotation")
	q.insert()
	eq(q.apparel_price_negotiation, pn.name)
	q.submit()
	pn.reload()
	last = pn.rounds[-1]
	eq((last.quotation, last.direction, last.price, last.qty), (q.name, "Our Offer", 13.9, 1200))
	eq(pn.quotation, q.name)


@test("negotiation")
def a_quotation_below_the_margin_floor_is_blocked_until_the_costing_is_approved():
	cs = submitted_cost_sheet()
	q = quotation_of(cs)
	q.items[0].rate = 12.0
	true(throws(lambda: q.insert(), "below the floor"))
	q.items[0].rate = 14.0
	q.insert()                                                                  # the same line above the floor is fine
	eq((q.items[0].apparel_style_no, q.items[0].apparel_style_item), (cs.style_no, cs.style_item))
	# a costing approved at a low price lets a quotation at or above that price through
	low = fx.cost_sheet(quoted_price=12.80, style_no="HT-COST-LOW")
	eq(low.approval_status, "Pending")
	low.submit()                                                                # Administrator approves at submit
	eq(frappe.db.get_value("Cost Sheet", low.name, "approval_status"), "Approved")
	q2 = quotation_of(low)
	q2.insert()
	q2.items[0].rate = 12.5
	true(throws(lambda: q2.save(), "below the floor"))


@test("negotiation")
def a_quotation_line_must_match_its_costing():
	cs = submitted_cost_sheet()
	q = quotation_of(cs)
	q.party_name = fx.customer("HT Buyer 2")
	true(throws(lambda: q.insert(), "belongs to"))
	q = quotation_of(cs)
	q.currency = "EUR"
	true(throws(lambda: q.insert(), "is in USD"))
	draft = fx.cost_sheet(style_no="HT-COST-DRAFT")
	q = quotation_of(cs)
	q.items[0].apparel_cost_sheet = draft.name
	true(throws(lambda: q.insert(), "not submitted"))
