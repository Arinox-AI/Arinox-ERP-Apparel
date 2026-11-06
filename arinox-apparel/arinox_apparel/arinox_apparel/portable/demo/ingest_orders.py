"""Ingest two real orders from the sample documents (S84 for PO 69785, S14 for POs 70599/70601/70602) into a site that has
the bundle loaded but NOT the app, to see whether the data model covers the real papers.

Run on the ERPNext-only test site (the console, so the app need not be installed there):

    printf 'from arinox_apparel.portable.demo import ingest_orders as i\\ni.run("<unzipped ARINOX ERP DOCS folder>")\\n' | bench --site hosted.localhost console

Every value that has no field on the target doctype is recorded in GAPS (and dropped) instead of vanishing silently. Every record that
the site refuses is recorded in FAILS with the server's message. `report()` prints both. The papers contain bank and account
numbers; nothing of that kind is read here."""

import glob
import os
import re
import warnings

import frappe
from frappe.utils import add_days, getdate

warnings.filterwarnings("ignore")

GAPS = []     # (doctype, field, value, why)
FAILS = []    # (doctype, name or key, message)
OBS = []      # things the system did on the real data that are worth knowing (a gate firing, a number that differs)
MADE = []     # (doctype, name)
FACTORY = "Cortex Vietnam Garment Limited"
TRADER = "Cortex Fashion (HK) Limited"
FABRIC_CO = "Cortex Textile FZ LLC"
BUYER = "EMJ APPAREL GROUP, LLC"
STD = {"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx", "doctype", "parent", "parenttype", "parentfield"}
SIZES = ["XXS", "XS", "S", "M", "L", "XL", "XXL"]
RATE = {FACTORY: 25000.0, TRADER: 7.8, FABRIC_CO: 3.6725}      # VND, HKD, AED per USD (the costing sheet uses 25,000 VND per USD)
FORWARDER = "BEE LOGISTICS CORPORATION - DANANG BRANCH"


# ---- the one place a record is made -------------------------------------------------------------------------------------

def put(doctype, data, submit=False, key=None):
	"""Insert `data`. Fields the doctype does not have are recorded in GAPS and dropped; a refusal is recorded in FAILS."""
	meta = frappe.get_meta(doctype)
	have = {f.fieldname: f for f in meta.fields} | {k: None for k in STD}
	clean = {}
	for k, v in data.items():
		if k not in have:
			GAPS.append((doctype, k, v, "no such field"))
			continue
		f = have[k]
		if f is not None and f.fieldtype in ("Table", "Table MultiSelect") and isinstance(v, list):
			rows = []
			child_meta = frappe.get_meta(f.options)
			child_have = {c.fieldname for c in child_meta.fields} | STD
			for row in v:
				good = {}
				for ck, cv in row.items():
					if ck not in child_have:
						GAPS.append((f.options, ck, cv, "no such field"))
					else:
						good[ck] = cv
				rows.append(good)
			clean[k] = rows
		else:
			clean[k] = v
	clean["doctype"] = doctype
	try:
		doc = frappe.get_doc(clean)
		doc.insert()
		if submit:
			doc.submit()
		MADE.append((doctype, doc.name))
		return doc
	except Exception as e:
		FAILS.append((doctype, key or data.get("name") or data.get("title") or data.get("customer_name") or "", str(e).replace("\n", " ")[:300]))
		frappe.db.rollback(save_point="put") if False else None
		return None


def gap(doctype, field, value, why):
	GAPS.append((doctype, field, value, why))


# ---- reading the papers --------------------------------------------------------------------------------------------------

def xl(path):
	import openpyxl

	return openpyxl.load_workbook(path, data_only=True)


def find(root, *patterns):
	for p in patterns:
		hits = sorted(glob.glob(os.path.join(root, p)))
		if hits:
			return hits[0]
	return None


def labelled(ws, rows=14, cols=18):
	"""Header block 'LABEL: value' pairs of a tech-pack grade sheet."""
	cells = [[c for c in r] for r in ws.iter_rows(min_row=1, max_row=rows, max_col=cols, values_only=True)]
	out = {}
	for r in cells:
		for i, c in enumerate(r):
			if isinstance(c, str) and c.strip().endswith(":"):
				nxt = next((x for x in r[i + 1:] if x not in (None, "")), None)
				if nxt is not None and not (isinstance(nxt, str) and nxt.strip().endswith(":")):
					out[c.strip().rstrip(":").upper()] = nxt
	return out


def grade(path):
	"""(header dict, size list, measurement rows) from a MEASUREMENT SPECIFICATION sheet. Reads the columns by their headings. A row with a name
	but no POM code is kept; a row with a name and no numbers (for example LINING) starts a new section; a date between the name and the
	tolerance marks the row as revised on that day."""
	import datetime

	ws = xl(path).worksheets[0]
	head = labelled(ws)
	hdr = None
	for i, r in enumerate(ws.iter_rows(min_row=1, max_row=40, values_only=True), 1):
		if r and str(r[0] or "").strip().upper() == "POM CODE":
			hdr = (i, r)
			break
	if not hdr:
		return head, [], []
	cols = {str(v).strip().upper(): j for j, v in enumerate(hdr[1]) if v not in (None, "")}
	size_cols = [(s_, cols[s_]) for s_ in SIZES if s_ in cols]
	name_col = next(j for k, j in cols.items() if k.startswith("POINT OF MEASURE"))
	tol_col = next(j for k, j in cols.items() if k.startswith("TOL"))
	rows, section = [], None
	for r in ws.iter_rows(min_row=hdr[0] + 1, max_row=ws.max_row, values_only=True):
		name = str(r[name_col] or "").strip()
		code = str(r[0] or "").strip()
		if not name:
			continue
		if code.upper() == "POM CODE":
			break
		nums = [r[j] for _, j in size_cols if isinstance(r[j], (int, float))]
		tol = r[tol_col] if isinstance(r[tol_col], (int, float)) else None
		if not nums and tol is None:
			section = name
			continue
		between = [r[j] for j in range(name_col + 1, tol_col)]
		rows.append({"pom": code, "name": name, "local": next((str(x).strip() for x in between if isinstance(x, str) and x.strip()), ""), "tol": tol,
					 "revised": next((x for x in between if isinstance(x, datetime.datetime)), None), "section": section,
					 "values": {s_: r[j] for s_, j in size_cols}})
	return head, [s_ for s_, _ in size_cols], rows


def bom(path):
	"""Rows of a buyer BOM report (STY360): fixed columns."""
	import xlrd

	ws = xlrd.open_workbook(path).sheet_by_index(0)
	style = colour = desc = None
	out = []
	for r in range(ws.nrows):
		def c(k):
			v = ws.cell_value(r, k) if k < ws.ncols else ""
			return str(v).strip()

		if c(1) == "Style:":
			style = c(5)
		if c(1) == "Color:":
			colour = c(5)
			desc = c(18)
		if c(1) and c(13) and c(7) and re.match(r"^[A-Z0-9]+$", c(1)) and c(33):
			try:
				out.append({"item": c(1), "colour_code": c(7), "size": c(10), "desc": c(13), "colour_desc": c(20), "job": c(27), "uom": c(31), "qty": float(c(33))})
			except ValueError:
				pass
	return style, colour, desc, out


def pdf_text(path):
	from pypdf import PdfReader

	return "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)


