"""Phase E setup: custom fields on the ERPNext documents the shipping and collections flow extends (Shipment, Delivery Note,
Sales and Purchase Invoice, Customer, Supplier Quotation, Payment Entry), the AQL plan, and process terms. Idempotent."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

from arinox_apparel.setup.materials import _chain

D = dict


def get_custom_fields():
	contract = lambda anchor: D(fieldname="apparel_sales_contract", fieldtype="Link", options="Sales Contract", label="Contract", insert_after=anchor,  # noqa: E731
								read_only=1, no_copy=1, search_index=1, in_standard_filter=1)
	cf = {
		"Shipment": _chain("Shipment", [
			D(fieldname="apparel_section", fieldtype="Section Break", label="Export Booking", collapsible=0),
			D(fieldname="apparel_mode", fieldtype="Select", label="Mode", options="\nSea LCL\nSea FCL\nAir\nCourier\nRoad", in_list_view=1, in_standard_filter=1),
			D(fieldname="apparel_ship_status", fieldtype="Select", label="Shipping Status", in_list_view=1, in_standard_filter=1, allow_on_submit=1,
			  options="\nPlanned\nBooked\nDocuments Prepared\nCargo Handed Over\nCustoms Cleared\nOn Board\nArrived\nDelivered\nClosed\nOn Hold", default="Planned"),
			D(fieldname="apparel_contracts", fieldtype="Small Text", label="Contracts", read_only=1),
			D(fieldname="apparel_forwarder", fieldtype="Link", options="Supplier", label="Forwarder", allow_on_submit=1),
			D(fieldname="apparel_booking_no", fieldtype="Data", label="Booking No", allow_on_submit=1),
			D(fieldname="apparel_booking_date", fieldtype="Date", label="Booking Date", allow_on_submit=1),
			D(fieldname="apparel_ship_col1", fieldtype="Column Break"),
			D(fieldname="apparel_pol", fieldtype="Data", label="Port / Airport of Loading", allow_on_submit=1),
			D(fieldname="apparel_pod", fieldtype="Data", label="Port / Airport of Discharge", allow_on_submit=1),
			D(fieldname="apparel_final_destination", fieldtype="Data", label="Final Destination", allow_on_submit=1),
			D(fieldname="apparel_vessel_voyage", fieldtype="Data", label="Vessel / Voyage or Flight", allow_on_submit=1),
			D(fieldname="apparel_stuffing_place", fieldtype="Data", label="Stuffing Place", allow_on_submit=1),
			D(fieldname="apparel_service_type", fieldtype="Data", label="Service (e.g. CFS/DOOR)", allow_on_submit=1),
			D(fieldname="apparel_freight_terms", fieldtype="Select", label="Freight", options="\nPrepaid\nCollect", allow_on_submit=1),
			D(fieldname="apparel_dates", fieldtype="Section Break", label="Dates and Bill of Lading"),
			D(fieldname="apparel_cutoff", fieldtype="Datetime", label="Cut-off", allow_on_submit=1),
			D(fieldname="apparel_etd", fieldtype="Date", label="ETD", allow_on_submit=1),
			D(fieldname="apparel_eta", fieldtype="Date", label="ETA", allow_on_submit=1),
			D(fieldname="apparel_bl_type", fieldtype="Select", label="B/L Type", options="\nOriginal\nTelex Release\nSurrendered\nSea Waybill\nAir Waybill", allow_on_submit=1),
			D(fieldname="apparel_dates_col", fieldtype="Column Break"),
			D(fieldname="apparel_hbl_no", fieldtype="Data", label="House B/L or AWB No", allow_on_submit=1),
			D(fieldname="apparel_mbl_no", fieldtype="Data", label="Master B/L or AWB No", allow_on_submit=1),
			D(fieldname="apparel_on_board_date", fieldtype="Date", label="On-board Date", allow_on_submit=1, description="The shipment date: payment terms counted from the B/L start here"),
			D(fieldname="apparel_arrival_date", fieldtype="Date", label="Arrival Date", allow_on_submit=1),
			D(fieldname="apparel_delivery_date", fieldtype="Date", label="Delivered to Buyer's Warehouse", allow_on_submit=1),
			D(fieldname="apparel_air_section", fieldtype="Section Break", label="If by Air on a Sea Contract", collapsible=1),
			D(fieldname="apparel_reason_for_air", fieldtype="Small Text", label="Why by Air", allow_on_submit=1),
			D(fieldname="apparel_air_cost_borne_by", fieldtype="Select", label="Extra Cost Borne By", options="\nFactory\nBuyer\nSupplier\nShared", allow_on_submit=1),
			D(fieldname="apparel_measures", fieldtype="Section Break", label="Measures (kept side by side)", collapsible=1),
			D(fieldname="apparel_declared_cbm", fieldtype="Float", label="Packing Lists CBM", read_only=1, precision="6"),
			D(fieldname="apparel_booked_cbm", fieldtype="Float", label="Booked CBM", allow_on_submit=1, precision="6"),
			D(fieldname="apparel_carrier_cbm", fieldtype="Float", label="Carrier CBM (B/L)", allow_on_submit=1, precision="6"),
			D(fieldname="apparel_measures_col", fieldtype="Column Break"),
			D(fieldname="apparel_declared_gross_kg", fieldtype="Float", label="Packing Lists Gross kg", read_only=1),
			D(fieldname="apparel_booked_gross_kg", fieldtype="Float", label="Booked Gross kg", allow_on_submit=1),
			D(fieldname="apparel_carrier_gross_kg", fieldtype="Float", label="Carrier Gross kg (B/L or AWB)", allow_on_submit=1),
			D(fieldname="apparel_customs_gross_kg", fieldtype="Float", label="Customs Gross kg", allow_on_submit=1),
			D(fieldname="apparel_measure_note", fieldtype="Small Text", label="Differences", read_only=1),
			D(fieldname="apparel_cost_section", fieldtype="Section Break", label="Freight Cost", collapsible=1),
			D(fieldname="apparel_freight_quote", fieldtype="Link", options="Supplier Quotation", label="Chosen Freight Quote", allow_on_submit=1),
			D(fieldname="apparel_estimate_total", fieldtype="Currency", label="Quote Total", read_only=1),
			D(fieldname="apparel_actual_total", fieldtype="Currency", label="Forwarder Bills", read_only=1),
			D(fieldname="apparel_cost_variance_pct", fieldtype="Percent", label="Bills vs Quote %", read_only=1),
			D(fieldname="apparel_lists_section", fieldtype="Section Break", label="On Board"),
			D(fieldname="apparel_packing_lists", fieldtype="Table", options="Shipment Packing List", label="Packing Lists", allow_on_submit=1),
			D(fieldname="apparel_containers", fieldtype="Table", options="Shipment Container", label="Containers", allow_on_submit=1),
			D(fieldname="apparel_declarations", fieldtype="Table", options="Shipment Declaration", label="Export Declarations", allow_on_submit=1),
			D(fieldname="apparel_documents", fieldtype="Table", options="Shipment Document", label="Documents", allow_on_submit=1),
			D(fieldname="apparel_destination_country", fieldtype="Link", options="Country", label="Destination Country", allow_on_submit=1, description="Decides which filing rules apply"),
			D(fieldname="apparel_chargeable_kg", fieldtype="Float", label="Chargeable Weight (air, kg)", read_only=1),
			D(fieldname="apparel_chargeable_cbm", fieldtype="Float", label="Chargeable Volume (sea, W/M)", read_only=1, precision="3"),
			D(fieldname="apparel_filings", fieldtype="Table", options="Shipment Filing", label="Destination Filings", allow_on_submit=1),
		], "description_of_content"),
		"Delivery Note": [
			contract("customer_name"),
			D(fieldname="apparel_shipment", fieldtype="Link", options="Shipment", label="Shipment", insert_after="apparel_sales_contract", read_only=1, no_copy=1, search_index=1),
			D(fieldname="apparel_gate_override", fieldtype="Check", label="Override Inspection Gate", insert_after="apparel_shipment", no_copy=1, description="Manager only"),
			D(fieldname="apparel_gate_override_reason", fieldtype="Small Text", label="Gate Override Reason", insert_after="apparel_gate_override", depends_on="apparel_gate_override", no_copy=1),
			D(fieldname="apparel_over_ship_override", fieldtype="Check", label="Approve Over-shipment", insert_after="apparel_gate_override_reason", no_copy=1, description="Manager only"),
			D(fieldname="apparel_over_ship_override_reason", fieldtype="Small Text", label="Over-shipment Reason", insert_after="apparel_over_ship_override", depends_on="apparel_over_ship_override", no_copy=1),
		],
		"Delivery Note Item": [
			D(fieldname="apparel_packing_list", fieldtype="Link", options="Packing List", label="Packing List", insert_after="against_sales_order", read_only=1, no_copy=1),
			D(fieldname="apparel_production_card", fieldtype="Link", options="Production Card", label="Production Card", insert_after="apparel_packing_list", read_only=1, no_copy=1),
		],
		"Sales Invoice": [
			contract("customer_name"),
			D(fieldname="apparel_all_contracts", fieldtype="Small Text", label="All Contracts On This Invoice", insert_after="apparel_sales_contract", read_only=1, no_copy=1,
			  description="One invoice may cover several contracts; the link above is the first, this lists them all"),
			D(fieldname="apparel_commercial_invoice_no", fieldtype="Data", label="Commercial Invoice No", insert_after="apparel_sales_contract", read_only=1, no_copy=1, search_index=1, in_standard_filter=1),
			D(fieldname="apparel_shipment", fieldtype="Link", options="Shipment", label="Shipment", insert_after="apparel_commercial_invoice_no", read_only=1, no_copy=1, search_index=1),
			D(fieldname="apparel_route_leg", fieldtype="Int", label="Route Leg", insert_after="apparel_shipment", read_only=1, no_copy=1, description="1 = seller to group company or direct, 2 = group company to buyer"),
			D(fieldname="apparel_is_sample_invoice", fieldtype="Check", label="Sample Invoice", insert_after="apparel_route_leg", no_copy=1),
			D(fieldname="apparel_letter_of_credit", fieldtype="Link", options="Letter of Credit", label="Letter of Credit", insert_after="apparel_is_sample_invoice", no_copy=1),
			D(fieldname="apparel_follow_section", fieldtype="Section Break", label="Payment Follow-up", insert_after="apparel_is_sample_invoice", collapsible=1),
			D(fieldname="apparel_due_basis", fieldtype="Data", label="Payment Basis", insert_after="apparel_follow_section", read_only=1, allow_on_submit=1, no_copy=1),
			D(fieldname="apparel_basis_date", fieldtype="Date", label="Basis Date", insert_after="apparel_due_basis", read_only=1, allow_on_submit=1, no_copy=1),
			D(fieldname="apparel_basis_source", fieldtype="Data", label="Basis Date From", insert_after="apparel_basis_date", read_only=1, allow_on_submit=1, no_copy=1),
			D(fieldname="apparel_expected_due_date", fieldtype="Date", label="Expected Due Date", insert_after="apparel_basis_source", read_only=1, allow_on_submit=1, no_copy=1, in_standard_filter=1),
			D(fieldname="apparel_follow_col", fieldtype="Column Break", insert_after="apparel_expected_due_date"),
			D(fieldname="apparel_followup_status", fieldtype="Select", label="Follow-up Status", insert_after="apparel_follow_col", read_only=1, allow_on_submit=1, no_copy=1, in_standard_filter=1,
			  options="\nNot Due\nDue Soon\nOverdue\nPromised\nPartly Paid\nDisputed\nPaid"),
			D(fieldname="apparel_days_overdue", fieldtype="Int", label="Days Overdue", insert_after="apparel_followup_status", read_only=1, allow_on_submit=1, no_copy=1),
			D(fieldname="apparel_promise_date", fieldtype="Date", label="Customer's Promise Date", insert_after="apparel_days_overdue", allow_on_submit=1, no_copy=1),
			D(fieldname="apparel_promise_amount", fieldtype="Currency", options="currency", label="Promised Amount", insert_after="apparel_promise_date", allow_on_submit=1, no_copy=1),
			D(fieldname="apparel_next_action_date", fieldtype="Date", label="Next Action", insert_after="apparel_promise_amount", allow_on_submit=1, no_copy=1),
			D(fieldname="apparel_dispute_reason", fieldtype="Small Text", label="Dispute", insert_after="apparel_next_action_date", allow_on_submit=1, no_copy=1),
		],
		"Purchase Invoice": [
			D(fieldname="apparel_shipment", fieldtype="Link", options="Shipment", label="Shipment (Forwarder Bill)", insert_after="bill_no", search_index=1, no_copy=1),
		],
		"Supplier Quotation": [
			D(fieldname="apparel_shipment", fieldtype="Link", options="Shipment", label="Shipment (Freight Quote)", insert_after="supplier_name", no_copy=1),
			D(fieldname="apparel_quote_mode", fieldtype="Select", label="Freight Mode", insert_after="apparel_shipment", options="\nSea LCL\nSea FCL\nAir\nCourier\nRoad"),
		],
		"Supplier Quotation Item": [
			D(fieldname="apparel_charge_unit", fieldtype="Select", label="Charged Per", insert_after="item_code",
			  options="\nPer CBM\nPer kg\nPer HBL\nPer Shipment\nPer Container\nPer Pallet\n% of Invoice\nAt Cost"),
			D(fieldname="apparel_min_amount", fieldtype="Currency", options="currency", label="Minimum Charge", insert_after="apparel_charge_unit"),
			D(fieldname="apparel_max_amount", fieldtype="Currency", options="currency", label="Maximum Charge", insert_after="apparel_min_amount"),
		],
		"Payment Entry": [
			D(fieldname="apparel_remittance_ref", fieldtype="Data", label="Remittance / Bank Reference", insert_after="reference_no"),
		],
		"Shipment Parcel Template": [
			D(fieldname="apparel_customer", fieldtype="Link", options="Customer", label="Customer", insert_after="parcel_template_name", description="Leave blank if any customer"),
			D(fieldname="apparel_tare_kg", fieldtype="Float", label="Empty Carton Weight (kg)", insert_after="weight"),
			D(fieldname="apparel_max_gross_kg", fieldtype="Float", label="Max Gross Weight (kg)", insert_after="apparel_tare_kg"),
		],
		"Customer": _chain("Customer", [
			D(fieldname="apparel_bill_section", fieldtype="Section Break", label="Apparel Invoicing", collapsible=1),
			D(fieldname="apparel_invoice_via_company", fieldtype="Link", options="Company", label="Invoice Through Group Company",
			  description="Leave blank to bill from the seller company directly. Set it when a group trading company invoices this buyer; the factory then invoices that company first at the transfer price."),
			D(fieldname="apparel_transfer_basis", fieldtype="Select", label="Transfer Price Basis", options="\nPercent of Customer Price\nPrice List\nCost Sheet FOB", depends_on="apparel_invoice_via_company"),
			D(fieldname="apparel_transfer_pct", fieldtype="Percent", label="Transfer Price % of Customer Price", depends_on="eval:doc.apparel_transfer_basis=='Percent of Customer Price'"),
			D(fieldname="apparel_transfer_price_list", fieldtype="Link", options="Price List", label="Transfer Price List", depends_on="eval:doc.apparel_transfer_basis=='Price List'"),
		], "default_currency"),
	}
	return cf


def run():
	make_custom_fields()
	move_carton_types()
	seed_filing_rules()
	from arinox_apparel.portable import loader

	loader.install()
	make_property_setters()
	seed_aql_plan()
	seed_process_terms()


def make_custom_fields():
	create_custom_fields(get_custom_fields(), ignore_validate=True, update=True)


def make_property_setters():
	"""A freight booking has no pickup address or time the way a courier parcel does; stop Shipment insisting on them."""
	for field in ("pickup_address_name", "delivery_address_name", "pickup_from", "pickup_to", "pickup_date", "description_of_content", "value_of_goods"):
		make_property_setter("Shipment", field, "reqd", "0", "Check", validate_fields_for_doctype=False)


# ISO 2859-1 Table 2-A, General Inspection Level II, single sampling, normal. Lot ranges, code letters and sample sizes agree
# across sources. Accept/Reject numbers are filled in only where two independent sources agreed (codes K, L, M). Everything
# else is left for QA to confirm from the standard: an inspection that lands on an unconfirmed row is refused.
AQL_ROWS = [  # lot from, to, code, sample size, (major ac, re), (minor ac, re), confirmed
	(2, 8, "A", 2, None, None), (9, 15, "B", 3, None, None), (16, 25, "C", 5, None, None), (26, 50, "D", 8, None, None),
	(51, 90, "E", 13, None, None), (91, 150, "F", 20, None, None), (151, 280, "G", 32, None, None), (281, 500, "H", 50, None, None),
	(501, 1200, "J", 80, None, None), (1201, 3200, "K", 125, (7, 8), (10, 11)), (3201, 10000, "L", 200, (10, 11), (14, 15)),
	(10001, 35000, "M", 315, (14, 15), (21, 22)), (35001, 150000, "N", 500, None, None), (150001, 500000, "P", 800, None, None),
	(500001, 99999999, "Q", 1250, None, None),
]
PLAN = "Garment AQL 2.5 / 4.0 Level II"
LEVEL = "General II"


def seed_aql_plan():
	if frappe.db.exists("AQL Plan", PLAN):
		return
	plan = frappe.get_doc({"doctype": "AQL Plan", "plan_name": PLAN, "inspection_level": LEVEL,
						   "aql_critical": "0", "aql_major": "2.5", "aql_minor": "4.0",
						   "note": "Lot ranges and sample sizes: ISO 2859-1 Table 2-A, Level II. Accept/Reject numbers are confirmed only for codes K, L and M (two sources agreed). QA must fill in and tick Confirmed on every other row from the standard before it is used."})
	for lo, hi, code, n, major, minor in AQL_ROWS:
		plan.append("rows", {"lot_from": lo, "lot_to": hi, "code_letter": code, "sample_size": n, "critical_ac": 0, "critical_re": 1,
							 "major_ac": major[0] if major else 0, "major_re": major[1] if major else 0, "minor_ac": minor[0] if minor else 0, "minor_re": minor[1] if minor else 0,
							 "confirmed": 1 if major else 0})
	plan.insert(ignore_permissions=True)
	if not frappe.db.get_single_value("Apparel Settings", "final_inspection_plan"):
		frappe.db.set_single_value("Apparel Settings", "final_inspection_plan", plan.name)


TERMS = {"Wash": (3, 5, 1), "Garment Dye": (5, 5, 3), "Embroidery": (3, 5, 1), "Print": (3, 5, 1), "Appliqué": (3, 5, 1), "Heat Transfer": (2, 5, 1)}


def seed_process_terms():
	"""Starting terms for the six seeded processes (turnaround days, quantity tolerance, damage limit). Only where empty."""
	for name, (days, tol, limit) in TERMS.items():
		if frappe.db.exists("Subcontract Process", name) and not frappe.db.get_value("Subcontract Process", name, "turnaround_days"):
			frappe.db.set_value("Subcontract Process", name, {"turnaround_days": days, "qty_tolerance_pct": tol, "damage_threshold_pct": limit}, update_modified=False)


def move_carton_types():
	"""Carton Type duplicated ERPNext's Shipment Parcel Template. Rows left in the old table are copied across once; the
	old doctype is removed from the app, so migrate drops it and this is the only place its data is read."""
	if not frappe.db.table_exists("Carton Type"):
		return
	for r in frappe.db.sql("select * from `tabCarton Type`", as_dict=True):
		name = r.get("type_name") or r.get("name")
		if not frappe.db.exists("Shipment Parcel Template", name):
			frappe.get_doc({"doctype": "Shipment Parcel Template", "parcel_template_name": name, "length": r.get("length_cm") or 0, "width": r.get("width_cm") or 0,
							"height": r.get("height_cm") or 0, "weight": r.get("tare_kg") or 0, "apparel_customer": r.get("customer"), "apparel_tare_kg": r.get("tare_kg"),
							"apparel_max_gross_kg": r.get("max_gross_kg")}).insert(ignore_permissions=True)


def seed_filing_rules():
	"""One example, switched off: the US Importer Security Filing is due 24 hours before loading for ocean cargo when the importer
	is the seller (delivered duty paid). Check it with your broker before enabling; other countries add their own rows."""
	if frappe.db.exists("Destination Filing Rule", "Importer Security Filing (US)") or not frappe.db.exists("Country", "United States"):
		return
	frappe.get_doc({"doctype": "Destination Filing Rule", "filing_name": "Importer Security Filing (US)", "country": "United States", "mode": "Sea",
					"hours_before_loading": 24, "incoterms": "DDP", "filed_by": "Forwarder", "enabled": 0,
					"note": "Ocean cargo to the US: filed 24 hours before loading at the foreign port (19 CFR 149). Cut-off is used as the loading time. Verify before enabling."}).insert(ignore_permissions=True)
