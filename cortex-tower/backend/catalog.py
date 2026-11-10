"""The process sidebar. One definition, served to the UI by ``cx_catalog`` — the frontend does not hard-code it.

Groups follow the client's order flow so every screen maps to one step. Item kinds:
``view``   a bespoke screen the frontend knows by key;
``doc``    the generic record workspace for an ERP doctype;
``report`` one of the 20 reports run through the TSR (17 Script Reports + 3 Query Reports wrapped as scripts).
"""

NAV = [
    {"key": "home", "label": "Home", "icon": "home", "items": [
        {"key": "today", "label": "Today", "kind": "view"},
        {"key": "overview", "label": "Overview", "kind": "view"},
        {"key": "ask", "label": "Ask Cortex", "kind": "view"},
    ]},
    {"key": "enquire", "label": "1 · Enquire", "icon": "inbox", "items": [
        {"key": "inbox", "label": "Inbox", "kind": "view"},
        {"key": "inquiries", "label": "Inquiries", "kind": "view"},
        {"key": "tech_pack", "label": "Tech Packs", "kind": "doc", "doctype": "Tech Pack"},
        {"key": "cost_sheet", "label": "Cost Sheets", "kind": "doc", "doctype": "Cost Sheet"},
        {"key": "negotiation", "label": "Negotiation", "kind": "doc", "doctype": "Price Negotiation"},
        {"key": "quotation", "label": "Quotations", "kind": "doc", "doctype": "Quotation"},
    ]},
    {"key": "win", "label": "2 · Win the order", "icon": "handshake", "items": [
        {"key": "intake", "label": "Order intake (POs)", "kind": "view"},
        {"key": "sales_contract", "label": "Sales Contracts", "kind": "doc", "doctype": "Sales Contract"},
        {"key": "orders", "label": "Order book", "kind": "view"},
        {"key": "sales_order", "label": "Sales Orders", "kind": "doc", "doctype": "Sales Order"},
    ]},
    {"key": "plan", "label": "3 · Plan", "icon": "calendar", "items": [
        {"key": "tna", "label": "T&A Calendar", "kind": "view"},
        {"key": "factory_allocation", "label": "Factory allocation", "kind": "doc", "doctype": "Factory Allocation"},
        {"key": "sample_approval", "label": "Samples", "kind": "doc", "doctype": "Sample Approval"},
        {"key": "pp_meeting", "label": "PP meetings", "kind": "doc", "doctype": "PP Meeting"},
        {"key": "r_sample_tracker", "label": "Sample tracker", "kind": "report", "report": "Sample Approval Tracker"},
    ]},
    {"key": "materials", "label": "4 · Materials", "icon": "layers", "items": [
        {"key": "fabric_requisition", "label": "Fabric requisitions", "kind": "doc", "doctype": "Fabric Requisition"},
        {"key": "trim_requisition", "label": "Trim requisitions", "kind": "doc", "doctype": "Trim Requisition"},
        {"key": "purchase_order", "label": "Purchase orders", "kind": "doc", "doctype": "Purchase Order"},
        {"key": "purchase_receipt", "label": "Receipts", "kind": "doc", "doctype": "Purchase Receipt"},
        {"key": "fabric_inspection", "label": "Fabric inspection", "kind": "doc", "doctype": "Fabric Inspection"},
        {"key": "trim_inspection", "label": "Trim inspection", "kind": "doc", "doctype": "Trim Inspection"},
        {"key": "r_material_status", "label": "Material status", "kind": "report", "report": "Material Status"},
        {"key": "r_fabric_stock", "label": "Running fabric stock", "kind": "report", "report": "Running Fabric Stock"},
        {"key": "r_fabric_overdue", "label": "Fabric lines overdue", "kind": "report", "report": "Fabric Overdue Lines"},
        {"key": "r_trim_hold", "label": "Trim lines on hold", "kind": "report", "report": "Trim Lines On Hold Count"},
        {"key": "fabric", "label": "Fabric price check", "kind": "view"},
    ]},
    {"key": "make", "label": "5 · Make", "icon": "factory", "items": [
        {"key": "production_card", "label": "Production cards", "kind": "doc", "doctype": "Production Card"},
        {"key": "cut_plan", "label": "Cut plans", "kind": "doc", "doctype": "Cut Plan"},
        {"key": "lay_report", "label": "Lay reports", "kind": "doc", "doctype": "Lay Report"},
        {"key": "daily_line_report", "label": "Line reports", "kind": "doc", "doctype": "Daily Line Report"},
        {"key": "subcontract_challan", "label": "Subcontract", "kind": "doc", "doctype": "Subcontract Challan"},
        {"key": "finishing_receipt", "label": "Finishing", "kind": "doc", "doctype": "Finishing Receipt"},
        {"key": "wip", "label": "WIP plan", "kind": "view"},
        {"key": "r_sewing_wip", "label": "Sewing WIP", "kind": "report", "report": "Sewing WIP"},
        {"key": "r_production_summary", "label": "Production summary", "kind": "report", "report": "Production Summary"},
        {"key": "r_line_loading", "label": "Line loading", "kind": "report", "report": "Line Loading"},
        {"key": "r_factory_load", "label": "Factory load", "kind": "report", "report": "Factory Load"},
    ]},
    {"key": "quality", "label": "6 · Quality & pack", "icon": "shield", "items": [
        {"key": "final_inspection", "label": "Final inspection", "kind": "doc", "doctype": "Final Inspection"},
        {"key": "packing_list", "label": "Packing lists", "kind": "doc", "doctype": "Packing List"},
        {"key": "r_dhu", "label": "Efficiency & DHU", "kind": "report", "report": "Line Efficiency and DHU"},
    ]},
    {"key": "ship", "label": "7 · Ship & get paid", "icon": "ship", "items": [
        {"key": "shipment", "label": "Shipments", "kind": "doc", "doctype": "Shipment"},
        {"key": "delivery_note", "label": "Delivery notes", "kind": "doc", "doctype": "Delivery Note"},
        {"key": "sales_invoice", "label": "Invoices", "kind": "doc", "doctype": "Sales Invoice"},
        {"key": "r_receivables", "label": "Receivables follow-up", "kind": "report", "report": "Receivables Follow-up"},
        {"key": "letter_of_credit", "label": "LC watch", "kind": "doc", "doctype": "Letter of Credit"},
        {"key": "buyer_claim", "label": "Claims", "kind": "doc", "doctype": "Buyer Claim"},
        {"key": "r_freight", "label": "Freight allocation", "kind": "report", "report": "Freight Allocation"},
    ]},
    {"key": "analyse", "label": "Analyse", "icon": "chart", "items": [
        {"key": "reports", "label": "All reports", "kind": "view"},
        {"key": "forecast", "label": "Forecast", "kind": "view"},
        {"key": "operations", "label": "Operations charts", "kind": "view"},
        {"key": "risks", "label": "Risks", "kind": "view"},
        {"key": "r_costing_margin", "label": "Costing margin", "kind": "report", "report": "Costing Margin Review"},
        {"key": "r_contract_trail", "label": "Contract trail", "kind": "report", "report": "Contract Trail"},
        {"key": "r_contract_delivery", "label": "Delivery schedule", "kind": "report", "report": "Contract Delivery Schedule"},
        {"key": "r_inquiry_tracker", "label": "Inquiry → contract", "kind": "report", "report": "Inquiry to Contract Tracker"},
    ]},
    {"key": "control", "label": "Control", "icon": "settings", "items": [
        {"key": "approvals", "label": "Approvals", "kind": "view"},
        {"key": "actions", "label": "Recommended actions", "kind": "view"},
        {"key": "mail", "label": "Outbound mail", "kind": "view"},
        {"key": "activity", "label": "Activity & audit", "kind": "view"},
        {"key": "sync", "label": "Sync & guardrails", "kind": "view"},
        {"key": "tsr", "label": "Script runtime", "kind": "view", "admin": True},
        {"key": "admin", "label": "Users & settings", "kind": "view", "admin": True},
    ]},
]

#: views any signed-in role may open (everything else of kind "view" that is admin-only is flagged above)