def packing(path):
	"""(header, carton runs, per-size ordered row, per-size shipped row) from a packing list sheet."""
	ws = xl(path).worksheets[0]
	rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=22, values_only=True))
	head = {}
	for r in rows[:12]:
		for j, v in enumerate(r):
			if isinstance(v, str) and v.strip().endswith(":"):
				nxt = next((x for x in r[j + 1:] if x not in (None, "") and not (isinstance(x, str) and x.strip().endswith(":"))), None)
				head[v.strip().rstrip(":").upper()] = nxt
	hdrs = [i for i, r in enumerate(rows) if [str(x).strip() for x in r[5:11]] == ["XXS", "XS", "S", "M", "L", "XL"]]
	size_row = hdrs[-1]                      # the summary header; the carton table has its own size header above it
	runs = []
	for r in rows[(hdrs[0] + 1 if len(hdrs) > 1 else 0):size_row]:
		if isinstance(r[1], str) and re.match(r"^\d+~\d+$", r[1].strip()):
			a, b = r[1].strip().split("~")
			per = {s: r[5 + k] for k, s in enumerate(["XXS", "XS", "S", "M", "L", "XL"]) if isinstance(r[5 + k], (int, float))}
			runs.append({"from": int(a), "to": int(b), "shade": r[2], "cartons": int(r[3] or 0), "colour": r[4], "per": per, "per_carton": r[11], "pieces": r[12],
						 "gw_each": r[13] if isinstance(r[13], (int, float)) else None, "cbm_each": r[14] if len(r) > 14 and isinstance(r[14], (int, float)) else None})
	ordered = shipped = None
	for r in rows[size_row:]:
		label = str(r[2] or r[4] or "").upper()
		vals = {s: r[5 + k] for k, s in enumerate(["XXS", "XS", "S", "M", "L", "XL"]) if isinstance(r[5 + k], (int, float))}
		if label.startswith("TOTAL ON PURCHAS"):
			ordered = vals
		if label.startswith("TOTAL UNITS SHIP"):
			shipped = vals
	return head, runs, ordered, shipped


# ---- masters -----------------------------------------------------------------------------------------------------------

def purge():
	"""Remove what an earlier run left, so a run starts clean (this site is only for testing)."""
	for dt in ("Sales Invoice", "Delivery Note", "Shipment", "Packing List", "Final Inspection", "Production Movement", "Production Adjustment", "Production Card",
			   "Trim Requisition", "Fabric Requisition", "Sales Order", "Sales Contract", "Cost Sheet", "Tech Pack"):
		for n in frappe.get_all(dt, pluck="name"):
			try:
				if frappe.db.get_value(dt, n, "docstatus") == 1:
					frappe.db.set_value(dt, n, "docstatus", 2, update_modified=False)    # a submitted document cannot be deleted; a cancelled one can
				frappe.delete_doc(dt, n, force=1, ignore_permissions=True)
			except Exception as e:
				FAILS.append(("purge " + dt, n, str(e)[:120]))
	frappe.db.commit()


def fiscal_years():
	"""The papers are dated 2025 and 2026; ERPNext refuses a document outside a fiscal year."""
	for y in (2025, 2026):
		if not frappe.db.exists("Fiscal Year", {"year_start_date": f"{y}-01-01"}):
			put("Fiscal Year", {"year": str(y), "year_start_date": f"{y}-01-01", "year_end_date": f"{y}-12-31"})
	frappe.db.commit()


def companies():
	spec = [(FACTORY, "CVN", "VND", "Vietnam", "CTXGVN"), (TRADER, "CHK", "HKD", "Hong Kong", None), (FABRIC_CO, "CTF", "AED", "United Arab Emirates", None)]
	for name, abbr, cur, country, prefix in spec:
		if frappe.db.exists("Company", name):
			continue
		if not frappe.db.exists("Country", country):
			gap("Company", "country", country, "country not in the ERPNext list")
			continue
		frappe.db.set_value("Currency", cur, "enabled", 1)
		put("Company", {"company_name": name, "abbr": abbr, "default_currency": cur, "country": country, "create_chart_of_accounts_based_on": "Standard Template",
						"chart_of_accounts": "Standard"})
	if frappe.db.exists("Company", FACTORY):
		frappe.db.set_value("Company", FACTORY, {"apparel_contract_prefix": "CTXGVN", "apparel_fr_prefix": "FR", "apparel_tr_prefix": "TR", "apparel_pc_prefix": "PC"})
	frappe.db.commit()


def group_of(doctype, field):
	f = frappe.get_meta(doctype).get_field(field)
	return (f.options or "").split("\n") if f else []


def parties():
	grp = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	terr = frappe.db.get_value("Territory", "United States", "name") or frappe.db.get_value("Territory", {"is_group": 0}, "name")
	basis = group_of("Customer", "apparel_transfer_basis")
	if not frappe.db.exists("Customer", BUYER):
		put("Customer", {"customer_name": BUYER, "customer_group": grp, "territory": terr, "default_currency": "USD", "apparel_invoice_via_company": TRADER,
						 "apparel_transfer_basis": next((b for b in basis if "Fixed" in b or "Price" in b), basis[0] if basis else None)})
	if not frappe.db.exists("Customer", TRADER):
		put("Customer", {"customer_name": TRADER, "customer_group": grp, "territory": terr, "is_internal_customer": 1, "represents_company": TRADER,
						 "companies": [{"company": FACTORY}], "default_currency": "USD"})
	if not frappe.db.exists("Supplier", FABRIC_CO):
		put("Supplier", {"supplier_name": FABRIC_CO, "supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"), "is_internal_supplier": 1,
						 "represents_company": FABRIC_CO, "companies": [{"company": FACTORY}]})
	if not frappe.db.exists("Supplier", FORWARDER):
		put("Supplier", {"supplier_name": FORWARDER, "supplier_group": frappe.db.get_value("Supplier Group", {"is_group": 0}, "name"), "supplier_type": "Company"})
	# group companies book in VND/HKD but invoice in USD: a USD receivable account per company, named on the customer
	for company, customer in ((FACTORY, TRADER), (TRADER, BUYER)):
		abbr = frappe.db.get_value("Company", company, "abbr")
		acct = f"Debtors USD - {abbr}"
		if not frappe.db.exists("Account", acct):
			parent = frappe.db.get_value("Account", {"company": company, "account_type": "Receivable", "is_group": 0}, "parent_account")
			put("Account", {"account_name": "Debtors USD", "company": company, "parent_account": parent, "account_type": "Receivable", "account_currency": "USD", "is_group": 0})
		cust = frappe.get_doc("Customer", customer)
		if not [a for a in cust.accounts if a.company == company]:
			cust.append("accounts", {"company": company, "account": acct})
			cust.save()
	frappe.db.set_single_value("Stock Settings", "over_delivery_receipt_allowance", 15)    # ERPNext's own guard must be no tighter than the largest contract tolerance
	frappe.db.commit()


def attribute_values(attr, values):
	doc = frappe.get_doc("Item Attribute", attr)
	have = {v.attribute_value.upper() for v in doc.item_attribute_values}
	for v, abbr in values:
		if v.upper() not in have:
			doc.append("item_attribute_values", {"attribute_value": v, "abbr": abbr})
	doc.save()


