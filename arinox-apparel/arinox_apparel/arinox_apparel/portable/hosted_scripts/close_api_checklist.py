# API arinox_close_get_checklist: the commercial-close checklist of an order.
def main():
    # include: lib_close.py
    frappe.get_doc("Sales Order", frappe.form_dict.get("sales_order")).check_permission("read")
    frappe.flags.arinox_result = [{"label": r[0], "ok": r[1], "detail": r[2]} for r in checklist(frappe.form_dict.get("sales_order"))]


main()
