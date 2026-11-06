# API arinox_pp_meeting_get_buyer_comments: add an action row for every open buyer comment of the style that is not on the list yet (answers the rows for the form).
def main():
    # include: lib_samples.py
    # include: lib_pp.py
    d = json.loads(frappe.form_dict.get("doc") or "{}")
    actions = list(d.get("actions") or [])
    listed = [a.get("comment_ref") for a in actions if a.get("comment_ref")]
    added = 0
    for c in open_buyer_comments(d.get("sales_order"), d.get("style_item")):
        if c["name"] in listed:
            continue
        label = c["sample_type"] + (" / %s" % c["colour"] if c["colour"] else "")
        actions.append({"sample_approval": c["sample_approval"], "comment_ref": c["name"], "source": "Buyer Comment", "category": c["category"],
                        "comment": "[%s] %s" % (label, c["comment"]), "relevant_to_cutting": c["relevant_to_cutting"]})
        added = added + 1
    frappe.flags.arinox_result = {"arinox_doc": {"actions": actions}, "count": added}


main()