def style_item(code, name, colour, abbr, sizes):
	"""A template item with Colour and Size attributes and one variant per colour x size. Returns {size: variant code}."""
	attribute_values("Colour", [(colour, abbr)])
	attribute_values("Size", [(s, s) for s in SIZES])
	if not frappe.db.exists("Item", code):
		put("Item", {"item_code": code, "item_name": name, "item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"), "stock_uom": "Nos",
					 "is_stock_item": 1, "has_variants": 1, "variant_based_on": "Item Attribute", "valuation_rate": 5,
					 "attributes": [{"attribute": "Colour"}, {"attribute": "Size"}]})
	from erpnext.controllers.item_variant import create_variant

	out = {}
	for s in sizes:
		v = create_variant(code, {"Colour": colour, "Size": s})
		v.valuation_rate = 5
		if not frappe.db.exists("Item", v.item_code):
			try:
				v.insert()
			except Exception as e:
				FAILS.append(("Item", v.item_code, str(e)[:200]))
				continue
		out[s] = v.item_code
	frappe.db.commit()
	return out


# ---- one order -----------------------------------------------------------------------------------------------------------

STANDARD_SIZES = ["XXS", "XS", "S", "M", "L", "XL", "XXL"]
STANDARD_SIZES_LOWER = [x.lower() for x in STANDARD_SIZES]


def tech_pack(style_no, name, style_code, head, sizes, rows, colour, bom_rows, customer=BUYER, source=None):
	mats = []
	for b in bom_rows:
		kind = "Fabric" if re.match(r"^[A-Z]\d+$", b["item"]) or "FABRIC" in b["desc"].upper() or "%" in b["desc"] else "Label" if "LABEL" in b["desc"].upper() else "Trim"
		mats.append({"material_type": kind, "description": b["desc"], "buyer_item_code": b["item"], "colour": b["colour_desc"] or b["colour_code"], "consumption": b["qty"],
					 "uom": {"YD": "Yard", "EA": "Nos"}.get(b["uom"], "Nos"), "job_code": b["job"], "size_applicability": b["size"]})
	meas = []
	for r in rows:
		label = ("[" + r["section"] + "] " if r["section"] else "") + r["name"]
		if r["section"]:
			gap("Tech Pack Measurement", "section (e.g. LINING)", r["section"], "the same POM code is measured twice (shell and lining); there is no section field, so the section is carried inside the point-of-measure text")
		if r["revised"]:
			gap("Tech Pack Measurement", "row revised on", str(r["revised"])[:10], "the sheet dates the rows that changed; the measurement row has no revision date")
		if not r["pom"]:
			gap("Tech Pack Measurement", "pom_code is blank", r["name"], "accepted: rows with no POM code are kept (the code is not mandatory)")
		# one row per point of measure, one column per standard size (the Tech Pack measurement layout)
		m = {"point_of_measure": label, "tolerance": r["tol"]}
		if r["pom"]:
			m["pom_code"] = r["pom"]
		for s_ in sizes:
			v = r["values"].get(s_)
			if isinstance(v, (int, float)):
				if s_.upper() not in STANDARD_SIZES:
					gap("Tech Pack Measurement", "size column " + s_, str(v), "not one of the standard size columns XXS to XXL")
					continue
				m[s_.lower()] = v
		if any(k in m for k in STANDARD_SIZES_LOWER):
			meas.append(m)
	doc = {"customer": customer, "style_no": style_no, "style_name": name, "season": str(head.get("SEASON") or ""), "style_item": style_code,
		   "wash_code": str(head.get("WASH DESCRIPTION") or ""), "wash_description": str(head.get("WASH DESCRIPTION") or ""),
		   "fabric_content": str(head.get("FABRIC CONTENT") or ""), "division": str(head.get("DIVISION") or ""), "designer": str(head.get("DESIGNER") or ""),
		   "tech_designer": str(head.get("TECH DESIGNER") or ""), "factory": str(head.get("FACTORY") or ""), "sample_size": str(head.get("SAMPLE SIZE") or ""),
		   "fit_status": str(head.get("STATUS") or ""), "size_range": str(head.get("SIZE RANGE") or ""), "group_name": str(head.get("GROUP") or ""),
		   "sizes": [{"size": s, "ratio": 1, "is_base_size": 1 if s == "M" else 0} for s in sizes], "colours": [{"colour": colour}],
		   "measurements": meas, "materials": mats, "source": "Buyer Tech Pack" if False else None, "source_reference": source}
	for k in ("creation date", "revised date"):
		if head.get(k.upper()):
			gap("Tech Pack", k, head.get(k.upper()), "grade sheet carries a creation and a revised date; Tech Pack keeps only 'received on'")
	return put("Tech Pack", {k: v for k, v in doc.items() if v not in (None, "")}, key=style_no)


def make_contract(root, spec):
	"""Sales Contract from a spec dict (header, lines, sizes); sizes are the per-PO ordered quantities by size."""
	lines, sizes = [], []
	for ln in spec["lines"]:
		lines.append({"style_item": spec["style_code"], "style_no": spec["style_no"], "colour": spec["colour"], "qty": ln["qty"], "rate": ln["rate"],
					  "ex_factory_date": ln["xf"], "etd": ln["etd"], "in_warehouse_date": ln["inwh"], "pcd": ln.get("pcd"), "buyer_po_code": ln["po"],
					  "fabric_description": spec["fabric"], "description": spec["garment"], "finish": spec.get("finish"), "price_term": spec["price_term"]})
		for sz, q in ln["sizes"].items():
			if q:
				sizes.append({"style_item": spec["style_code"], "colour": spec["colour"], "size": sz, "qty": q, "ship_to": spec["ship_to"], "buyer_po_no": ln["po"]})
	body = {"customer": BUYER, "company": FACTORY, "currency": "USD", "contract_date": spec["date"], "buyer_po_no": spec["po_header"], "season": spec["season"],
			"brand": spec.get("brand"), "division": spec.get("division"), "buyer_contact": spec.get("buyer_contact"), "merchant": spec.get("merchant"),
			"incoterm": frappe.db.get_value("Incoterm", "DDP", "name") or frappe.db.get_value("Incoterm", {"name": ["like", "DDP%"]}, "name"),
			"shipment_mode": "Sea", "port_of_loading": spec.get("pol"), "port_of_discharge": spec.get("pod"), "country_of_origin": "Vietnam",
			"payment_basis": "Days after Receipt of Goods (ROG)", "payment_days": 15, "packing_instructions": spec.get("packing"), "shipping_marks": spec.get("marks"),
			"days_ex_factory_to_etd": 7, "transit_days": 30, "tolerance_bands": spec["bands"], "items": lines, "sizes": sizes,
			"shipping_marks": spec.get("marks"), "customer_address": spec.get("address_text")}
	if spec.get("legacy_no"):
		body["arinox_name"] = spec["legacy_no"]
	return put("Sales Contract", {k: v for k, v in body.items() if v not in (None, "")}, key=spec["style_no"])


def try_sign(sc, label):
	"""Sign the contract as the merchandiser would. A refusal is a finding about the rule, not a failure of the ingest."""
	if not sc:
		return
	try:
		sc.reload()
		sc.submit()
		OBS.append(("Sales Contract", sc.name, label + ": signed without complaint"))
	except Exception as e:
		OBS.append(("Sales Contract", sc.name, label + ": signing refused -> " + re.sub("<[^>]+>", " ", str(e).replace("\n", " "))[:260]))


