# API arinox_pp_meeting_add_standard_participants: a row for every required department that is not on the attendance list yet.
def main():
    # include: lib_pp.py
    d = json.loads(frappe.form_dict.get("doc") or "{}")
    rows = list(d.get("participants") or [])
    have = [p.get("department") for p in rows]
    for dept in required_departments(d.get("meeting_type") or "PP Meeting", d.get("is_washed")):
        if dept not in have:
            rows.append({"department": dept, "attended": 0})
    frappe.flags.arinox_result = {"arinox_doc": {"participants": rows}, "count": len(rows)}


main()
