# _platform · API arinox_ping — tells Cortex Tower that Server Scripts run natively on this ERP.
# Read-only. Spec: cortex-tower/prompts/2026-11-12_erp_native_scripts_and_modules.md §1.
frappe.response["message"] = {"native": True, "scripts": frappe.db.count("Server Script", {"disabled": 0}), "version": "2026-11-12"}
