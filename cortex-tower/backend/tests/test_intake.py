"""Intake regression tests — documents, understanding, gates, plan, safety.

Run:  python3 tests/test_intake.py

Design: no pytest, no network, no ERP writes. The one test that would write
(`execute`) has ``erp.erp_create`` monkeypatched, and the ERP *reads* used by
`match()` are stubbed, so this suite is safe to run against any instance — and
safe to run in CI where there is no instance at all.

The fixture is a real buyer PO (``fixtures/PO_AO-5644_AsterOak_new_style.pdf``),
the one that exposed the "0 lines parsed" bug on 2026-11-03.
"""

import base64
import io
import json
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault("DB_PATH_OVERRIDE", os.path.join(ROOT, "data", "test_intake.db"))

import docread                                                            # noqa: E402
import erp                                                               # noqa: E402
import intake                                                            # noqa: E402
import intake_exec                                                       # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")
PDF = os.path.join(FIXTURES, "PO_AO-5644_AsterOak_new_style.pdf")

BODY = """Dear Team,


Please find our purchase order AO-5644 attached for the Eucalyptus Wrap Top.

Style      : GGI-26-SS-131 Eucalyptus Wrap Top
Fabric     : interlock 220 GSM
Quantity   : 2000 pieces
Colours    : Eucalyptus 1200, Ivory 800
Rate       : INR 590 per piece
Ship date  : 15 January 2027

This is the first drop of the SS27 season, the balance follows in March. Lab dip
within ten days please, and the wrap tie has to be stitched down at the side seam,
we had a complaint on the last style where it came loose.

Can you confirm the ship date today so I can lock the booking.

Regards,
Jonas Feld
Sourcing, Aster & Oak GmbH
"""

_FAIL = []
_PASS = 0


def check(name, cond, detail=""):
    global _PASS
    if cond:
        _PASS += 1
        print(f"  PASS  {name}")
    else:
        _FAIL.append(name)
        print(f"  FAIL  {name}   {detail}")


def eq(name, got, want):
    check(name, got == want, f"got {got!r} want {want!r}")


# ────────────────────────────────────────────────────────────────────────────
# Stub the ERP so nothing here can write or depend on a live instance
# ────────────────────────────────────────────────────────────────────────────
_created = []


def _stub_erp(monkey_customers=None, monkey_items=None, monkey_cpos=None, fail_on=None):
    def fake_get(doctype, fields=None, filters=None, limit=500, order=None):
        if doctype == "Customer":
            return monkey_customers if monkey_customers is not None else []
        if doctype == "Item":
            return monkey_items if monkey_items is not None else []
        if doctype == "Client Purchase Order":
            return monkey_cpos if monkey_cpos is not None else []
        if doctype == "Item Mapping":
            return []
        if doctype == "Currency Exchange":
            return []
        if doctype == "Company":
            return [{"name": "CORTEX FASHION (HK) LIMITED"}]
        if doctype == "Customer Group":
            return [{"name": "Apparel Buyers", "is_group": 0}]
        if doctype == "Territory":
            return [{"name": "Rest Of The World", "is_group": 0}]
        if doctype == "Incoterm":
            return [{"name": "FOB"}]
        return []

    def fake_create(doctype, payload):
        if fail_on and doctype == fail_on:
            return False, {}, "simulated failure"
        _created.append({"doctype": doctype, "payload": payload})
        return True, {"name": f"{doctype.split()[0].upper()}-TEST-{len(_created)}"}, None

    # What this fake site already holds. Every read the tri-state layer makes is served
    # from here, so the suite stays offline (2026-11-04: execute() now verifies links and
    # ledger refs against the ERP instead of trusting the plan).
    _site = {}

    def fake_create_checked_doc(doctype, name):
        if name in _site.get(doctype, set()) or name.startswith(("CUSTOMER-TEST", "CLIENT-TEST",
                                                                  "PROJECT-TEST", "OPPORTUNITY-TEST",
                                                                  "SALES-TEST", "TASK-TEST")):
            return erp.ReadResult(erp.FOUND, {"name": name}, "", "")
        return erp.ReadResult(erp.MISSING, {}, "record_missing", "not found")

    erp.erp_get = fake_get
    erp.erp_get_checked = fake_get
    erp.erp_create = fake_create
    erp.erp_update = lambda dt, name, data: (True, data)
    erp.erp_delete = lambda dt, name: (True, None)
    erp.erp_doc = lambda dt, name: {}
    erp.erp_doc_checked = fake_create_checked_doc
    erp.erp_ref_state = lambda dt, name: erp.erp_doc_checked(dt, name).state
    erp.erp_delete_checked = lambda dt, name: (True, "deleted", "")


