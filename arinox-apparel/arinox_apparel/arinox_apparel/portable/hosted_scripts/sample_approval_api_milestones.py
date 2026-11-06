# API arinox_sample_approval_get_sampling_milestones: sampling dates and status per style x colour of an order, for the T&A / WIP sheet or the planning
# agent: each sample type's due date, first sent date, last decision date and status, with the round-by-round history.
def main():
    # include: lib_samples.py
    # include: lib_allocation.py
    sales_order = frappe.form_dict.get("sales_order")
    frappe.new_doc("Sample Approval").check_permission("read")
    order = get_order_lines(sales_order)
    out = []
    for k in order:
        o = order[k]
        style = o["style_item"]
        if [r for r in out if r["style_item"] == style and norm(r["colour"]) == norm(o["colour"])]:
            continue
        row = {"style_item": style, "colour": o["colour"], "samples": {}}
        for smp in frappe.get_all("Sample Approval", filters=scope_filters(sales_order, style),
                                  fields=["name", "sample_type", "colour", "status", "due_date", "submitted_on", "approved_on", "late_chargeback"]):
            if smp.colour and norm(smp.colour) != norm(o["colour"]):
                continue
            rounds = frappe.get_all("Sample Approval Round", filters={"parent": smp.name}, fields=["round_no", "sent_on", "decision", "decision_on"], order_by="round_no")
            item = dict(smp)
            item["rounds"] = rounds
            if smp.sample_type not in row["samples"]:
                row["samples"][smp.sample_type] = []
            row["samples"][smp.sample_type].append(item)
        out.append(row)
    frappe.flags.arinox_result = out


main()
