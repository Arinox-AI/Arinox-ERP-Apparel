# Scheduler (daily): remind about credits that expire or must be presented soon.
u = frappe.utils
today = u.getdate(u.nowdate())
for lc in frappe.get_all("Letter of Credit", {"status": "Open"}, ["name", "lc_no", "expiry_date", "presentation_deadline", "owner"]):
    for label, day, within in (("expires", lc.expiry_date, 14), ("documents must be presented", lc.presentation_deadline, 5)):
        if not day:
            continue
        left = u.date_diff(day, today)
        if 0 <= left <= within:
            marker = f"[lc-{lc.name}-{label}-{day}]"
            if not frappe.db.exists("ToDo", {"reference_type": "Letter of Credit", "reference_name": lc.name, "description": ["like", "%" + marker + "%"]}):
                frappe.get_doc({"doctype": "ToDo", "allocated_to": lc.owner, "reference_type": "Letter of Credit", "reference_name": lc.name,
                                "description": f"L/C {lc.lc_no} {label} in {left} day(s), on {day}. {marker}"}).insert(ignore_permissions=True)