def make_order(contract, spec, variants):
	"""Sales Order from the contract: one row per PO x size, the apparel_* fields filled from the contract line."""
	wh = frappe.db.get_value("Warehouse", {"company": FACTORY, "is_group": 0}, "name")
	rows = []
	for ln in spec["lines"]:
		for sz, q in ln["sizes"].items():
			if not q:
				continue
			rows.append({"item_code": variants[sz], "qty": q, "rate": ln["rate"], "delivery_date": ln["xf"], "warehouse": wh, "apparel_colour": spec["colour"], "apparel_size": sz,
						 "apparel_ship_to": spec["ship_to"], "apparel_buyer_po": ln["po"], "apparel_etd": ln["etd"], "apparel_in_warehouse_date": ln["inwh"],
						 "apparel_qty_tolerance_pct": ln["tol"]})
	so = put("Sales Order", {"customer": BUYER, "company": FACTORY, "currency": "USD", "po_no": spec["po_header"], "po_date": spec["date"], "transaction_date": spec["date"],
							 "delivery_date": min(l["xf"] for l in spec["lines"]), "apparel_sales_contract": contract.name if contract else None, "items": rows},
			 submit=True, key=spec["style_no"])
	if so and contract:
		frappe.db.set_value("Sales Contract", contract.name, "sales_order", so.name)
	return so


def make_card(so, spec, variants):
	cells = []
	for sz in variants:
		cells.append({"colour": spec["colour"], "size": sz})
	card = put("Production Card", {"company": FACTORY, "customer": BUYER, "sales_order": so.name, "style_item": spec["style_code"], "lines": cells,
									"packing_requirements": spec.get("packing"), "local_contract_no": spec.get("local_contract"), "declaration_no": spec.get("declaration"),
									"top_sample_size": spec.get("top_size"), "factory": spec.get("factory_name")}, submit=True, key=spec["style_no"])
	return card


def post_flow(card, shipped):
	"""Write the production history that the packing list and the invoice imply (cut -> ... -> packed), so later documents have a ledger."""
	import json

	f = frappe.get_doc("Server Script", "arinox_engine")
	for stage in ("CUT", "SEW_IN", "SEW_OUT", "FIN_IN", "FIN_A", "PACKED"):
		rows = [{"stage": stage, "colour": c, "size": s, "qty": q} for (c, s), q in shipped.items() if q]
		frappe.local.form_dict.update({"action": "post", "card": card.name, "rows": json.dumps(rows), "source_doctype": "Import", "source_name": "IMP-" + stage,
									   "posting_date": frappe.utils.nowdate(), "check": "0"})
		f.execute_method()


def make_packing_lists(card, runs, head, spec, po):
	cartons, contents, pcs = [], [], 0
	for r in runs:
		sz = next((s for s, q in r["per"].items() if q), None)
		cartons.append({"carton_from": r["from"], "carton_to": r["to"], "carton_count": r["cartons"], "pieces_per_carton": r["per_carton"], "total_pieces": r["pieces"],
						"gross_weight_kg": r["gw_each"], "shade": r["shade"], "cbm_per_carton": r.get("cbm_each")})
		for s, q in r["per"].items():
			contents.append({"carton_from": r["from"], "colour": spec["colour"], "size": s, "qty_per_carton": q, "pieces_total": q * r["cartons"]})
		pcs += r["pieces"] or 0
	pl = put("Packing List", {"production_card": card.name, "packing_date": str(getdate(head.get("DATE") or frappe.utils.nowdate())), "pack_type": "Solid Colour Solid Size",
							  "pcs_per_carton": max([r["per_carton"] or 0 for r in runs] or [1]), "buyer_po": po, "ship_to": spec["ship_to"], "ship_via": ("Sea" if "SEA" in str(head.get("SHIP VIA") or "").upper() else "Air" if "AIR" in str(head.get("SHIP VIA") or "").upper() else ""),
							  "cartons": cartons, "contents": contents, "remarks": "imported from the factory packing list"}, submit=True, key=po)
	return pl


SECTION_CATEGORY = {"WOVEN LABELS": "Woven Label", "THREAD & FUSING": "Thread", "SECURITY TAGS": "Security Tag", "HANG TAGS": "Hang Tag", "OTHER BRANDING": "Branding",
					"BUTTONS": "Button", "POLY BAG": "Packaging", "POLYBAG STICKER": "Packaging", "TISSUE PAPER": "Packaging", "ZIPPER, HOOKS, FASTNERS": "Zipper / Hooks / Fasteners",
					"OTHERS": "Others", "PACKAGING": "Packaging"}


def tr_rows(path, sheet):
	"""Trim lines of one TRIMS REQUESTION (FORM) sheet: description, code, colour text, quantity, total with allowance, remark."""
	ws = xl(path)[sheet]
	section, out = None, []
	for r in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=9, values_only=True):
		first = str(r[0] or "").strip()
		if first and not first.replace(".", "").isdigit() and any("DESCRIPTION" in str(c).upper() for c in r[1:4] if c):
			section = first
			continue
		if (isinstance(r[0], (int, float)) or first.isdigit()) and section:
			cells = [c for c in r[1:] if c not in (None, "")]
			nums = [c for c in cells if isinstance(c, (int, float)) and not isinstance(c, bool)]
			texts = [str(c).strip() for c in cells if isinstance(c, str) and not str(c).startswith("#")]
			if not texts or not nums:
				continue
			out.append({"section": section, "texts": texts, "qty": nums[0] if len(nums) > 1 else None, "total": nums[-1]})
	return out


def trim_req(tr_path, sheet, so, spec):
	items = []
	for r in tr_rows(tr_path, sheet):
		t = r["texts"]
		code = next((x for x in t if re.match(r"^[A-Z]{1,3}\d{2,4}\b", x)), "")
		cat = SECTION_CATEGORY.get(r["section"].strip(), "Others")
		if r["section"].strip() == "WOVEN LABELS":
			cat = "Size Label" if "SIZE" in t[0].upper() and "MAIN" not in t[0].upper() else "Care Label" if "CARE" in t[0].upper() else "Woven Label"
		if "FUS" in " ".join(t).upper():
			cat = "Fusing / Interlining"
		qty = r["qty"] or spec["total_qty"]
		note = next((x for x in reversed(t) if "STOCK" in x.upper() or "ORDER" in x.upper() or "(" in x), "")
		items.append({"sales_order": so.name, "buyer_po": spec["lines"][0]["po"], "style_item": spec["style_code"], "style_no": spec["style_no"], "colour": "",
					  "trim_category": cat, "buyer_item_code": code, "description": " / ".join(x for x in t if x != note)[:140], "garment_qty": qty, "gross_qty": r["total"],
					  "allowance_pct": round((r["total"] / qty - 1) * 100, 2) if qty and r["total"] and r["total"] >= qty else None, "remarks": note, "calc_basis": "Per Garment"})
		if "HAVE STOCK" in note.upper():
			gap("Trim Requisition Item", "stock decision (HAVE STOCK / NEED TO ORDER)", note, "paper states the decision as words; the item has stock_used (a quantity) and a warehouse, not a yes/no")
	return put("Trim Requisition", {"company": FACTORY, "customer": BUYER, "tr_date": spec["tr_date"], "season": spec["season"], "shipment_mode": "Sea", "ordered_by": "Administrator",
									"items": items}, key=spec["style_no"])


