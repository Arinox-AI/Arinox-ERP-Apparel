# API arinox_sample_approval_load_standard_tests: add the standard test list from Apparel Settings (one test per line) to the unsaved form.
def main():
    d = json.loads(frappe.form_dict.get("doc") or "{}")
    names = (frappe.db.get_single_value("Apparel Settings", "gpt_test_list") or "").splitlines()
    tests = [t for t in (d.get("tests") or [])]
    have = [t.get("test_property") for t in (d.get("tests") or [])]
    for name in [n.strip() for n in names]:
        if name and name not in have:
            tests.append({"test_property": name})
            have.append(name)
    frappe.flags.arinox_result = {"arinox_doc": {"tests": tests}, "count": len(tests)}


main()
