app_name = "arinox_apparel"
app_title = "Arinox Apparel"
app_publisher = "Arinox AI"
app_description = "Apparel industry ERP layer for Frappe / ERPNext"
app_email = "dev@arinox.ai"
app_license = "MIT"

# Installed only after ERPNext is present on the site.
required_apps = ["erpnext"]

add_to_apps_screen = [
	{
		"name": app_name,
		"logo": "/assets/erpnext/images/erpnext-logo.svg",
		"title": "Apparel",
		"route": "/app/apparel",
	}
]

# ---------------------------------------------------------------------------------------------
# Install / migrate: custom fields on ERPNext doctypes, roles, seed cost heads and product types.
# Idempotent, so it runs on every migrate.
after_install = "arinox_apparel.setup.install.after_install"
after_migrate = "arinox_apparel.setup.install.after_migrate"

# ---------------------------------------------------------------------------------------------
# Phase 1 (order win): ERPNext documents that join the apparel flow.
doctype_js = {
	"Opportunity": "public/js/opportunity.js",
	"Quotation": "public/js/quotation.js",
	"Sales Order": "public/js/sales_order.js",
	"Work Order": "public/js/work_order.js",
}

doc_events = {
	"Quotation": {
		"validate": "arinox_apparel.overrides.quotation.validate",
		"on_submit": "arinox_apparel.overrides.quotation.on_submit",
	},
	"Sales Order": {
		"validate": "arinox_apparel.overrides.sales_order.validate",
		"on_submit": "arinox_apparel.overrides.sales_order.on_submit",
		"on_cancel": "arinox_apparel.overrides.sales_order.on_cancel",
	},
	# Phase B: bulk gate (G3)
	"Work Order": {
		"validate": "arinox_apparel.overrides.work_order.validate",
		"before_submit": "arinox_apparel.overrides.work_order.before_submit",
	},
}

override_doctype_dashboards = {
	"Opportunity": "arinox_apparel.overrides.dashboards.opportunity",
	"Quotation": "arinox_apparel.overrides.dashboards.quotation",
	"Customer": "arinox_apparel.overrides.dashboards.customer",
	"Sales Order": "arinox_apparel.overrides.dashboards.sales_order",
}