def shipment(spec, pl, card, so, info):
	"""ERPNext Shipment with the apparel fields: booking, vessel, B/L, declaration, the measures kept side by side."""
	cust = frappe.db.get_value("Customer", BUYER, "name")
	body = {"pickup_from_type": "Company", "pickup_company": FACTORY, "delivery_to_type": "Customer", "delivery_customer": cust, "pickup_type": "Pickup",
			"pickup_date": info["pickup"], "description_of_content": "Garments " + spec["style_no"],
			"shipment_parcel": [{"length": 60, "width": 40, "height": 30, "weight": info["gw"] / max(info["cartons"], 1), "count": info["cartons"]}],
			"apparel_mode": "Sea LCL", "apparel_forwarder": info["forwarder"], "apparel_booking_no": info["booking"], "apparel_booking_date": info["booking_date"], "apparel_pol": info["pol"],
			"apparel_pod": info["pod"], "apparel_final_destination": "Los Angeles", "apparel_vessel_voyage": info["vessel"], "apparel_on_board_date": info["on_board"],
			"apparel_hbl_no": info["hbl"], "apparel_declared_cbm": info["cbm_pl"], "apparel_booked_cbm": info["cbm_booking"],
			"apparel_carrier_cbm": info["cbm_bl"], "apparel_declared_gross_kg": info["gw"], "apparel_booked_gross_kg": info["gw"], "apparel_carrier_gross_kg": info["gw"],
			"apparel_freight_terms": "Prepaid", "apparel_service_type": "LCL",
			"apparel_packing_lists": [{"packing_list": pl.name}] if pl else [],
			"apparel_declarations": [{"declaration_no": info["decl"], "type_code": "Export of goods made for export", "registered_on": "2025-12-20", "status": "Cleared",
									  "channel": "Green", "invoice_nos": info["invoice_no"], "invoice_value": info["ddp_price"] * info["pieces"] if info.get("pieces") else None,
									  "currency": "USD", "packages": info["cartons"], "gross_kg": info["gw"]}],
			"apparel_documents": [{"document_type": "Bill of Lading", "document_no": info["hbl"], "document_date": info["on_board"]},
								  {"document_type": "Commercial Invoice", "document_no": info["invoice_no"], "document_date": spec["inv_date"]},
								  {"document_type": "Packing List", "document_no": pl.name if pl else ""},
								  {"document_type": "Export Declaration", "document_no": info["decl"], "document_date": "2025-12-20"}]}
	return put("Shipment", {k: v for k, v in body.items() if v not in (None, "")}, key=info["booking"])


def delivery_note(so, pls, shipped_by_po, shipment_doc, spec):
	"""Delivery note for the packed quantities (by PO and size). `pls` maps PO -> Packing List."""
	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note

	dn = make_delivery_note(so.name)
	for it in dn.items:
		size, po = frappe.db.get_value("Sales Order Item", it.so_detail, ["apparel_size", "apparel_buyer_po"])
		it.qty = shipped_by_po.get(po, {}).get(size, 0)
		pl = pls.get(po)
		it.apparel_packing_list = pl.name if pl else None
	dn.items = [i for i in dn.items if i.qty]
	dn.posting_date = spec["ship_date"]
	dn.set_posting_time = 1
	if shipment_doc:
		dn.apparel_shipment = shipment_doc.name
	dn.apparel_gate_override = 1
	dn.apparel_gate_override_reason = "Final inspection report is not in the sample set (imported history)"
	try:
		dn.insert()
		try:
			dn.submit()
		except Exception as e:
			msg = str(e).replace("\n", " ")
			if "allowed up to" not in msg:
				raise
			OBS.append(("Delivery Note", so.name, "over-ship check stopped the note: " + re.sub("<[^>]+>", "", msg)[:200]))
			dn = frappe.get_doc("Delivery Note", dn.name)
			dn.apparel_over_ship_override = 1
			dn.apparel_over_ship_override_reason = "Buyer accepted the overage (imported history)"
			dn.save()
			dn.submit()
		MADE.append(("Delivery Note", dn.name))
		return dn
	except Exception as e:
		FAILS.append(("Delivery Note", so.name, str(e).replace("\n", " ")[:300]))
		return None


def invoice_lines(path):
	"""{sheet: [(po, style, qty, unit price, total)]} from a commercial invoice workbook."""
	out = {}
	for ws in xl(path).worksheets:
		rows = []
		for r in ws.iter_rows(min_row=1, max_row=60, values_only=True):
			cells = [c for c in r if c not in (None, "")]
			if len(cells) >= 6 and isinstance(cells[0], str) and re.match(r"^EM\d+", cells[0]) and isinstance(cells[-1], (int, float)) and isinstance(cells[-3], (int, float)):
				rows.append((cells[0], cells[1], cells[-3], cells[-2], cells[-1]))
		out[ws.title] = rows
	return out


def contract_file(path):
	"""Header and product lines of a CORTEX VIETNAM sales contract sheet."""
	ws = xl(path).worksheets[0]
	rows = list(ws.iter_rows(min_row=1, max_row=90, max_col=18, values_only=True))
	head = {}
	for r in rows[:12]:
		cells = list(r)
		for j, v in enumerate(cells):
			if isinstance(v, str) and v.strip().upper() in ("BUYER", "COMPANY", "SEASON", "DATED", "DIVISION", "MERCHANT", "SALES CONTRACT NO", "REVISION NO"):
				nxt = next((x for x in cells[j + 1:] if x not in (None, "")), None)
				head[v.strip().upper()] = nxt
	hi = next(i for i, r in enumerate(rows) if r and str(r[0] or "").strip().upper() == "ITEM NO")
	names = [str(c or "").strip().upper() for c in rows[hi]]
	lines = []
	for r in rows[hi + 1:]:
		if str(r[0] or "").strip().upper().startswith("TOTAL"):
			break
		if isinstance(r[0], (int, float)):
			lines.append({n: r[k] for k, n in enumerate(names) if n})
			for k, n in enumerate(names):
				if n.startswith("QUANTITY"):
					lines[-1]["QUANTITY"] = r[k]
	bands_text = "\n".join(str(c) for r in rows for c in r if isinstance(c, str) and "pcs" in c.lower())
	return head, lines, bands_text


def invoices(so, dn, spec, info):
	"""The two legs of the group route: factory -> Cortex HK at the transfer price, Cortex HK -> buyer at the DDP price. Same invoice number."""
	out = []
	for leg, seller, buyer, price in ((1, FACTORY, TRADER, info["transfer_price"]), (2, TRADER, BUYER, info["ddp_price"])):
		wh = frappe.db.get_value("Warehouse", {"company": seller, "is_group": 0}, "name")
		items = [{"item_code": i.item_code, "qty": i.qty, "rate": price, "warehouse": wh} for i in (dn.items if dn else so.items)]
		out.append(put("Sales Invoice", {"company": seller, "customer": buyer, "currency": "USD", "posting_date": spec["inv_date"], "set_posting_time": 1, "due_date": info["due"],
										 "update_stock": 0, "conversion_rate": RATE[seller], "apparel_sales_contract": spec.get("contract_name"), "apparel_commercial_invoice_no": info["invoice_no"],
										 "apparel_route_leg": leg, "apparel_shipment": info.get("shipment_name"), "apparel_due_basis": "Days after Receipt of Goods (ROG)", "items": items},
						 key=info["invoice_no"] + " leg " + str(leg)))
	return out