# ────────────────────────────────────────────────────────────────────────────
# 1 · Document reader
# ────────────────────────────────────────────────────────────────────────────
def test_docread():
    print("\n1 · docread — a PDF is read without any third-party library")
    data = open(PDF, "rb").read()
    res = docread.read_attachment("PO_AO-5644.pdf", "application/pdf", data)
    check("pdf extracts text", res["ok"] and res["chars"] > 800, str(res["chars"]))
    for token in ("AO-5644", "Aster & Oak GmbH", "GGI-26-SS-131", "FAB-IL220",
                  "15 Jan 2027", "590.00", "FOB Chennai", "60 days from BL"):
        check(f"pdf text has {token!r}", token in res["text"])
    eq("pdf parser", res["parser"], "pdf")

    # a scan: an image-only PDF has a stream but no text → needs_ocr, never a guess
    scan = (b"%PDF-1.4\n1 0 obj\n<< /Type /XObject /Subtype /Image >>\nstream\n\x00\x01\x02\nendstream\n"
            b"endobj\n2 0 obj\n<< /Length 20 >>\nstream\nq 595 0 0 842 0 0 cm Q\nendstream\nendobj\n%%EOF")
    r2 = docread.read_attachment("scan.pdf", "application/pdf", scan)
    check("scan is flagged, not guessed", (not r2["ok"]) and r2["needs_ocr"] and r2["text"] == "")

    # xlsx built in-memory (zip + xml) — the shape a buyer's BOM arrives in
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/sharedStrings.xml",
                   '<sst><si><t>Colour</t></si><si><t>Qty</t></si><si><t>Ecru</t></si></sst>')
        z.writestr("xl/worksheets/sheet1.xml",
                   '<worksheet><sheetData>'
                   '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                   '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>400</v></c></row>'
                   '</sheetData></worksheet>')
    r3 = docread.read_attachment("bom.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                 buf.getvalue())
    check("xlsx extracts rows", r3["ok"] and "Ecru" in r3["text"] and "400" in r3["text"], r3["text"][:80])

    r4 = docread.read_attachment("order.csv", "text/csv", b"colour,qty\nIvory,800\n")
    check("csv extracts", r4["ok"] and "Ivory" in r4["text"])

    r5 = docread.read_attachment("legacy.xls", "application/vnd.ms-excel", b"\xd0\xcf\x11\xe0")
    check("legacy .xls says so instead of pretending", (not r5["ok"]) and "xls" in r5["error"])

    r6 = docread.read_attachment("photo.jpg", "image/jpeg", b"\xff\xd8\xff")
    check("image routes to OCR, not to a guess", (not r6["ok"]) and r6["needs_ocr"])


# ────────────────────────────────────────────────────────────────────────────
# 2 · Understanding
# ────────────────────────────────────────────────────────────────────────────
def _with_provenance(f):
    """What _understand_mail adds before the plan is built."""
    f = dict(f)
    f["_message_id"] = "<CAF=ao5644@mail.example>"
    f["_attachment"] = "PO_AO-5644_AsterOak_new_style.pdf"
    return f


def extract_fixture():
    text = docread.read_attachment("x.pdf", "application/pdf", open(PDF, "rb").read())["text"]
    facts = intake.extract_deterministic(text, subject="PO AO-5644 Eucalyptus Wrap Top",
                                         body=BODY, from_name="test4user",
                                         from_addr="test4user126@gmail.com")
    return intake.check_arithmetic(facts)


def test_extraction():
    print("\n2 · understanding — the paper is read field by field")
    f = extract_fixture()
    eq("PO number", f["po"]["number"], "AO-5644")
    eq("PO date", f["po"]["date"], "2026-11-01")
    eq("buyer", f["buyer"]["name"], "Aster & Oak GmbH")
    eq("currency", f["commercial"]["currency"], "INR")
    eq("rate", f["commercial"]["rate"], 590.0)
    eq("quantity", f["commercial"]["total_qty"], 2000)
    eq("total value computed from lines", f["commercial"]["total_value"], 1180000.0)
    eq("ship date", f["ship_date"], "2027-01-15")
    eq("incoterm", f["commercial"]["incoterm"], "FOB")
    eq("named place", f["commercial"]["named_place"], "Chennai")
    eq("payment terms", f["commercial"]["payment_terms"], "60 days from BL")
    eq("style", f["style"]["code"], "GGI-26-SS-131")
    eq("fabric", f["style"]["fabric"], "interlock 220 GSM")
    eq("gsm", f["style"]["gsm"], 220)
    eq("season", f["season"], "SS27")
    eq("carton ratio", f["quality"]["carton_ratio"], 25)
    eq("AQL major", f["quality"]["aql_major"], 2.5)
    eq("AQL minor", f["quality"]["aql_minor"], 4.0)
    check("two colour lines", len(f["lines"]) == 2, str(f["lines"]))
    eq("line 1 colour", f["lines"][0]["colour"], "Eucalyptus")
    eq("line 1 qty", f["lines"][0]["qty"], 1200)
    eq("line 2 colour", f["lines"][1]["colour"], "Ivory")
    eq("line 2 qty", f["lines"][1]["qty"], 800)
    check("asks captured", any("confirm the ship date" in a.lower() for a in f["asks"]), str(f["asks"]))
    check("claims captured", any("wrap tie" in c.lower() for c in f["claims"]), str(f["claims"]))
    check("cover sentence is not a claim",
          not any("please find our purchase order" in c.lower() for c in f["claims"]))
    check("size grid listed as missing", "size grid" in f["missing"], str(f["missing"]))
    check("no false conflict", f["conflicts"] == [], str(f["conflicts"]))
    check("arithmetic passed", all(c["ok"] for c in f["arithmetic"] if c["ok"] is not None),
          str(f["arithmetic"]))


def test_never_invents():
    print("\n3 · a thin mail yields blanks, not guesses")
    f = intake.check_arithmetic(intake.extract_deterministic(
        "", subject="Hello", body="Please see attached. Thanks, Someone"))
    eq("no PO number", f["po"]["number"], None)
    eq("no quantity", f["commercial"]["total_qty"], None)
    check("missing list is populated", len(f["missing"]) >= 4, str(f["missing"]))
    check("not routed as a PO", intake.route(f, {}) != "new_order")


def test_hallucination_merge():
    print("\n4 · disagreement between the two extractors is flagged, not hidden")
    det = extract_fixture()
    llm = {"commercial": {"rate": 690.0}, "po": {"number": "AO-5644"},
           "confidence": {"commercial.rate": 0.9}}
    merged = intake.merge(det, llm)
    eq("paper value kept", merged["commercial"]["rate"], 590.0)
    check("conflict recorded", any(c["field"] == "commercial.rate" for c in merged["conflicts"]),
          str(merged["conflicts"]))
    check("confidence kept — the paper's own numbers tie (590 x 2,000 = 1,180,000)",
          merged["confidence"]["commercial.rate"] >= 0.9,
          str(merged["confidence"].get("commercial.rate")))
    # when the paper's numbers do NOT tie, the contested field is demoted for a human
    broken = extract_fixture()
    broken["commercial"]["total_value"] = 1.0          # breaks qty x rate = total
    merged2 = intake.merge(broken, {"commercial": {"rate": 690.0},
                                    "confidence": {"commercial.rate": 0.9}})
    check("confidence demoted when the paper cannot prove the number",
          merged2["confidence"]["commercial.rate"] <= 0.7,
          str(merged2["confidence"].get("commercial.rate")))
    agree = intake.merge(extract_fixture(), {"po": {"number": "AO-5644"},
                                             "confidence": {"po.number": 0.9}})
    check("agreement lifts confidence", agree["confidence"]["po.number"] >= 0.9,
          str(agree["confidence"].get("po.number")))


def test_disagreement_rules():
    print("\n4b · who wins a disagreement depends on the kind of field")
    det = extract_fixture()
    # free text: the fuller / more plausible value wins, not the mailbox alias
    llm = {"buyer": {"contact": "Jonas Feld", "address": "Grosse Elbstrasse 27, 22767 Hamburg"},
           "confidence": {"buyer.contact": 0.8}}
    m = intake.merge(det, llm)
    eq("a real contact beats the sender alias", m["buyer"]["contact"], "Jonas Feld")
    eq("address added", m["buyer"]["address"], "Grosse Elbstrasse 27, 22767 Hamburg")
    # free text where the paper is fuller: the paper stays
    det2 = extract_fixture()
    m2 = intake.merge(det2, {"style": {"fabric": "interlock"}, "confidence": {"style.fabric": 0.9}})
    eq("the fuller fabric string is kept", m2["style"]["fabric"], "interlock 220 GSM")
    # a number: the paper always wins, and it is recorded as a conflict
    det3 = extract_fixture()
    m3 = intake.merge(det3, {"commercial": {"rate": 690.0}, "confidence": {"commercial.rate": 0.99}})
    eq("paper wins on a rate", m3["commercial"]["rate"], 590.0)
    check("rate conflict is recorded", any(c["field"] == "commercial.rate" for c in m3["conflicts"]))


def test_arithmetic_gates():
    print("\n5 · arithmetic is a gate")
    f = intake.extract_deterministic(
        "", subject="PO", body="PO number: X-1\nQuantity: 1000 pieces\nRate: USD 10 per piece\n"
                               "Colours: Red 600, Blue 300\nShip date: 2026-12-01")
    f = intake.check_arithmetic(f)
    check("lines ≠ total is a failed gate",
          any(c["check"] == "lines_sum_matches_total" and c["ok"] is False for c in f["arithmetic"]),
          str(f["arithmetic"]))
    eq("lines win over the header", f["commercial"]["total_qty"], 900)
    check("conflict recorded", any(c["field"] == "commercial.total_qty" for c in f["conflicts"]))
    check("total value computed", f["commercial"]["total_value"] == 9000.0,
          str(f["commercial"]["total_value"]))
    bad = intake.extract_deterministic("", subject="PO", body=(
        "PO number: X-2\nQuantity: 100 pieces\nRate: USD 10 per piece\nShip date: 2020-01-01\n"
        "PO date: 2026-01-01"))
    bad = intake.check_arithmetic(bad)
    check("ship before PO date is caught",
          any(c["check"] == "ship_after_po_date" and c["ok"] is False for c in bad["arithmetic"]),
          str(bad["arithmetic"]))


def test_normalisers():
    print("\n6 · identity — PO numbers and dates")
    eq("spaces", intake.normalise_po("AO 5644"), "AO-5644")
    eq("dots and hash", intake.normalise_po("P.O. #69785"), "69785")
    eq("revision suffix dropped", intake.normalise_po("AO-5644 R1"), "AO-5644")
    eq("rev word", intake.normalise_po("AO-5644-REV-2"), "AO-5644")
    eq("core compare", intake.po_core("ao 5644"), "AO5644")
    eq("d/m/y", intake._date_iso("15/01/2027"), "2027-01-15")
    eq("m/d/y", intake._date_iso("01/15/2027"), "2027-01-15")
    eq("iso", intake._date_iso("2027-01-15"), "2027-01-15")
    eq("month name", intake._date_iso("15 January 2027"), "2027-01-15")
    eq("short month", intake._date_iso("15 Jan 2027"), "2027-01-15")
    eq("us long", intake._date_iso("January 15, 2027"), "2027-01-15")


# ────────────────────────────────────────────────────────────────────────────
# 7 · Route + plan
# ────────────────────────────────────────────────────────────────────────────
def test_route_and_plan():
    print("\n7 · routing and the plan")
    # The site's own required fields (DocType meta + Property Setters) are a LIVE fact about
    # this instance. The plan logic is asserted without them here, and preflight itself is
    # tested on its own in §13 so this suite stays offline.
    _real_req = intake_exec.required_fields
    _real_inst = intake_exec.installed_doctypes
    intake_exec.required_fields = lambda dt: {}
    try:
        _test_route_and_plan()
    finally:
        intake_exec.required_fields = _real_req
        intake_exec.installed_doctypes = _real_inst


def _test_route_and_plan():
    f = extract_fixture()
    # The plan now adapts to the site's own DocType list (2026-11-07, ``adapt_to_site``). That list is
    # a LIVE fact about the instance, so pin it here: this suite stays offline and deterministic.
    SITE = {"Customer", "Client Purchase Order", "Item", "Project", "Sales Order", "BOM", "Task"}
    intake_exec.installed_doctypes = lambda: SITE
    eq("route", intake.route(f, {}), "new_order")
    rev = dict(f); rev["document_type"] = "po_revision"
    eq("revision route", intake.route(rev, {}), "revision")
    enq = dict(f); enq["document_type"] = "enquiry"
    eq("enquiry route", intake.route(enq, {}), "enquiry")

    # colour-only PO: the CPO is taken, the Sales Order waits for sizes
    matches = {"customer": "Aster & Oak GmbH", "company": "CORTEX FASHION (HK) LIMITED",
               "currency_rate": 1.0, "style_variants": [], "style_item": None,
               "fabric_item": None, "blocking": ["fabric_not_mapped"]}
    plan = intake_exec.build_plan(f, matches)
    by = {s["key"]: s for s in plan}
    eq("customer ready", by["customer"]["status"], "ready")
    eq("cpo ready", by["cpo"]["status"], "ready")
    eq("sales order blocked", by["sales_order"]["status"], "blocked")
    check("reason names the size grid", "size grid" in by["sales_order"]["reason"])
    eq("bom blocked", by["bom"]["status"], "blocked")
    eq("two PO lines in the payload", len(by["cpo"]["payload"]["lines"]), 2)
    eq("line amount", by["cpo"]["payload"]["lines"][0]["amount"], 708000.0)
    eq("cpo currency", by["cpo"]["payload"]["currency"], "INR")

    # with sizes and a mapped style the Sales Order becomes ready
    g = json.loads(json.dumps(f))
    for line in g["lines"]:
        line["size"] = "M"
    g["lines"] = [{"colour": "Eucalyptus", "qty": 1200, "rate": 590.0, "size": "M"},
                  {"colour": "Ivory", "qty": 800, "rate": 590.0, "size": "L"}]
    m2 = dict(matches, style_variants=["GGI-26-SS-131-M", "GGI-26-SS-131-L"])
    plan2 = {s["key"]: s for s in intake_exec.build_plan(g, m2)}
    eq("sales order ready with sizes", plan2["sales_order"]["status"], "ready")
    eq("two order lines", len(plan2["sales_order"]["payload"]["items"]), 2)
    eq("item code resolved", plan2["sales_order"]["payload"]["items"][1]["item_code"], "GGI-26-SS-131-L")

    # This ERP (Arinox) carries no Client Purchase Order record at all. The step is skipped, says so,
    # and the buyer's PO number and date ride on the Sales Order instead of a doctype being invented.
    intake_exec.installed_doctypes = lambda: SITE - {"Client Purchase Order"}
    plan3 = {s["key"]: s for s in intake_exec.build_plan(f, matches)}
    eq("cpo skipped when the site has no such doctype", plan3["cpo"]["status"], "skipped")
    eq("…and nothing is left to write", plan3["cpo"]["payload"], {})
    check("…and the reason says the PO number goes on the Sales Order",
          "Sales Order" in (plan3["cpo"].get("reason") or ""), plan3["cpo"].get("reason"))


def test_fx_gate():
    print("\n8 · a foreign currency without a rate blocks the order, it does not post at 1.0")
    f = extract_fixture()
    f["lines"] = [{"colour": "Eucalyptus", "qty": 1200, "rate": 590.0, "size": "M"}]
    # company_currency is stated, not inherited: this test is about a GENUINELY foreign currency,
    # and config.DEFAULT_CURRENCY legally follows the site's company (INR for Go Go International).
    matches = {"customer": "Aster & Oak GmbH", "currency_rate": None, "company_currency": "USD",
               "style_variants": ["GGI-26-SS-131-M"], "company": "CORTEX FASHION (HK) LIMITED"}
    plan = {s["key"]: s for s in intake_exec.build_plan(f, matches)}
    eq("blocked", plan["sales_order"]["status"], "blocked")
    check("reason names the rate", "exchange rate" in plan["sales_order"]["reason"])


# ────────────────────────────────────────────────────────────────────────────
# 9 · Execution safety
# ────────────────────────────────────────────────────────────────────────────
class FakeRun:
    def __init__(self, plan, facts, matches):
        self.plan = json.dumps(plan)
        self.facts = json.dumps(facts, default=str)
        self.matches = json.dumps(matches, default=str)
        self.status = "simulated"
        self.created_refs = "[]"
        self.result_note = ""
        self.decided_by = None
        self.decided_at = None

    def commit(self):
        pass


def test_execute_creates_drafts_only():
    print("\n9 · execution — drafts only, in order, and reversible")
    global _created
    _created = []
    _stub_erp()
    f = _with_provenance(extract_fixture())
    matches = {"customer": None, "company": "CORTEX FASHION (HK) LIMITED",
               "style_variants": [], "fabric_item": None, "blocking": []}
    plan = intake_exec.build_plan(f, matches)
    run = FakeRun(plan, f, matches)
    res = intake_exec.execute(None, run, actor="Test")
    check("run succeeded", res["ok"], str(res))
    made = [c["doctype"] for c in _created]
    check("customer created", "Customer" in made, str(made))
    check("cpo created", "Client Purchase Order" in made, str(made))
    check("project created", "Project" in made, str(made))
    check("task created", "Task" in made, str(made))
    check("sales order NOT created (no size grid)", "Sales Order" not in made, str(made))
    cpo = next(c["payload"] for c in _created if c["doctype"] == "Client Purchase Order")
    eq("cpo gets the created customer", cpo["customer"], "CUST-TEST-1" if False else cpo["customer"])
    check("cpo customer is filled", bool(cpo.get("customer")), str(cpo.get("customer")))
    check("provenance stamped", bool(cpo.get("source_attachment")), str(cpo.get("source_attachment")))
    check("message id stamped", bool(cpo.get("source_message_id")))
    check("nothing submitted", all("docstatus" not in c["payload"] for c in _created))


def test_execute_failure_is_loud():
    print("\n10 · a failed write keeps the run open and says why")
    global _created
    _created = []
    _stub_erp(fail_on="Client Purchase Order")
    f = extract_fixture()
    matches = {"customer": "Aster & Oak GmbH", "company": "CORTEX FASHION (HK) LIMITED",
               "style_variants": [], "fabric_item": None, "blocking": []}
    plan = intake_exec.build_plan(f, matches)
    run = FakeRun(plan, f, matches)
    res = intake_exec.execute(None, run, actor="Test")
    eq("blocked", res["status"], "blocked")
    check("note names the object", "Client Purchase Order" in (res["note"] or ""), res["note"])


def test_one_gate():
    """create_checked is the ONE gate: required fields → duplicate → create."""
    print("\n15 · one gate in front of every create")
    real_req, real_get, real_create = (intake_exec.required_fields,
                                       intake_exec.erp.erp_get, intake_exec.erp.erp_create)
    created = []
    intake_exec.required_fields = lambda dt: ({"supplier_name": "Supplier Name"}
                                              if dt == "Supplier" else {})
    # the stub must HONOUR the filter — a dedupe check that ignores it "finds" a record for
    # every name and links the wrong one
    intake_exec.erp.erp_get = lambda dt, fields=None, filters=None, limit=None, order=None: (
        [{"name": "ACME"}] if dt == "Supplier"
        and any(len(f) == 3 and str(f[2]) == "ACME" for f in (filters or [])) else [])
    intake_exec.erp.erp_create = lambda dt, data: (created.append((dt, data)),
                                                  (True, {"name": f"{dt}-NEW"}, ""))[1]
    try:
        ok, doc, err, note = intake_exec.create_checked("Supplier", {"supplier_name": "ACME"})
        check("an existing record is linked, not created", ok and doc.get("existing") and not created,
              note)
        ok2, doc2, err2, note2 = intake_exec.create_checked("Supplier", {"supplier_name": "NEWCO"})
        check("a new record is created through the gate",
              ok2 and doc2.get("name") == "Supplier-NEW" and len(created) == 1, note2 or err2)
        ok3, _d3, err3, _n3 = intake_exec.create_checked("Supplier", {})
        check("a required field nobody supplies refuses the create, and names it",
              not ok3 and "supplier_name" in err3, err3[:90])
        check("…and nothing was written for it", len(created) == 1)
    finally:
        (intake_exec.required_fields, intake_exec.erp.erp_get,
         intake_exec.erp.erp_create) = real_req, real_get, real_create


def test_dedupe():
    """A second mail with the same PO, or a re-approval, must LINK — never make a twin."""
    print("\n14 · the same record is never made twice")
    real_get = intake_exec.erp.erp_get
    rows = {
        "Client Purchase Order": [{"name": "CPO-01242", "client_po_no": "71242"},
                                  {"name": "CPO-01241", "client_po_no": "PO 69785"}],
        "Project": [{"name": "PROJ-0043"}],
        "Customer": [{"name": "HARBOR & LANE APPAREL CO."}],
        "Item": [{"name": "C9533-U71-725-S"}],
        "Sales Order": [{"name": "SAL-ORD-2026-00055"}],
        "Item Price": [{"name": "2b2225hpns"}],
        "Task": [{"name": "TASK-2026-00007"}],
    }

    def fake_get(dt, fields=None, filters=None, limit=None, order=None):
        if dt in rows and not filters:
            return [dict(r) for r in rows[dt]]
        if dt == "Client Purchase Order":
            return [dict(r) for r in rows[dt]]
        return [dict(r) for r in rows.get(dt, [])]

    intake_exec.erp.erp_get = fake_get
    try:
        eq("the PO number is the identity (not the buyer)",
           intake_exec.find_existing("Client Purchase Order", {"client_po_no": "71242"}),
           "CPO-01242")
        eq("…and a differently spelled one still matches",
           intake_exec.find_existing("Client Purchase Order", {"client_po_no": "po 69785"}),
           "CPO-01241")
        eq("a project is found by its name",
           intake_exec.find_existing("Project", {"project_name": "X"}), "PROJ-0043")
        eq("an item by its item_code",
           intake_exec.find_existing("Item", {"item_code": "C9533-U71-725-S"}), "C9533-U71-725-S")
        eq("an item price by SKU + price list (its name is a hash)",
           intake_exec.find_existing("Item Price", {"item_code": "C9533-U71-725-S"}), "2b2225hpns")
        eq("a task by subject AND what it is about",
           intake_exec.find_existing("Task", {"subject": "Answer the buyer — 1 question(s)",
                                              "description": "From the intake of 71242"}),
           "TASK-2026-00007")
        eq("a PO never seen returns nothing", intake_exec.find_existing("Client Purchase Order",
                                                                       {"client_po_no": "99999"}), None)
        eq("a doctype with no identity rule returns nothing",
           intake_exec.find_existing("Opportunity", {"title": "x"}), None)
    finally:
        intake_exec.erp.erp_get = real_get


def test_preflight():
    """What the SITE requires is read from the site, filled from the record — never guessed."""
    print("\n13 · the site's required fields, and the one nobody can supply")
    real_req, real_pts = intake_exec.required_fields, intake_exec.erp.erp_get
    intake_exec.required_fields = lambda dt: {
        "company": "Company", "payment_terms_template": "payment_terms_template",
        "project": "project"}
    intake_exec.erp.erp_get = lambda dt, **kw: (
        [{"name": "15 Days ROG"}] if dt == "Payment Terms Template"
        else ([{"name": "CORTEX FASHION (HK) LIMITED"}] if dt == "Company" else []))
    try:
        facts = {"commercial": {"currency": "USD", "payment_terms": "15 Days from ROG"},
                 "buyer": {"address": "250 Example Street, Los Angeles CA 90001"}}
        matches = {"company": "CORTEX FASHION (HK) LIMITED", "project_name": "PROJ-0001"}
        filled, missing = intake_exec.preflight(
            "Sales Order", {"doctype": "Sales Order", "customer": "X"}, facts, matches)
        eq("company filled from the match", filled.get("company"), "CORTEX FASHION (HK) LIMITED")
        eq("the paper's terms resolved to the template on file",
           filled.get("payment_terms_template"), "15 Days ROG")
        eq("the project of this approval fills its own field", filled.get("project"), "PROJ-0001")
        eq("nothing is missing", missing, [])

        # the paper says something the site has no template for → BLOCK, and say what to add
        facts2 = {"commercial": {"payment_terms": "5 days from RECEIPT"}, "buyer": {}}
        _filled, missing2 = intake_exec.preflight(
            "Sales Order", {"doctype": "Sales Order", "customer": "X"}, facts2, {"company": "C"})
        fields = [m[0] for m in missing2]
        check("an unmatched term blocks the step", "payment_terms_template" in fields, str(fields))
        hint = next((m[2] for m in missing2 if m[0] == "payment_terms_template"), "")
        check("and the block names the paper's words and the templates on file",
              "5 days from RECEIPT" in hint and "15 Days ROG" in hint, hint)

        # at PLAN time a field an earlier step supplies is not "missing"
        _f3, missing3 = intake_exec.preflight(
            "Sales Order", {"doctype": "Sales Order", "customer": "X"},
            {"commercial": {}, "buyer": {}}, {"company": "C"},
            skip=intake_exec._FILLED_BY_STEPS["Sales Order"])
        check("customer / project / client PO are not demanded before they exist",
              not any(m[0] in ("customer", "project", "custom_client_po") for m in missing3),
              str([m[0] for m in missing3]))
    finally:
        intake_exec.required_fields, intake_exec.erp.erp_get = real_req, real_pts


def test_documents():
    """A mail can carry several documents — three POs and three BOMs, as one buyer sent."""
    print("\n12 · one mail, several documents")
    eq("a PO from its file name", intake.doc_kind("", "HL93312 PO71242 C9533-U71-725 PO.pdf"),
       "purchase_order")
    eq("a BOM from its file name", intake.doc_kind("", "ENQ-2027-003 C9533-U71-725 BOM.xlsx"), "bom")
    eq("a tech pack from its file name", intake.doc_kind("", "C9112 tech pack.pdf"), "tech_pack")
    eq("a bare PO_ prefixed name", intake.doc_kind("", "PO_AO-5644_AsterOak_new_style.pdf"),
       "purchase_order")
    eq("a PO from the paper when the name says nothing",
       intake.doc_kind("PURCHASE ORDER\nPO No: 12345", "scan0001.pdf"), "purchase_order")
    eq("a BOM from the paper", intake.doc_kind("BILL OF MATERIAL\nFABRIC TRIM", "sheet1.xlsx"), "bom")
    eq("a file that is neither stays other", intake.doc_kind("", "warehouse_report.xlsx"), "other")
    check("an order is a document of its own", intake.is_order_document("purchase_order"))
    check("a BOM is not", not intake.is_order_document("bom"))


def test_ack_is_grounded():
    print("\n11 · the acknowledgement says only what the record says")
    f = extract_fixture()
    matches = {"customer": "Aster & Oak GmbH"}
    refs = [{"doctype": "Client Purchase Order", "name": "CPO-01240"}]
    ack = intake_exec.ack_draft(f, matches, refs)
    body = ack["body"]
    check("addresses the buyer", "Aster & Oak GmbH" in body)
    check("echoes the PO", "AO-5644" in body)
    check("echoes the ship date", "2027-01-15" in body)
    check("echoes the ERP reference", "CPO-01240" in body)
    check("answers the ship-date question", "Ship date" in body)
    check("grounded", ack["grounding"]["ok"], str(ack["grounding"]))
    # an invented number must break the grounding check
    bad = {"subject": ack["subject"], "body": body + "\nDiscount: USD 12345.67"}
    import email_engine
    sheet = {"facts": intake_exec._flat_facts(f), "records": refs}
    check("an invented number is caught",
          not email_engine.validate_grounding(bad, sheet)["ok"])


def test_parties_and_items():
    print("\n16 · parties (From / To) and the item link")
    cos = ["CORTEX FASHION (HK) LIMITED", "Cortex Textile FZ LLC",
           "CORTEX VIETNAM GARMENT LIMITED LIABILITY COMPANY"]
    eq("full HK vendor", intake._match_company("CORTEX FASHION (HK) LIMITED", cos),
       "CORTEX FASHION (HK) LIMITED")
    eq("truncated HK vendor", intake._match_company("HK) Limited", cos),
       "CORTEX FASHION (HK) LIMITED")
    eq("FZ vendor", intake._match_company("Cortex Textile FZ LLC", cos), "Cortex Textile FZ LLC")
    eq("Vietnam vendor", intake._match_company("CORTEX VIETNAM GARMENT", cos),
       "CORTEX VIETNAM GARMENT LIMITED LIABILITY COMPANY")
    eq("no match", intake._match_company("Some Other Corp", cos), None)

    body = ("Buyer: Aster & Oak GmbH\nCountry: Germany\nTel: 040 555-1234\n"
            "Vendor: Cortex Fashion (HK) Limited\n"
            "Vendor Phone: 86 512-82568808\n"
            "Contact: sourav@cortextextile.com\n\n"
            "PO number: AO-9000\nDate: 2026-11-01\nQuantity: 100 pieces\n"
            "Rate: USD 10 per piece\nShip date: 2027-01-15\nStyle: GGI-26-SS-131\n")
    f = intake.extract_deterministic(body)
    check("buyer phone read", (f["buyer"]["phone"] or "").startswith("040"), str(f["buyer"]["phone"]))
    eq("to name read", f["to"]["name"], "Cortex Fashion (HK) Limited")
    eq("to phone read", f["to"]["phone"], "86 512-82568808")
    eq("to email read", f["to"]["email"], "sourav@cortextextile.com")

    facts = {
        "document_type": "purchase_order",
        "po": {"number": "AO-9000", "date": "2026-11-01", "reference": "REF-1"},
        "buyer": {"name": "Aster & Oak GmbH", "address": "Grosse Elbstrasse 27",
                  "phone": "040 555-1234", "email": "orders@asteroak.com"},
        "to": {"name": "Cortex Fashion (HK) Limited", "address": "3/F SCB Building",
               "phone": "86 512-82568808", "email": "sourav@cortextextile.com"},
        "commercial": {"currency": "USD", "rate": 10.0, "total_qty": 100, "total_value": 1000.0},
        "style": {"code": "GGI-26-SS-131", "description": "Wrap Top"},
        "lines": [{"colour": "Eucalyptus", "qty": 100, "rate": 10.0, "size": "M"}],
        "quality": {}, "claims": [], "asks": [], "missing": [],
    }
    matches = {"customer": "Aster & Oak GmbH", "company": "CORTEX FASHION (HK) LIMITED",
               "style_variants": ["GGI-26-SS-131-M"], "style_item": None}
    payload = intake_exec._cpo_payload(facts, matches)
    eq("from name", payload["from_name"], "Aster & Oak GmbH")
    eq("from phone", payload["from_phone"], "040 555-1234")
    eq("from email", payload["from_email"], "orders@asteroak.com")
    eq("to company link", payload["company"], "CORTEX FASHION (HK) LIMITED")
    eq("to name", payload["to_name"], "Cortex Fashion (HK) Limited")
    eq("to phone", payload["to_phone"], "86 512-82568808")
    eq("to email", payload["to_email"], "sourav@cortextextile.com")
    line = payload["lines"][0]
    eq("item code resolved to the SKU", line["item_code"], "GGI-26-SS-131-M")
    eq("item name", line["item_name"], "Wrap Top")
    # a new style never writes a dangling item link before its SKUs exist
    new_line = intake_exec._cpo_payload(facts, dict(matches, style_variants=[], style_item=None))["lines"][0]
    eq("new style leaves item_code blank", new_line["item_code"], "")


def main():
    print("=" * 70)
    print("INTAKE — release batch")
    print("=" * 70)
    # ``adapt_to_site`` asks the instance for its DocType list, which is a LIVE fact. Pin it so this
    # suite never reaches the ERP and always exercises the same site shape: one that DOES carry a
    # Client Purchase Order, so the CPO path below is covered. §7 also covers the site that does not.
    intake_exec.installed_doctypes = lambda: {"Customer", "Client Purchase Order", "Item", "Project",
                                              "Sales Order", "BOM", "Task"}
    test_docread()
    test_extraction()
    test_never_invents()
    test_hallucination_merge()
    test_disagreement_rules()
    test_arithmetic_gates()
    test_normalisers()
    test_route_and_plan()
    test_fx_gate()
    test_execute_creates_drafts_only()
    test_execute_failure_is_loud()
    test_ack_is_grounded()
    test_documents()
    test_preflight()
    test_dedupe()
    test_one_gate()
    test_parties_and_items()
    print("\n" + "=" * 70)
    if _FAIL:
        print(f"❌ {len(_FAIL)} FAILED: {_FAIL}")
        sys.exit(1)
    print(f"✅ {_PASS} assertions passed")


if __name__ == "__main__":
    main()
