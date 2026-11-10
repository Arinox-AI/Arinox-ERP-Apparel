#!/usr/bin/env python3
"""The client's own PO form — thirteen real papers, read without a model.

Every PO in the client's corpus is printed on one vendor form. Before this reader
existed the deterministic pass read the EM cross-reference as the PO number and the
FABRIC price as the garment rate, and threw the size grid away (2026-11-03). These
assertions are the regression: if the form reader breaks, the demo breaks, because
the rest of the pipeline trusts ``extract_deterministic``.

Run:  python3 tests/test_po_form.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import docread          # noqa: E402
import intake           # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
PO_DIR = os.path.join(ROOT, "data", "arinox_new", "ARINOX ERP DOCS",
                      "1 - Merchandising", "10 - Client Purchase Order")

# paper → (PO, PO date, style, qty, rate, value, ship, grid)
PAPERS = {
    "EM92409 09.12.25 CTX C2027-S84-304 PO69785.pdf":
        ("69785", "2025-09-09", "C2027-S84-304", 1462, 16.30, 23830.60, "2026-01-30",
         {"XS": 270, "S": 436, "M": 421, "L": 223, "XL": 112}),
    "EM92412 09.12.25 CTX C4878-H96-304 PO69788.pdf":
        ("69788", "2025-09-09", "C4878-H96-304", 1700, 15.30, 26010.00, "2026-01-30",
         {"XS": 320, "S": 520, "M": 486, "L": 252, "XL": 122}),
    "EM92419 12.03.25 CTX C7540-S99-304 PO70415.pdf":
        ("70415", "2025-12-03", "C7540-S99-304", 1600, 23.00, 36800.00, "2026-04-24",
         {"XS": 303, "S": 503, "M": 479, "L": 259, "XL": 56}),
    "EM92420 12.11.25 CTX C7540-S99-304 PO70465.pdf":
        ("70465", "2025-12-11", "C7540-S99-304", 250, 23.00, 5750.00, "2026-04-26",
         {"XS": 44, "S": 84, "M": 68, "L": 54}),
    "EM92422 1.20.26 CTX C7502-S14-304 PO70599 REVISION.pdf":
        ("70599", "2026-01-20", "C7502-S14-304", 1271, 13.50, 17158.50, "2026-06-08",
         {"XXS": 114, "XS": 178, "S": 330, "M": 408, "L": 165, "XL": 76}),
    "EM92423 1.20.26 CTX C7502-S14-304 PO70601 REVISION.pdf":
        ("70601", "2026-01-20", "C7502-S14-304", 3800, 13.50, 51300.00, "2026-06-08",
         {"XXS": 145, "XS": 320, "S": 480, "M": 2310, "L": 415, "XL": 130}),
    "EM92424 1.20.26 CTX C7502-S14-304 PO70602 REVISION.pdf":
        ("70602", "2026-01-20", "C7502-S14-304", 16, 13.50, 216.00, "2026-02-20",
         {"XXS": 1, "XS": 3, "S": 4, "M": 6, "L": 1, "XL": 1}),
    "EM92425 02.04.26 CTX C8009-R43-304 PO70627 REVISION.pdf":
        ("70627", "2026-02-02", "C8009-R43-304", 1800, 21.50, 38700.00, "2026-05-25",
         {"XS": 387, "S": 553, "M": 492, "L": 231, "XL": 137}),
    "EM92427 03.12.26 CTX C9307-U70-630 PO70790 REVISION.pdf":
        ("70790", "2026-03-09", "C9307-U70-630", 1200, 13.98, 16776.00, "2026-06-26",
         {"XXS": 79, "XS": 185, "S": 346, "M": 330, "L": 162, "XL": 98}),
    "EM92428 03.13.26 CTX C9360-549-638 PO70791 REVISION.pdf":
        ("70791", "2026-03-09", "C9360-549-635", 1200, 13.00, 15600.00, "2026-06-26",
         {"XXS": 83, "XS": 179, "S": 336, "M": 323, "L": 171, "XL": 108}),
    "EM92429 03.13.26 CTX C9043-U70-629 PO70792  REVISION.pdf":
        ("70792", "2026-03-09", "C9043-U70-629", 1000, 14.65, 14650.00, "2026-06-26",
         {"XXS": 60, "XS": 145, "S": 276, "M": 273, "L": 154, "XL": 92}),
    "EM92430 03.13.26 CTX C4825-549-527 PO7793 REVISION.pdf":
        ("70793", "2026-03-09", "C4825-549-527", 1000, 13.00, 13000.00, "2026-06-26",
         {"XXS": 69, "XS": 131, "S": 282, "M": 281, "L": 140, "XL": 97}),
    "EM92432 03.13.26 CTX C9051-U70-664 PO70795 REVISION.pdf":
        ("70795", "2026-03-09", "C9051-U70-654", 800, 13.60, 10880.00, "2026-06-26",
         {"XXS": 51, "XS": 115, "S": 223, "M": 221, "L": 120, "XL": 70}),
}

passed = failed = 0


def check(label: str, got, want) -> None:
    global passed, failed
    ok = got == want
    if isinstance(got, float) and isinstance(want, float):
        ok = abs(got - want) < 0.005
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL  {label}\n        got  {got!r}\n        want {want!r}")


def main() -> int:
    if not os.path.isdir(PO_DIR):
        print(f"SKIP — the corpus is not on this machine ({PO_DIR})")
        return 0

    subject = "Please find the purchase order attached"
    for name, (po, po_date, style, qty, rate, value, ship, grid) in sorted(PAPERS.items()):
        path = os.path.join(PO_DIR, name)
        if not os.path.exists(path):
            print(f"  SKIP  {name} (not in the corpus)")
            continue
        doc = docread.read_pdf(open(path, "rb").read())
        f = intake.extract_deterministic(doc["text"], subject=subject, layout=doc.get("layout"))
        c = f["commercial"]
        line = (f["lines"] or [{}])[0]
        print(f"{po}  {style}")
        check(f"{po} number", f["po"]["number"], po)
        check(f"{po} date", f["po"]["date"], po_date)
        check(f"{po} style", f["style"]["code"], style)
        check(f"{po} qty", c["total_qty"], qty)
        check(f"{po} rate (the garment rate, not the fabric price)", float(c["rate"] or 0), rate)
        check(f"{po} value", float(c["total_value"] or 0), value)
        check(f"{po} ship date", f["ship_date"], ship)
        check(f"{po} grid", line.get("size_grid"), grid)
        check(f"{po} buyer is the paper's legal entity", f["buyer"]["name"], "EMJ APPAREL GROUP")
        check(f"{po} grid ties to the quantity", sum((line.get("size_grid") or {}).values()), qty)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