def cost_sheet(tp, spec, product_type, date, qty, fabrics, cm, trim, wash, markup_pct=10):
	"""Cost Sheet from a row of INTERNAL COSTING: fabric lines (yards per piece, +3%, price, cuttable width), cut-and-make, trim, wash, then the
	percentages the sheet prints under the total (overhead 17.5, rejection 3.5, finance 2.5, depreciation 2.5)."""
	frappe.db.set_value("Currency", "CNY", "enabled", 1)        # the papers say RMB; ERPNext's code for it is CNY
	if not frappe.db.exists("Cost Head", "Depreciation"):
		put("Cost Head", {"head_name": "Depreciation", "head_group": "Overhead", "calc_type": "Percent of Product Cost", "sequence": 135, "enabled": 1})
		OBS.append(("Cost Head", "Depreciation", "the sheet charges 2.5% depreciation on every style; no such cost head was seeded, so it was added as data"))
	if not frappe.db.exists("Product Type", product_type):
		put("Product Type", {"product_type": product_type})
	mats = []
	for f in fabrics:
		mats.append({"material_type": f.get("type", "Fabric"), "description": f["desc"], "consumption": f["yds"], "uom": "Yard", "wastage_pct": 3, "rate": f["rate"], "rate_uom": "Yard",
					 "price_currency": f.get("cur", "USD"), "exchange_rate": f.get("fx", 1), "cuttable_width": f["cw"], "remarks": "paper: " + f.get("note", "")})
	mats.append({"material_type": "Trim", "description": spec.get("trim_text", "trims, labels, thread"), "consumption": 1, "uom": "Nos", "wastage_pct": 0, "rate": trim})
	charges = [{"cost_head": "Stitching (CMT)", "rate": cm, "calc_type": "Per Piece"}, {"cost_head": "Washing", "rate": wash, "calc_type": "Per Piece"},
			   {"cost_head": "Overhead", "rate": 17.5, "calc_type": "Percent of Product Cost"}, {"cost_head": "Rejection Allowance", "rate": 3.5, "calc_type": "Percent of Product Cost"},
			   {"cost_head": "Finance", "rate": 2.5, "calc_type": "Percent of Product Cost"}, {"cost_head": "Depreciation", "rate": 2.5, "calc_type": "Percent of Product Cost"}]
	return put("Cost Sheet", {"naming_series": "CS-.YYYY.-", "customer": BUYER, "style_no": spec["style_no"], "style_name": spec["garment"], "product_type": product_type, "costing_date": date,
							  "currency": "USD", "order_qty": qty, "company": FACTORY, "season": spec["season"], "style_item": spec["style_code"], "tech_pack": tp.name if tp else None,
							  "profit_pct": markup_pct, "materials": mats, "charges": charges}, key=spec["style_no"])


def order_s84(root):
	d = lambda *p: find(root, *p)
	grade_p = d("1 - Merchandising/2 - Tech Pack/C2027-S84-304*GRADE*.xlsx")
	bom_p = d("1 - Merchandising/3 - Bill of Material*/C2027-S84-304.xls")
	pl_p = d("4 - Finance/1 - Final Invoice*/C2027-S84/*PL.xlsx")
	head, sizes, meas = grade(grade_p)
	_, bcolour, bdesc, brows = bom(bom_p)
	plh, runs, ordered, shipped = packing(pl_p)
	osz = [s for s in SIZES if ordered.get(s)] if ordered else ["XS", "S", "M", "L", "XL"]
	variants = style_item("C2027-S84-304", "CLASSIC BUTTON DOWN SHIRT", "MICRO TILE PRINT", "MICTP", osz)
	tp = tech_pack("C2027-S84-304", "CLASSIC BUTTON DOWN SHIRT", "C2027-S84-304", head, sizes, meas, "MICRO TILE PRINT", brows, source=os.path.basename(grade_p))
	spec = {"style_code": "C2027-S84-304", "style_no": "C2027-S84-304", "colour": "MICRO TILE PRINT", "fabric": "51% VISCOSE 49% RAYON, V50DxR60S/191x94, 92 gsm, 56in",
			"garment": "WOMEN WOVEN SHIRT", "price_term": "DDP", "ship_to": "EMJ APPAREL GROUP, LLC, Los Angeles", "date": "2025-09-12", "po_header": "69785 / EM92409",
			"season": "SPRING 2026", "brand": "Belladahl", "division": "SPECIAL PROJECTS", "pol": "Cai Mep", "pod": "Los Angeles", "total_qty": 1462,
			"packing": "CUSTOMER #6 / PACK #2 / FOLD #2 GREEN COLOR STICKER", "tr_date": "2025-09-20", "top_size": "S", "factory_name": None,
			"declaration": "308078021920", "local_contract": None,
			"bands": [{"from_qty": 0, "to_qty": 500, "tolerance_pct": 15}, {"from_qty": 501, "to_qty": 800, "tolerance_pct": 10}, {"from_qty": 801, "to_qty": 1600, "tolerance_pct": 7.5},
					  {"from_qty": 1601, "to_qty": 3000, "tolerance_pct": 5}],
			"lines": [{"po": "69785/EM92409", "qty": 1462, "rate": 16.30, "xf": "2025-12-26", "etd": "2026-01-02", "inwh": "2026-01-30", "tol": 7.5, "sizes": ordered}]}
	gap("Sales Contract", "(no garment sales contract for S84 in the sample set)", None, "the contract was built from the PO; the S84 file in 4 - Sales Contract is the FABRIC contract")
	cost_sheet(tp, spec, "Woven Top", "2025-08-29", 1462, [{"desc": "S84 51% viscose 49% rayon (self)", "yds": 1.5966754, "rate": 3.9, "cw": 56, "note": "USD 3.9 per yard; RMB column blank"}],
			   cm=2.2, trim=0.7, wash=0.22)
	sc = make_contract(root, spec)
	try_sign(sc, "S84 (contract built from the PO)")
	so = make_order(sc, spec, variants)
	tr_p = d("1 - Merchandising/7 - Trim Requesition (TR)/TRIM REQUEST 9.20*")
	tr = trim_req(tr_p, "TR C2027-S84-304", so, spec) if so and tr_p else None
	card = make_card(so, spec, variants) if so else None
	pl = sh = dn = None
	inv = []
	if card:
		post_flow(card, {(spec["colour"], s): q for s, q in shipped.items()})
		pl = make_packing_lists(card, runs, plh, spec, "69785/EM92409")
		info = {"pickup": "2025-12-23", "gw": 344.6, "cartons": 64, "forwarder": "BEE LOGISTICS CORPORATION - DANANG BRANCH", "booking": "BEELAX2512001", "booking_date": "2025-12-17",
				"pol": "VUNG TAU, VIETNAM", "pod": "LONG BEACH, USA", "vessel": "OOCL SUNFLOWER 007E", "on_board": "2025-12-26", "hbl": "BDN251200184", "cbm_pl": 1.597,
				"cbm_booking": 1.6, "cbm_bl": 1.91, "decl": "308078021920", "invoice_no": "CTXGVN25.12.23", "transfer_price": 6.56, "ddp_price": 16.85, "due": "2026-02-14"}
		spec["ship_date"] = "2025-12-23"
		spec["inv_date"] = "2025-12-20"
		info["pieces"] = sum(q for q in shipped.values() if q)
		sh = shipment(spec, pl, card, so, info)
		info["shipment_name"] = sh.name if sh else None
		dn = delivery_note(so, {"69785/EM92409": pl}, {"69785/EM92409": shipped}, sh, spec)
		inv = invoices(so, dn, spec, info)
	return {"tp": tp, "sc": sc, "so": so, "tr": tr, "card": card, "pl": pl, "sh": sh, "dn": dn, "inv": inv, "variants": variants, "ordered": ordered, "shipped": shipped}


