# Shipment (Before Save): container numbers, chargeable weight and volume, destination filings.
# Written for the Server Script sandbox: no import, no class, no .format, no += on items or attributes.


def iso6346_ok(code):
    """ISO 6346 container number: 4 letters, 6 digits and a check digit."""
    code = (code or "").replace(" ", "").replace("-", "").upper()
    if len(code) != 11 or not code[4:].isdigit() or not code[:4].isalpha():
        return False
    values = {}
    n = 10
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if n % 11 == 0:
            n = n + 1
        values[ch] = n
        n = n + 1
    total = 0
    for i in range(10):
        v = values[code[i]] if i < 4 else int(code[i])
        total = total + v * (2 ** i)
    return (total % 11) % 10 == int(code[10])


u = frappe.utils

# 1. container numbers: warn, never block (a mistyped number is fixed on the bill of lading)
for c in doc.get("apparel_containers") or []:
    if c.container_no and c.container_type != "LCL part" and c.container_type != "Air ULD" and not iso6346_ok(c.container_no):
        frappe.msgprint(f"Container {c.container_no} does not pass the ISO 6346 check digit. Check it against the bill of lading.", indicator="orange")

# 2. chargeable weight (air) and volume (sea): the greater of actual and volumetric
divisor = u.flt(frappe.db.get_single_value("Apparel Settings", "air_volumetric_divisor")) or 6000
gross = 0
volume_cm3 = 0
for p in doc.get("shipment_parcel") or []:
    count = u.cint(p.count)
    gross = gross + u.flt(p.weight) * count
    volume_cm3 = volume_cm3 + u.flt(p.length) * u.flt(p.width) * u.flt(p.height) * count
mode = doc.get("apparel_mode") or ""
if mode == "Air":
    doc.apparel_chargeable_kg = round(max(gross, volume_cm3 / divisor), 2)
elif mode.startswith("Sea"):
    doc.apparel_chargeable_cbm = round(max(volume_cm3 / 1000000.0, gross / 1000.0), 3)

# 3. destination filings: one row per enabled rule that applies to this country, mode and incoterm
country = doc.get("apparel_destination_country")
if country and mode:
    have = [r.rule for r in (doc.get("apparel_filings") or []) if r.rule]
    for rule in frappe.get_all("Destination Filing Rule", {"enabled": 1, "country": country},
                               ["name", "filing_name", "mode", "hours_before_loading", "incoterms", "filed_by"]):
        if rule.name in have:
            continue
        mode_ok = (not rule.mode) or rule.mode == "Any" or mode.startswith(rule.mode)
        wanted = [x.strip() for x in (rule.incoterms or "").split(",") if x.strip()]
        if mode_ok and ((not wanted) or (doc.get("incoterm") in wanted)):
            due = None
            if doc.get("apparel_cutoff"):
                due = u.add_to_date(doc.apparel_cutoff, hours=-u.cint(rule.hours_before_loading))
            doc.append("apparel_filings", {"rule": rule.name, "filing_name": rule.filing_name, "due_by": due, "filed_by": rule.filed_by})

late = []
now = u.now_datetime()
for r in doc.get("apparel_filings") or []:
    if r.due_by and not r.filed_on and u.get_datetime(r.due_by) < now:
        late.append(r.filing_name)
if late:
    frappe.msgprint("Filing overdue: " + ", ".join(late), indicator="red", title="Destination filings")
