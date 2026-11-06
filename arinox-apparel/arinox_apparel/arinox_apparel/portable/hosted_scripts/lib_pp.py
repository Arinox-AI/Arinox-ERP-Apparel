# shared helpers from pp_meeting.py: the departments that must attend, the buyer comments still open on a style, and the open cutting actions
def required_departments(meeting_type, is_washed):
    """Departments that must attend, from Apparel Settings (one per line). Washing joins when the garment is washed."""
    field = "pilot_required_departments" if meeting_type == "Pilot Run" else "pp_required_departments"
    default = "Cutting\nSewing\nQC\nCAD" if meeting_type == "Pilot Run" else "Planning\nPurchasing\nCutting\nSewing\nQC"
    names = [d.strip() for d in (frappe.db.get_single_value("Apparel Settings", field) or default).splitlines() if d.strip()]
    if frappe.utils.cint(is_washed) and meeting_type != "Pilot Run" and "Washing" not in names:
        names.append("Washing")
    return names


def open_buyer_comments(sales_order, style_item):
    """Open comments on every sample of this style that applies to the order (each a dict)."""
    rows = []
    for s in frappe.get_all("Sample Approval", filters=scope_filters(sales_order, style_item), fields=["name", "sample_type", "colour"]):
        for c in frappe.get_all("Sample Approval Comment", filters={"parent": s.name, "parenttype": "Sample Approval", "status": "Open"},
                                fields=["name", "category", "comment", "relevant_to_cutting"]):
            d = dict(c)
            d["sample_approval"] = s.name
            d["sample_type"] = s.sample_type
            d["colour"] = s.colour
            rows.append(d)
    return rows


def cutting_actions_open(sales_order, style_item):
    """[PP meetings held, open cutting-related actions]. Actions of pilot runs count too; only a PP Meeting counts as the meeting being held."""
    open_rows = []
    all_meetings = frappe.get_all("PP Meeting", filters={"sales_order": sales_order, "style_item": style_item, "docstatus": 1}, fields=["name", "meeting_type"])
    meetings = [m for m in all_meetings if m.meeting_type == "PP Meeting"]
    for m in all_meetings:
        open_rows = open_rows + frappe.get_all("PP Meeting Action", filters={"parent": m.name, "relevant_to_cutting": 1, "status": "Open"}, fields=["comment"])
    return [meetings, open_rows]