def order_s14(root):
	d = lambda *p: find(root, *p)
	cpath = d("1 - Merchandising/4 - Sales Contract/SALES CONTRACT FOR C7502*")
	head_c, lines_c, bands_text = contract_file(cpath)
	grade_p = d("1 - Merchandising/2 - Tech Pack/5160*GRADE*.xlsx")
	bom_p = d("1 - Merchandising/3 - Bill of Material*/C7502-S14-304 COST SHEET.xls")
	fin = "4 - Finance/1 - Final Invoice*/C7502-S14/"
	pl1_p, pl2_p = d(fin + "EM92422*PL.xlsx"), d(fin + "EM92423*PL.xlsx")
	inv_p = d(fin + "*INV 5.28*")
	head, sizes, meas = grade(grade_p)
	_, _, _, brows = bom(bom_p)
	h1, runs1, ord1, shp1 = packing(pl1_p)
	h2, runs2, ord2, shp2 = packing(pl2_p)
	ord3 = {"XXS": 1, "XS": 3, "S": 4, "M": 6, "L": 1, "XL": 1}      # PO 70602, six numbers on the PO page; the PO has no packing list
	osz = [s for s in SIZES if (ord1 or {}).get(s) or (ord2 or {}).get(s) or ord3.get(s)]
	variants = style_item("C7502-S14-304", "BIAS MIDI SKIRT", "MOONFLOWER FOLIAGE", "MNFLR", osz)
	tp = tech_pack("C7502-S14-304", "BIAS MIDI SKIRT", "C7502-S14-304", head, sizes, meas, "MOONFLOWER FOLIAGE", brows, source=os.path.basename(grade_p))
	by_po = {"70599/EM92422": ord1, "70601/EM92423": ord2, "70602/EM92424": ord3}
	lines = []
	for ln in lines_c:
		po = str(ln.get("BUYER PO CODE")).strip()
		lines.append({"po": po, "qty": ln.get("QUANTITY"), "rate": ln.get("DDP UNIT"), "xf": str(getdate(ln.get("X-FTY"))), "etd": str(getdate(ln.get("ETD"))),
					  "inwh": str(getdate(ln.get("IN WAREHOUSE"))), "pcd": str(getdate(ln.get("PCD"))), "tol": 7.5 if (ln.get("QUANTITY") or 0) > 800 else 15, "sizes": by_po.get(po, {})})
	for ln in lines:
		if sum((ln["sizes"] or {}).values()) != ln["qty"]:
			gap("Sales Contract", "size breakdown", ln["po"], f"contract says {ln['qty']}, sizes add to {sum((ln['sizes'] or {}).values())}")
	spec = {"style_code": "C7502-S14-304", "style_no": "C7502-S14-304 (#5160)", "colour": "MOONFLOWER FOLIAGE", "fabric": "100% RAYON", "garment": "BIAS MIDI SKIRT",
			"finish": "Rinse W/softener", "price_term": "DDP", "ship_to": "EMJ APPAREL GROUP, LLC, Los Angeles", "date": str(getdate(head_c.get("DATED"))),
			"po_header": "70599/EM92422, 70601/EM92423, 70602/EM92424", "season": str(head_c.get("SEASON")), "brand": str(head_c.get("COMPANY")), "division": str(head_c.get("DIVISION")),
			"buyer_contact": str(head_c.get("BUYER")), "merchant": str(head_c.get("MERCHANT")), "marks": "TBA", "legacy_no": str(head_c.get("SALES CONTRACT NO")), "pol": "Vietnam", "pod": "Los Angeles",
			"total_qty": 5087, "packing": "PACK#5", "tr_date": "2026-01-22", "top_size": "S",
			"bands": [{"from_qty": 0, "to_qty": 500, "tolerance_pct": 15}, {"from_qty": 501, "to_qty": 800, "tolerance_pct": 10}, {"from_qty": 801, "to_qty": 1600, "tolerance_pct": 7.5},
					  {"from_qty": 1601, "to_qty": 3000, "tolerance_pct": 5}], "lines": lines}
	cost_sheet(tp, spec, "Bottom", "2025-11-21", 5000, [
		{"desc": "S14 100% rayon 58gsm (self)", "yds": 1.4, "rate": 18, "cur": "CNY", "fx": 7.3155, "cw": 52, "note": "RMB 18 -> USD 2.4606"},
		{"desc": "311 lining", "yds": 1.35, "rate": 10, "cur": "CNY", "fx": 8.0, "cw": 52, "type": "Lining", "note": "RMB 10 -> USD 1.25 (rate 8.0, not 7.3155)"}], cm=1.7, trim=0.5, wash=0.15)
	OBS.append(("Cost Sheet", "S14", "paper converts the main fabric at 7.3155 RMB per USD but the lining at 8.0; the model keeps an exchange rate per material row, so both are recorded as printed"))
	sc = make_contract(root, spec)
	try_sign(sc, "S14 (the real contract, shipping marks TBA as printed)")
	spec["contract_name"] = sc.name if sc else None
	so = make_order(sc, spec, variants)
	tr_p = d("1 - Merchandising/7 - Trim Requesition (TR)/TRIM REQUEST 01.24.26 CABI*")
	tr = trim_req(tr_p, "TR C7502-S14-304 (#5160)", so, spec) if so and tr_p else None
	card = make_card(so, spec, variants) if so else None
	pls, dn, sh, inv = {}, None, None, []
	if card:
		shipped_all = {}
		for shp in (shp1, shp2):
			for s_, q in (shp or {}).items():
				shipped_all[(spec["colour"], s_)] = shipped_all.get((spec["colour"], s_), 0) + q
		post_flow(card, shipped_all)
		pls["70599/EM92422"] = make_packing_lists(card, runs1, h1, spec, "70599/EM92422")
		pls["70601/EM92423"] = make_packing_lists(card, runs2, h2, spec, "70601/EM92423")
		spec["ship_date"] = "2026-05-30"
		spec["inv_date"] = "2026-05-28"
		invs = invoice_lines(inv_p)
		info = {"pickup": "2026-05-30", "gw": 236.7 + 0.0, "cartons": 56 + 163, "forwarder": FORWARDER, "booking": "GLOLAX160626", "booking_date": "2026-05-26", "pol": "Vietnam",
				"pod": "Los Angeles", "vessel": "", "on_board": "2026-06-16", "hbl": "GLOLAX160626", "cbm_pl": None, "cbm_booking": None, "cbm_bl": None, "decl": "308579201510",
				"invoice_no": "CTXGVN26.05.28", "transfer_price": 5.0, "ddp_price": 13.5, "due": "2026-07-25", "pieces": sum(shipped_all.values())}
		sh = shipment(spec, pls["70599/EM92422"], card, so, info)
		info["shipment_name"] = sh.name if sh else None
		dn = delivery_note(so, pls, {"70599/EM92422": shp1, "70601/EM92423": shp2}, sh, spec)
		inv = invoices(so, dn, spec, info)
		gap("Sales Invoice", "one invoice for 3 POs and 2 styles", "CTXGVN26.05.28", "the paper invoice also carries EM92428 / C9360 (another contract); Sales Invoice has one contract link, so the other style's lines were left out")
	return {"tp": tp, "sc": sc, "so": so, "tr": tr, "card": card, "pls": pls, "sh": sh, "dn": dn, "inv": inv, "variants": variants, "invoice_sheets": invoice_lines(inv_p) if inv_p else None}


def run(root):
	"""Ingest S84 and S14 from the unzipped 'ARINOX ERP DOCS' folder."""
	root = root.rstrip("/")
	frappe.set_user("Administrator")
	frappe.db.set_single_value("Stock Settings", "allow_negative_stock", 1)
	purge()
	fiscal_years()
	companies()
	parties()
	out = {"s84": order_s84(root), "s14": order_s14(root)}
	frappe.db.commit()
	return out


def report():
	print("MADE", len(MADE), "FAILS", len(FAILS), "GAPS", len(GAPS))
	for f in FAILS:
		print("FAIL", f)
	seen = set()
	for g in GAPS:
		k = (g[0], g[1])
		if k not in seen:
			seen.add(k)
			print("GAP", g[0], "|", g[1], "|", str(g[2])[:60], "|", g[3])
	from collections import Counter

	for o in OBS:
		print("OBS", o)
	print("OUT made:", dict(Counter(m[0] for m in MADE)))


def verify():
	"""Compare what the site now holds with the figures printed on the papers. Prints CHECK lines."""
	def q(sql, *a):
		return frappe.db.sql(sql, a)[0][0]

	def check(label, got, want, tol=0.005):
		ok = abs(float(got or 0) - float(want)) <= tol
		print(f"CHECK {'ok  ' if ok else 'DIFF'} {label}: ERP {got} | paper {want}")
		return ok

	so84 = frappe.db.get_value("Sales Order", {"po_no": "69785 / EM92409"}, "name")
	if so84:
		check("S84 order qty", q("select sum(qty) from `tabSales Order Item` where parent=%s", so84), 1462)
		check("S84 order value (PO total)", q("select grand_total from `tabSales Order` where name=%s", so84), 23830.60)
		card = frappe.db.get_value("Production Card", {"sales_order": so84}, "name")
		check("S84 planned cut (each size +5%, rounded up: 284+458+443+235+118)", q("select sum(planned_cut_qty) from `tabProduction Card Line` where parent=%s", card), 1538)
		check("S84 ledger SHIPPED", q("select ifnull(sum(qty),0) from `tabProduction Movement` where production_card=%s and stage='SHIPPED'", card), 1520)
		pl = frappe.db.get_value("Packing List", {"production_card": card}, "name")
		check("S84 packing list pieces (sum of the rows)", q("select sum(total_pieces) from `tabPacking List Carton` where parent=%s", pl), 1520)
		check("S84 packing list cartons (sum of the runs)", q("select sum(carton_count) from `tabPacking List Carton` where parent=%s", pl), 64)
		check("S84 packing list header total_cartons", q("select ifnull(total_cartons,0) from `tabPacking List` where name=%s", pl), 64)
		check("S84 packing list header total_pieces", q("select ifnull(total_pieces,0) from `tabPacking List` where name=%s", pl), 1520)
		for leg, want in ((1, 9971.20), (2, 25612.00)):
			got = frappe.db.sql("select grand_total from `tabSales Invoice` where apparel_commercial_invoice_no='CTXGVN25.12.23' and apparel_route_leg=%s", leg)
			check("S84 invoice leg " + str(leg), got[0][0] if got else 0, want)
		over = 1520 / 1462 * 100 - 100
		print(f"CHECK info S84 shipped {over:.2f}% over the order; contract band 7.5% -> allowed")
	so14 = frappe.db.get_value("Sales Order", {"po_no": ["like", "70599%"]}, "name")
	if so14:
		check("S14 order qty (3 POs)", q("select sum(qty) from `tabSales Order Item` where parent=%s", so14), 5087)
		check("S14 order value", q("select grand_total from `tabSales Order` where name=%s", so14), 68674.5)
		sc = frappe.db.get_value("Sales Contract", {"sales_order": so14}, "name")
		print("CHECK info S14 contract number kept from the paper:", sc)
		card = frappe.db.get_value("Production Card", {"sales_order": so14}, "name")
		check("S14 ledger SHIPPED", q("select ifnull(sum(qty),0) from `tabProduction Movement` where production_card=%s and stage='SHIPPED'", card), 1325 + 3902)
		check("S14 PO 70599 shipped (delivery note)", q("select ifnull(sum(i.qty),0) from `tabDelivery Note Item` i join `tabSales Order Item` s on s.name=i.so_detail where i.docstatus=1 and s.parent=%s and s.apparel_buyer_po like '70599%%'", so14), 1325)
		check("S14 PO 70601 shipped (delivery note)", q("select ifnull(sum(i.qty),0) from `tabDelivery Note Item` i join `tabSales Order Item` s on s.name=i.so_detail where i.docstatus=1 and s.parent=%s and s.apparel_buyer_po like '70601%%'", so14), 3902)
		got = frappe.db.sql("select grand_total from `tabSales Invoice` where apparel_commercial_invoice_no='CTXGVN26.05.28' and apparel_route_leg=2")
		check("S14 buyer invoice (the two S14 POs only)", got[0][0] if got else 0, 17887.5 + 52677)


def verify_tech_packs(root):
	"""Every measurement cell and every BOM line on the papers is on the Tech Pack."""
	root = root.rstrip("/")
	for style, g, b in (("C2027-S84-304", "1 - Merchandising/2 - Tech Pack/C2027-S84-304*GRADE*.xlsx", "1 - Merchandising/3 - Bill of Material*/C2027-S84-304.xls"),
						("C7502-S14-304", "1 - Merchandising/2 - Tech Pack/5160*GRADE*.xlsx", "1 - Merchandising/3 - Bill of Material*/C7502-S14-304 COST SHEET.xls")):
		head, sizes, rows = grade(find(root, g))
		ws = xl(find(root, g)).worksheets[0]
		hdr = next(i for i, r in enumerate(ws.iter_rows(min_row=1, max_row=40, values_only=True), 1) if str(r[0] or "").strip().upper() == "POM CODE")
		hr = [c.value for c in ws[hdr]]
		scols = [j for j, v in enumerate(hr) if str(v or "").strip().upper() in SIZES]
		cells = 0
		for r in ws.iter_rows(min_row=hdr + 1, max_row=ws.max_row, values_only=True):         # every numeric cell under a size heading, whatever the row looks like
			if str(r[0] or "").strip().upper() == "POM CODE":
				break
			cells += sum(1 for j in scols if isinstance(r[j], (int, float)) and not isinstance(r[j], bool))
		odd = []
		tp = frappe.db.get_value("Tech Pack", {"style_no": style}, "name")
		got = 0
		for mrow in frappe.get_all("Tech Pack Measurement", filters={"parent": tp}, fields=STANDARD_SIZES_LOWER):
			got += sum(1 for k in STANDARD_SIZES_LOWER if frappe.utils.flt(mrow.get(k)))
		bom_rows = len(bom(find(root, b))[3])
		mats = frappe.db.count("Tech Pack Material", {"parent": tp})
		codes = [r["pom"] for r in rows]
		dup = sorted({c for c in codes if codes.count(c) > 1})
		print(f"CHECK {'ok  ' if cells == got else 'DIFF'} {style} measurements: {len(rows)} rows on the paper, {cells} numbers under the size headings | ERP {got}")
		print(f"CHECK {'ok  ' if bom_rows == mats else 'DIFF'} {style} BOM lines: paper {bom_rows} | ERP {mats}")
		print(f"CHECK info {style} POM codes used twice on the paper: {dup}; cells that are not plain numbers: {odd[:6]}")
