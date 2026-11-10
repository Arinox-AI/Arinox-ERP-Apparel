"""Intake — read an order email, understand it, decide which process it starts.

Pipeline (see ``docs/INTAKE_PLAN_EMAIL_TO_PROCESS.md``)::

    extract()  ->  check_arithmetic()  ->  match()  ->  route()  ->  plan()

Design rules
------------
* **Nothing is invented.** Every field is either read from the paper or ``None``
  with a reason in ``missing``. A guessed quantity is worse than a blank one.
* **Two extractors, one shape.** A deterministic reader (regex over the text) and
  an LLM pass over the same text. They are merged field by field; when they
  disagree the field is marked ``conflict`` and drops to low confidence so the
  human decides.
* **Arithmetic is a gate, not a check.** ``Σ lines == total``,
  ``rate × qty == value``, ``Σ colours == total``, ``ship > po date``. A field
  that fails its gate cannot be trusted and is demoted.
* **Confidence is per field**, 0..1, and maps to an action: ≥0.85 auto-fills,
  0.60–0.85 needs a glance, <0.60 needs the operator to type it.
* This module reads the ERP only to *match*; it never writes. Writes live in
  ``intake_exec.py`` (called only from an approved run).
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime

import config

# ────────────────────────────────────────────────────────────────────────────
# Vocabulary
# ────────────────────────────────────────────────────────────────────────────
CURRENCY_WORDS = {
    "usd": "USD", "us$": "USD", "us dollar": "USD", "dollars": "USD", "dollar": "USD", "$": "USD",
    "eur": "EUR", "euro": "EUR", "euros": "EUR", "€": "EUR",
    "inr": "INR", "rs": "INR", "rs.": "INR", "rupee": "INR", "rupees": "INR", "₹": "INR",
    "hkd": "HKD", "hk$": "HKD", "vnd": "VND", "dong": "VND", "₫": "VND",
    "cny": "CNY", "rmb": "CNY", "yuan": "CNY", "¥": "CNY", "jpy": "JPY", "yen": "JPY",
    "gbp": "GBP", "£": "GBP", "pound": "GBP", "pounds": "GBP",
    "aed": "AED", "aud": "AUD", "cad": "CAD", "bdt": "BDT", "pkr": "PKR", "try": "TRY",
}
INCOTERMS = ("EXW", "FCA", "FAS", "FOB", "CFR", "C&F", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP")
MONTHS = {m.lower(): i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}
MONTHS.update({m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September",
     "October", "November", "December"], start=1)})

DOC_TYPES = ("purchase_order", "po_revision", "enquiry", "invoice", "remittance", "other")

_CLAIM_HINTS = ("must", "please", "do not", "don't", "has to", "have to", "ensure", "need",
                "within", "confirm", "complaint", "approved", "no later", "before")
_ASK_HINTS = ("please confirm", "confirm", "kindly", "let us know", "advise", "send us",
              "can you", "could you", "we need", "please send", "please advise", "urgent")


# ────────────────────────────────────────────────────────────────────────────
# Small helpers
# ────────────────────────────────────────────────────────────────────────────
def _clean(text: str) -> str:
    text = (text or "").replace("\u00a0", " ").replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    return text


def _num(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip().replace(" ", "")
        s = re.sub(r"[^\d.,-]", "", s)
        if not s:
            return None
        # 11,80,000.00 (Indian grouping) / 1,180,000.00 / 1.180.000,00
        if re.match(r"^\d{1,3}(,\d{2})*,\d{3}(\.\d+)?$", s) or s.count(",") > 1 and "." in s:
            s = s.replace(",", "")
        elif s.count(",") == 1 and s.count(".") == 0:
            s = s.replace(",", ".") if len(s.split(",")[-1]) != 3 else s.replace(",", "")
        elif s.count(".") > 1 and "," in s:
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
        return float(s)
    except Exception:
        return None


def _int(value) -> int | None:
    n = _num(value)
    return int(round(n)) if n is not None else None


_ROLE_WORDS = ("order desk", "orderdesk", "purchasing", "purchase dept", "purchasing dept", "sourcing",
               "buying", "buyer", "merchandising", "merchandiser", "accounts", "finance", "sales",
               "customer service", "cs team", "team", "dept", "department", "office", "hq", "ltd.",
               "orders", "order team", "planning", "production", "vendor", "supplier", "admin",
               "noreply", "no-reply", "info", "contact", "service")


def _looks_like_company(value: str) -> bool:
    """A buyer NAME, not an address or a role."""
    v = (value or "").strip()
    if not v or "@" in v or len(v) < 3 or len(v) > 90:
        return False
    if not re.search(r"[A-Za-z]{3}", v):
        return False
    if _slug(v) in _ROLE_WORDS:
        return False
    return True


def _company_from_display(display: str) -> str | None:
    """``Bella Dahl Order Desk`` → ``Bella Dahl``; ``Nordic Retail AB Purchasing`` → ``Nordic Retail AB``."""
    v = (display or "").strip()
    if "@" in v:
        v = v.split("@")[0]
    v = re.sub(r"[_\-.]+", " ", v).strip()
    changed = True
    while changed:
        changed = False
        low = v.lower()
        for w in sorted(_ROLE_WORDS, key=len, reverse=True):
            if low.endswith(" " + w) or low.endswith(w) and low != w:
                cut = low.rfind(w)
                if cut > 0:
                    v = v[:cut].strip(" -|,")
                    changed = True
                    break
    return v if _looks_like_company(v) and len(v) >= 3 else None


_LEGAL = ("llc", "l.l.c", "ltd", "limited", "inc", "incorporated", "corp", "corporation", "co",
          "company", "gmbh", "bv", "nv", "sa", "sarl", "srl", "spa", "plc", "pvt", "pte", "ag",
          "kg", "oy", "ab", "as", "aps", "oyj", "holdings", "group llc")


def _company_slug(value: str) -> str:
    """A company name with its legal form removed: ``EMJ APPAREL GROUP, LLC`` ==
    ``EMJ Apparel Group``. Matching on the raw string missed by one character and
    fell through to the contact's email domain — which is the brand, not the buyer
    (2026-11-03)."""
    toks = [t for t in _slug(value).split() if t]
    changed = True
    while changed and toks:
        changed = False
        for suffix in _LEGAL:
            parts = suffix.split()
            if len(toks) >= len(parts) + 1 and toks[-len(parts):] == parts:
                toks = toks[:-len(parts)]
                changed = True
                break
    return " ".join(toks)


def _slug(value: str) -> str:
    v = unicodedata.normalize("NFKD", (value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", v.lower()).strip()


def _match_company(text: str, companies: list[str]) -> str | None:
    """Match the PO's vendor name to one of our own Company records (the 'To').

    The paper rarely prints the full legal name — ``Vendor: HK) Limited`` is the
    OCR'd half of CORTEX FASHION (HK) LIMITED — so a keyword hints first, then a
    slug/fuzzy match, and never a bare guess.
    """
    t = (text or "").lower()
    if not t or not companies:
        return None
    for key, hint in (("hong kong", "hk"), ("hk", "hk"), ("fz", "fz"),
                      ("vietnam", "vietnam"), ("việt nam", "vietnam"),
                      ("zhangjiagang", "china"), ("china", "china")):
        if key in t:
            for c in companies:
                cl = (c or "").lower()
                if hint == "hk" and ("hk" in cl or "hong kong" in cl):
                    return c
                if hint == "fz" and "fz" in cl:
                    return c
                if hint == "vietnam" and "vietnam" in cl:
                    return c
                if hint == "china" and ("zhangjiagang" in cl or "textile limited" in cl):
                    return c
    slug_t = _company_slug(text)
    best, best_score = None, 0.0
    import difflib
    for c in companies:
        cand = _company_slug(c)
        if slug_t and cand and (slug_t in cand or cand in slug_t):
            return c
        s = difflib.SequenceMatcher(None, slug_t.lower(), cand.lower()).ratio() if slug_t and cand else 0.0
        if s > best_score:
            best, best_score = c, s
    return best if best_score >= 0.6 else None


def normalise_po(value: str) -> str:
    """``AO 5644 R1`` → ``AO-5644``; ``p.o. #69785`` → ``69785``.

    A revision suffix is deliberately dropped here: revision is decided from the
    document type, never from a string, or ``-R1`` silently becomes a new order.
    """
    v = _clean(value or "").upper()
    v = re.sub(r"\b(P\.?\s*O\.?|PURCHASE\s+ORDER|ORDER)\b", " ", v)
    v = re.sub(r"(?<=\d)[\s\-/]*(REV|R|V)\.?[\s\-/]*\d{1,2}\b", "", v)   # revision suffix
    v = re.sub(r"[^A-Z0-9]+", "-", v).strip("-")
    v = re.sub(r"-{2,}", "-", v)
    return v


def po_core(value: str) -> str:
    """The comparable part of a PO number: letters + digits only, no leading "PO".

    ``PO 69785``, ``P.O. #69785`` and ``69785`` are the same order; ``PO-69999``
    and ``69999`` too. Without this the merge flagged a false conflict on every
    fixture and the duplicate guard missed half the matches (2026-11-03).
    """
    core = re.sub(r"[^A-Z0-9]", "", (value or "").upper())
    core = re.sub(r"^(?:PO|PURCHASEORDER|ORDER)(?=\d)", "", core)
    # "69785-R1" / "69785REV2" describe the SAME order as "69785"
    trimmed = re.sub(r"(?:REV|R|V)\d{1,2}$", "", core)
    if len(trimmed) >= 3:
        core = trimmed
    return core


def _date_iso(token: str) -> str | None:
    """Understand every date shape a buyer uses. Returns ISO or None."""
    if not token:
        return None
    t = _clean(str(token)).strip().strip(",.;")
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", t)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$", t)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # 15/01/2027 is unambiguously d/m; 01/15/2027 is m/d. Decide by size.
        if a > 12 >= b:
            return _safe_date(y, b, a)
        if b > 12 >= a:
            return _safe_date(y, a, b)
        return _safe_date(y, b, a)      # default d/m/yyyy (Cortex / EU / IN buyers)
    m = re.match(r"^(\d{1,2})[\s-]+([A-Za-z]{3,9})\.?[\s,-]+(\d{2,4})$", t)
    if m:
        mon = MONTHS.get(m.group(2).lower())
        if mon:
            y = int(m.group(3))
            y = y + 2000 if y < 100 else y
            return _safe_date(y, mon, int(m.group(1)))
    m = re.match(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})$", t)
    if m:
        mon = MONTHS.get(m.group(1).lower())
        if mon:
            return _safe_date(int(m.group(3)), mon, int(m.group(2)))
    return None


def _safe_date(y: int, m: int, d: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except Exception:
        return None


def _today() -> date:
    return date.today()


# ────────────────────────────────────────────────────────────────────────────
# The fact shape — one contract for every extractor
# ────────────────────────────────────────────────────────────────────────────
def empty_facts() -> dict:
    return {
        "document_type": "other",
        "buyer": {"name": None, "country": None, "address": None,
                  "contact": None, "email": None, "phone": None, "tax_id": None},
        "to": {"name": None, "address": None, "phone": None, "email": None},
        "po": {"number": None, "date": None, "reference": None},
        "commercial": {"currency": None, "rate": None, "incoterm": None, "named_place": None,
                       "payment_terms": None, "total_qty": None, "total_value": None},
        "ship_date": None,
        "delivery_window": {"from": None, "to": None},
        "season": None,
        "style": {"code": None, "description": None, "fabric": None,
                  "composition": None, "gsm": None, "fabric_code": None},
        "lines": [],
        "quality": {"aql_major": None, "aql_minor": None, "carton_ratio": None},
        "claims": [],
        "asks": [],
        "confidence": {},
        "missing": [],
        "conflicts": [],
        "extractors": [],
    }


def _set(facts: dict, path: str, value, conf: float | None = None) -> None:
    """Assign ``a.b.c`` = value, and its confidence (if any)."""
    if value in (None, "", [], {}):
        return
    parts = path.split(".")
    node = facts
    for p in parts[:-1]:
        node = node.setdefault(p, {})
    node[parts[-1]] = value
    if conf is not None:
        facts.setdefault("confidence", {})[path] = round(float(conf), 2)


def _conf(facts: dict, path: str) -> float:
    return float((facts.get("confidence") or {}).get(path) or 0)


# ────────────────────────────────────────────────────────────────────────────
# Deterministic extractor
# ────────────────────────────────────────────────────────────────────────────
_LABELLED = r"[ \t]*[:\-–]?[ \t]*"


_STOP = (r"(?=\s{2,}|\s*\||\s+(?:PO\s*number|PO\s*date|Ship\s*date|Terms|Payment|Buyer|"
         r"Address|Country|Style|Description|Fabric|Qty|Quantity|Rate|Colour|Color|Total|Order\s*reference|"
         r"Page\b|For\s+the\s+buyer|Accepted\s+by|Buyer\s+instructions)|$)")

_LABEL_WORDS = {"qty", "quantity", "rate", "fabric", "style", "description", "colour", "color",
                "shade", "value", "amount", "total", "pages", "page", "cartons", "pieces", "pcs",
                "order", "purchase", "buyer", "address", "country", "terms", "payment", "price"}


def _pick_value(raw: str, stop: bool = True) -> str:
    v = (raw or "").strip(" |\t.,;")
    if stop:
        v = re.split(_STOP, v)[0].strip(" |\t.,;")
    return v


def _grab(text: str, labels: list[str], value: str, flags=re.I, stop: bool = True) -> tuple[str | None, float]:
    """First value after any of ``labels`` on the same line. Returns (value, conf)."""
    for lab in labels:
        pat = rf"(?:^|\n)[ \t|]*{lab}{_LABELLED}({value})"
        m = re.search(pat, text, flags | re.M)
        if m:
            v = _pick_value(m.group(1), stop)
            if v:
                return v, 0.95
    for lab in labels:                                  # allow the label to sit mid-line
        pat = rf"\b{lab}{_LABELLED}({value})"
        m = re.search(pat, text, flags)
        if m:
            v = _pick_value(m.group(1), stop)
            if v:
                return v, 0.8
    return None, 0.0


def _find_dates(text: str) -> list[tuple[str, str]]:
    """[(raw, iso)] for every date-looking token, in order."""
    out = []
    pats = [r"\d{4}-\d{1,2}-\d{1,2}", r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}",
            r"\d{1,2}[\s-]+[A-Za-z]{3,9}\.?,?[\s-]+\d{2,4}",
            r"[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}"]
    for p in pats:
        for m in re.finditer(p, text):
            iso = _date_iso(m.group(0))
            if iso:
                out.append((m.group(0), iso))
    return out


_FREE_MAIL = ("gmail.com", "googlemail.com", "yahoo.", "outlook.", "hotmail.", "icloud.com",
              "aol.com", "proton.me", "protonmail.", "mail.ru", "163.com", "qq.com")


def _currency_from(text: str) -> str | None:
    """Currency codes are matched as WORDS. Substring matching read "orders" as Rs
    and turned a USD order into INR (2026-11-03)."""
    t = _clean(text)
    m = re.search(r"\b(USD|EUR|INR|HKD|VND|CNY|RMB|GBP|AED|JPY|AUD|CAD|BDT|PKR|TRY)\b", t.upper())
    if m:
        return "CNY" if m.group(1) == "RMB" else m.group(1)
    # symbols only when they sit against a number
    for sym, cur in (("₹", "INR"), ("€", "EUR"), ("£", "GBP"), ("$", "USD"), ("¥", "CNY")):
        if re.search(rf"{re.escape(sym)}\s?\d", t):
            return cur
    if re.search(r"\bRs\.?\s?\d", t, re.I):
        return "INR"
    return None


# Labels a buyer prints as a column HEADER with the value in the row underneath (2026-11-07).
# Harbor & Lane's PO prints "PO NUMBER | PO DATE | BUYER | COUNTRY" on one row and the values on the
# next; the same-line reader then took the NEXT label's text as the value ("buyer = SAMPLE
# REQUIREMENTS…", "country = DATE OR"). The positions are already in the layout trace.
_HEADER_LABELS = re.compile(
    r"^(?:P\.?\s?O\.?\s*(?:no\.?|number|#)?|purchase\s+order\s*(?:no\.?|number|#)?|order\s*(?:no\.?|number|#)|"
    r"po\s*date|order\s*date|date|ship\s*date|shipment\s*date|delivery\s*date|ex[- ]?factory(?:\s*date)?|etd|"
    r"buyer|customer|bill\s*to|sold\s*to|consignee|vendor|supplier|seller|country|origin|"
    r"style(?:\s*(?:no\.?|number|#|code))?|description|fabric(?:ation)?|colou?r|shade|season|"
    r"price|unit\s*price|fob|rate|qty|quantity|total\s*qty|currency|terms|payment\s*terms|incoterms?)\s*[:#]?$",
    re.I)


def _is_header_token(t: str) -> bool:
    t = (t or "").strip()
    return bool(t) and len(t) <= 32 and not re.search(r"\d{2,}", t) and bool(_HEADER_LABELS.match(t))


def header_value_pairs(layout: list | None) -> list[str]:
    """``["PO NUMBER: 71240", "BUYER: Harbor & Lane", …]`` from a header row and the row below it.

    A row counts as a header when at least two of its tokens are known labels and they make up most of
    the row. Each label takes the tokens of the next row that start under it (from just left of the
    label to just left of the next label). Nothing is guessed when the next row is itself a header.
    """
    rows = _rows_from_layout(layout or [])
    out: list[str] = []
    for i in range(len(rows) - 1):
        page, toks = rows[i]
        npage, ntoks = rows[i + 1]
        if page != npage or len(toks) < 2:
            continue
        heads = [(x, t) for x, t in toks if _is_header_token(t)]
        if len(heads) < 2 or len(heads) < 0.6 * len(toks):
            continue
        if sum(1 for _x, t in ntoks if _is_header_token(t)) >= max(2, len(ntoks) // 2):
            continue                                   # two header rows in a row: no values to pair
        heads.sort()
        for j, (x, lab) in enumerate(heads):
            right = heads[j + 1][0] if j + 1 < len(heads) else float("inf")
            vals = [t for vx, t in ntoks if x - 12 <= vx < right - 4]
            v = " ".join(vals).strip(" |:")
            if v and not _is_header_token(v):
                out.append(f"{lab.rstrip(':# ').strip()}: {v}")
    return out


def extract_deterministic(text: str, subject: str = "", body: str = "",
                          from_name: str = "", from_addr: str = "",
                          layout: list | None = None) -> dict:
    """Read the facts out of the paper using patterns only.

    Every read carries a confidence: a labelled field ("PO number AO-5644") is
    trusted more than a bare pattern in prose.
    """
    facts = empty_facts()
    facts["extractors"] = ["deterministic"]
    blob = _clean("\n".join(x for x in (body, text, subject) if x))
    doc = _clean(text or "") or blob
    # label-safe text: the mail body first (clean "Label : value" pairs), then the paper
    fields_src = _clean("\n".join(x for x in (body, text) if x)) or blob
    # column headers with their values underneath, rebuilt from positions, go FIRST: a clean
    # "Label: value" line beats a same-line read that picked up the neighbouring header
    try:
        pairs = header_value_pairs(layout)
    except Exception:
        pairs = []
    if pairs:
        fields_src = "\n".join(pairs) + "\n" + fields_src
        facts["_header_pairs"] = pairs[:60]

    # ── document type ───────────────────────────────────────────────────────
    low = blob.lower()
    if re.search(r"\b(revised|amendment|amended|supersedes|revision|updated po|change order)\b", low):
        facts["document_type"] = "po_revision"
    elif re.search(r"\b(purchase order|p\.?\s?o\.?\s*(no|number|#)|order confirmation)\b", low):
        facts["document_type"] = "purchase_order"
    elif re.search(r"\b(invoice)\b", low) and re.search(r"\b(inv|invoice)\s*(no|number|#)", low):
        facts["document_type"] = "invoice"
    elif re.search(r"\b(remittance|payment advice|swift copy|tt copy)\b", low):
        facts["document_type"] = "remittance"
    elif re.search(r"\b(enquiry|inquiry|rfq|request for quotation|quote|quotation)\b", low):
        facts["document_type"] = "enquiry"
    if re.search(r"\b(order)\b", low) and facts["document_type"] == "other" and re.search(r"\bqty|quantity|pcs|pieces\b", low):
        facts["document_type"] = "purchase_order"

    # ── PO number ───────────────────────────────────────────────────────────
    po, conf = _grab(fields_src, [r"PO\s*number", r"P\.?\s?O\.?\s*(?:No\.?|Number|#)",
                                  r"Purchase\s+Order\s*(?:No\.?|Number|#)?", r"Order\s+No\.?", r"PO\b"],
                     r"[A-Za-z]{0,4}[-/ ]?\d[A-Za-z0-9\-/]{1,22}")
    if not po:
        m = re.search(r"\b([A-Z]{2,4}[-/ ]?\d{3,7}(?:[-/]\d{1,3})?)\b", subject or blob)
        po, conf = (m.group(1), 0.7) if m else (None, 0.0)
    if po:
        po = re.split(r"\s{2,}|\s+(?:dated|date|for|attached)\b", po, flags=re.I)[0].strip(" |.,")
        _set(facts, "po.number", po, conf)

    # ── dates: PO date and ship date ────────────────────────────────────────
    raw, c = _grab(fields_src, [r"PO\s*date", r"Order\s*date", r"Date\s*of\s*(?:PO|order)"],
                   r"[0-9A-Za-z][0-9A-Za-z ,./-]{5,24}")
    iso = _date_iso(raw or "")
    if not iso:
        iso = _date_iso(raw or "") or None
    if not iso:
        # the label line may be "PO date 01 Nov 2026" — capture the date itself
        m = re.search(r"(?:PO|Order)\s*date\W{0,4}([0-9]{1,2}[\s/-][A-Za-z0-9]{1,9}[\s/-]\d{2,4}|\d{4}-\d{2}-\d{2})", doc, re.I)
        iso = _date_iso(m.group(1)) if m else None
        c = 0.9 if iso else 0.0
    if iso:
        _set(facts, "po.date", iso, c or 0.9)

    raw, c = _grab(fields_src, [r"Ship\s*date", r"Shipment\s*date", r"Delivery\s*date", r"Ex[- ]?factory\s*date",
                         r"ETD", r"Required\s*(?:by|date)"], r"[0-9A-Za-z][0-9A-Za-z ,./-]{5,24}")
    iso = _date_iso(raw or "")
    if not iso:
        m = re.search(r"(?:Ship|Delivery|Shipment)\s*date\W{0,4}([0-9]{1,2}[\s/-][A-Za-z0-9]{1,9}[\s/-]\d{2,4}|\d{4}-\d{2}-\d{2})", doc, re.I)
        iso = _date_iso(m.group(1)) if m else None
        c = 0.9 if iso else 0.0
    if iso:
        _set(facts, "ship_date", iso, c or 0.9)
    elif facts["document_type"] in ("purchase_order", "po_revision"):
        # fall back to the LAST date on the paper (the ship date is printed after the PO date)
        dates = _find_dates(doc)
        if len(dates) >= 2:
            _set(facts, "ship_date", dates[-1][1], 0.55)
        elif dates:
            _set(facts, "ship_date", dates[-1][1], 0.45)

    # ── buyer ───────────────────────────────────────────────────────────────
    name, c = _grab(fields_src, [r"Buyer", r"Customer", r"Bill\s*to", r"Sold\s*to", r"Consignee"],
                    r"[A-Z][^\n|]{2,70}")
    if name:
        name = re.split(r"\s{2,}|\s*\|\s*|\s+(?:Address|Country|PO number|PO date)\b", name)[0].strip(" .,|")
        if (_looks_like_company(name)):
            _set(facts, "buyer.name", name, c)
    if not facts["buyer"]["name"]:
        # signature block: the line after "Regards," / "Best regards," holding a company suffix
        m = re.search(r"(?:regards|sincerely|best)\s*,?\s*\n+([^\n]{3,80})\n([^\n]{0,80})", blob, re.I)
        if m:
            cand = m.group(1).strip()
            if re.search(r"(gmbh|ltd|limited|llc|inc|corp|company|co\.|bv|s\.a\.|pvt|plc|ag|srl|spa)\b", cand, re.I):
                _set(facts, "buyer.name", cand, 0.85)
            elif re.search(r"(gmbh|ltd|limited|llc|inc|corp|company|co\.|bv|s\.a\.|pvt|plc|ag|srl|spa)\b", m.group(2), re.I):
                _set(facts, "buyer.name", m.group(2).strip(), 0.8)
    if from_addr and not facts["buyer"]["email"]:
        _set(facts, "buyer.email", from_addr.lower(), 0.9)
    if from_name and not facts["buyer"].get("contact"):
        _set(facts, "buyer.contact", from_name.strip(), 0.6)
    if not facts["buyer"].get("name") and from_name:
        derived = _company_from_display(from_name)
        if derived:
            _set(facts, "buyer.name", derived, 0.6)
    country, c = _grab(fields_src, [r"Country"], r"[A-Z][A-Za-z ]{2,30}")
    if country:
        _set(facts, "buyer.country", country.strip(" |"), c)
    if not facts["buyer"]["country"]:
        for cand in ("Germany", "United States", "USA", "UK", "United Kingdom", "India", "Vietnam",
                     "China", "Hong Kong", "Netherlands", "Sweden", "Denmark", "France", "Italy",
                     "Spain", "Canada", "Australia", "Turkey", "Bangladesh", "UAE", "Japan"):
            if re.search(rf"\b{re.escape(cand)}\b", doc):
                _set(facts, "buyer.country", "United States" if cand == "USA" else
                     ("United Kingdom" if cand == "UK" else cand), 0.55)
                break

    # ── buyer phone (the From letterhead) ──────────────────────────────────
    phone, c = _grab(fields_src, [r"Tel", r"Telephone", r"Phone", r"Ph\s*no"],
                     r"[+\d][\d \t()\-./]{5,24}")
    if phone:
        _set(facts, "buyer.phone", phone.strip(" .|"), c)

    # ── To / vendor (our company — who the buyer's PO is addressed to) ────
    to_name, c = _grab(fields_src, [r"Vendor", r"Supplier", r"Seller", r"Ship\s*from"],
                       r"[A-Z][^\n|]{2,70}")
    if to_name:
        to_name = re.split(r"\s{2,}|\s*\|\s*|\s+(?:Ship\s*to|Address|Contact|Terms|Phone|Tel|PO)\b",
                           to_name, flags=re.I)[0].strip(" .,|")
        if (_looks_like_company(to_name)
                or re.search(r"(cortex|textile|garment|fashion|limited|ltd|llc|fz|hk|vietnam)", to_name, re.I)):
            _set(facts, "to.name", to_name[:80], c)
    to_phone, c = _grab(fields_src, [r"Vendor\s*(?:Phone|Tel|Fax)", r"Supplier\s*(?:Phone|Tel|Fax)"],
                        r"[+\d][\d \t()\-./]{5,24}")
    if to_phone:
        _set(facts, "to.phone", to_phone.strip(" .|"), c)
    # our own side's contact — a cortex/kogo-domain address, never the buyer's
    m = re.search(r"[A-Za-z0-9._%+\-]+@(?:cortex|kogo)[A-Za-z0-9.\-]*\.[A-Za-z]{2,}", doc, re.I)
    if m:
        _set(facts, "to.email", m.group(0).lower(), 0.7)

    # ── commercial ──────────────────────────────────────────────────────────
    cur = _currency_from(doc)
    if cur:
        _set(facts, "commercial.currency", cur, 0.9 if re.search(rf"\b{cur}\b", doc) else 0.6)

    rate, c = _grab(fields_src, [r"Rate", r"Unit\s*price", r"Price(?:/pc| per pc)?", r"FOB\s*price", r"Selling\s*price"],
                    r"(?:USD|EUR|INR|HKD|VND|CNY|GBP|AED|US\$|Rs\.?|₹|\$|€|£|¥)?\s*[\d][\d,]*\.?\d*")
    rv = _num(rate)
    if rv:
        _set(facts, "commercial.rate", rv, c)
        mcur = re.search(r"(USD|EUR|INR|HKD|VND|CNY|GBP|AED)", (rate or "").upper())
        if mcur:
            _set(facts, "commercial.currency", mcur.group(1), c)
    if not rv:
        m = re.search(r"(?:USD|EUR|INR|HKD|VND|CNY|GBP|US\$|Rs\.?|₹|\$|€|£)\s*([\d][\d,]*\.?\d{0,2})\s*"
                      r"(?:per|/)\s*(?:pc|piece|pcs)", doc, re.I)
        if m:
            _set(facts, "commercial.rate", _num(m.group(1)), 0.85)

    qty, c = _grab(fields_src, [r"Total\s*(?:Qty|Quantity|Pcs|Pieces)", r"Quantity", r"Qty",
                         r"Order\s*Qty", r"Total\s*pieces"], r"[\d][\d,]{0,9}")
    qv = _int(qty)
    if not qv:
        m = re.search(r"([\d][\d,]{2,9})\s*(?:pcs|pieces|units|pairs)\b", doc, re.I)
        qv, c = (_int(m.group(1)), 0.8) if m else (None, 0.0)
    if qv:
        _set(facts, "commercial.total_qty", qv, c)

    val, c = _grab(fields_src, [r"Total\s*value", r"Order\s*value", r"Amount", r"Value"],
                   r"(?:USD|EUR|INR|HKD|VND|CNY|GBP|AED|US\$|Rs\.?|₹|\$|€|£|¥)?\s*[\d][\d,]*\.?\d*")
    vv = _num(val)
    if vv:
        _set(facts, "commercial.total_value", vv, c)

    # incoterm + named place. Buyer PDFs often letter-space the term ("DD P
    # SHIPMENT"), so a spaced form is matched too.
    m = re.search(r"\b(EXW|FCA|FAS|FOB|CFR|C&F|CIF|CPT|CIP|DAP|DPU|DDP)\b\s*(?:at\s+|to\s+)?([A-Z][A-Za-z .'-]{2,30})?", doc)
    if m:
        _set(facts, "commercial.incoterm", "CFR" if m.group(1) == "C&F" else m.group(1), 0.9)
        place = (m.group(2) or "").strip(" .,|")
        place = re.split(r"\s{2,}|\||\b(?:Payment|Terms|Ship|PO|Style|Qty)\b", place)[0].strip()
        if place:
            _set(facts, "commercial.named_place", place[:40], 0.75)
    else:
        # letter-spaced in the PDF's text layer: "DD P SHIPMENT" is DDP SHIPMENT
        spaced = re.search(r"\b([EDFC])\s?([DXF])\s?([PWAF])\b", doc)
        if spaced:
            compact = "".join(spaced.groups()).upper()
            if compact in INCOTERMS:
                _set(facts, "commercial.incoterm", compact, 0.65)

    # payment terms
    m = re.search(r"(\d{1,3})\s*(?:days?|d)\s*(?:from|after|net|of|from\s+the)\s*(B/?L|BL|bill of lading|invoice|"
                  r"shipment|delivery|sight|acceptance|receipt|ROG)", doc, re.I)
    if m:
        _set(facts, "commercial.payment_terms", f"{m.group(1)} days from {m.group(2).upper()}", 0.9)
    else:
        m = re.search(r"\b(L/C\s+at\s+sight|LC\s+at\s+sight|letter of credit|D/P|D/A|O/A|T/T|TT|advance)\b", doc, re.I)
        if m:
            _set(facts, "commercial.payment_terms", m.group(1), 0.75)

    # season / buyer reference
    m = re.search(r"\b((?:SS|FW|AW|SP)\s?\d{2})\b", doc)
    if m:
        _set(facts, "season", m.group(1).replace(" ", ""), 0.8)
    ref, c = _grab(fields_src, [r"Order\s*reference", r"Buyer\s*reference", r"Reference"], r"[A-Za-z0-9][^\n|]{2,60}")
    if ref:
        _set(facts, "po.reference", ref.strip(), c)

    # ── style ───────────────────────────────────────────────────────────────
    m = re.search(r"\b([A-Z]{2,4}-\d{2}-[A-Z]{2}-\d{2,4})\b", doc)          # GGI-26-SS-131
    if not m:
        m = re.search(r"\b([A-Z]\d{3,4}-[A-Z0-9]{1,4}-\d{3}(?:-[A-Z0-9]{1,5})?)\b", doc)   # C9043-U70-629
    if m:
        _set(facts, "style.code", m.group(1), 0.9)
    else:
        st, c = _grab(fields_src, [r"Style\s*(?:no\.?|number|code)?", r"Style"], r"[A-Za-z0-9][A-Za-z0-9\-/]{3,24}")
        if st:
            _set(facts, "style.code", st.strip(), c)

    fab, c = _grab(fields_src, [r"Fabric", r"Quality", r"Ground\s*fabric"], r"[A-Za-z0-9][^\n|]{2,60}")
    if fab and _slug(fab) not in _LABEL_WORDS:
        f = re.split(r"\s{2,}|\s*\|\s*|\s+(?:Qty|Colour|Color|Rate)\b", fab)[0].strip(" .,|")
        _set(facts, "style.fabric", f, c)
        g = re.search(r"(\d{2,4})\s*gsm", f, re.I)
        if g:
            _set(facts, "style.gsm", int(g.group(1)), c)
        mcode = re.search(r"\b(FAB-[A-Z0-9]{2,12})\b", doc)
        if mcode:
            _set(facts, "style.fabric_code", mcode.group(1), 0.9)
    if not facts["style"]["gsm"]:
        g = re.search(r"(\d{2,4})\s*gsm", doc, re.I)
        if g:
            _set(facts, "style.gsm", int(g.group(1)), 0.7)
    m = re.search(r"\b(\d{1,3})\s*%\s*(cotton|polyester|viscose|rayon|elastane|spandex|linen|wool|nylon)", doc, re.I)
    if m:
        _set(facts, "style.composition", f"{m.group(1)}% {m.group(2).title()}", 0.7)

    desc, c = _grab(fields_src, [r"Description", r"Item", r"Garment"], r"[A-Za-z][^\n|]{3,80}")
    if desc:
        d = re.split(r"\s{2,}|\s*\|\s*", desc)[0].strip()
        if len(d) > 3 and not re.match(r"^(?:qty|fabric|style|colour|color)\b", d, re.I):
            _set(facts, "style.description", d, c * 0.9)

    # ── colour lines ────────────────────────────────────────────────────────
    # scan the mail body AND the paper: the list is usually typed in the mail,
    # the table is in the attachment, and either may be the only one present.
    facts["lines"] = _extract_lines(fields_src, facts, layout)

    # ── production facts the paper prints (lead time, yield, fabric price) ──
    m = re.search(r"(?:PRODUCTION\s*)?LEAD\s*TIME\s*[:|]?\s*(\d{1,3})\s*(?:DAYS|D)\b", doc, re.I)
    if m:
        _set(facts, "lead_time_days", int(m.group(1)), 0.9)
    m = re.search(r"\bYIELD\s*[:|]?\s*([\d.]+)", doc, re.I)
    if m:
        _set(facts, "style.yield_per_pc", _num(m.group(1)), 0.8)
    m = re.search(r"FABRIC\s*PRICE\s*[:|]?\s*(?:USD|US\$|\$)?\s*([\d.]+)", doc, re.I)
    if m:
        _set(facts, "commercial.fabric_rate", _num(m.group(1)), 0.8)

    # ── quality ─────────────────────────────────────────────────────────────
    m = re.search(r"AQL\s*([\d.]+)\s*(?:major)?\s*[,/ ]?\s*([\d.]+)?\s*(?:minor)?", doc, re.I)
    if m:
        _set(facts, "quality.aql_major", _num(m.group(1)), 0.85)
        if m.group(2):
            _set(facts, "quality.aql_minor", _num(m.group(2)), 0.85)
    m = re.search(r"(?:carton|pack)\s*(?:ratio|of|size)\s*[: ]?\s*(\d{1,3})", doc, re.I)
    if m:
        _set(facts, "quality.carton_ratio", _int(m.group(1)), 0.85)

    # ── claims + asks (from the email body, not the paper) ──────────────────
    facts["claims"], facts["asks"] = _extract_claims(_clean(body or "") or blob)

    # ── the client's own PO form wins over every generic pattern ────────────
    # The paper is the same form on all thirteen real POs, so when we recognise it
    # its row reads are authoritative: they replace a generic "PO" grab that took
    # the EM cross-reference, and a "Price" grab that took the fabric rate.
    form = _po_form(doc, layout)
    if form:
        _set(facts, "po.number", form.get("po"), 0.97)
        _set(facts, "po.date", form.get("po_date"), 0.97)
        if form.get("cross_ref"):
            _set(facts, "po.reference", form["cross_ref"], 0.9)
        _set(facts, "buyer.name", form.get("buyer"), 0.95)
        _set(facts, "style.code", form.get("style"), 0.97)
        _set(facts, "style.description", form.get("description"), 0.9)
        _set(facts, "style.fabric_code", form.get("fabric_code"), 0.9)
        _set(facts, "commercial.rate", form.get("rate"), 0.95)
        _set(facts, "commercial.total_qty", form.get("qty"), 0.95)
        _set(facts, "commercial.total_value", form.get("value"), 0.9)
        _set(facts, "ship_date", form.get("ship_date"), 0.9)
        _set(facts, "commercial.payment_terms", form.get("payment_terms"), 0.9)
        _set(facts, "commercial.incoterm", form.get("incoterm"), 0.9)
        _set(facts, "lead_time_days", form.get("lead_time_days"), 0.9)
        _set(facts, "style.yield_per_pc", form.get("yield_per_pc"), 0.8)
        _set(facts, "commercial.fabric_rate", form.get("fabric_rate"), 0.9)
        if form.get("lines"):
            lines = []
            for r in form["lines"]:
                line = {"colour": r.get("colour"), "shade": None, "qty": r.get("qty"),
                        "cartons": None, "rate": r.get("rate"), "size": None, "confidence": 0.9}
                if form.get("grid"):
                    line["size_grid"] = form["grid"]
                    line["size_confidence"] = form.get("grid_confidence")
                lines.append(line)
            facts["lines"] = lines
        if form.get("rate_conflict"):
            facts.setdefault("conflicts", []).append({
                "field": "commercial.rate",
                "kept": form["rate_conflict"][0],
                "other": form["rate_conflict"][1],
                "reason": "the PO line rate wins over the notes box that contradicts it",
            })
        facts["extractors"] = sorted(set(list(facts.get("extractors") or []) + ["client_po_form"]))

    # ── derived: missing + confidence hygiene ───────────────────────────────
    _finish(facts)
    return facts


# ────────────────────────────────────────────────────────────────────────────
# The client's own purchase-order form (EMJ / Bella Dahl)
# ────────────────────────────────────────────────────────────────────────────
# Every real PO in the client's corpus — all thirteen of them — is printed on ONE
# vendor form, and it is a two-cell table with the size grid on its own line. A
# generic "a row has three cells" reader sees nothing on it, so it took the EM
# cross-reference as the PO number, the FABRIC price as the garment rate and threw
# the grid away (2026-11-03). This reader knows the form. It runs first; when it
# matches, its reads replace the generic ones — the paper is the same paper every
# time, so the read should not depend on a model call.

_FORM_HEAD_RE = re.compile(
    r"^(?P<buyer>[A-Z][A-Z0-9 &.,'()/-]{2,60}?)\s*\|\s*(?P<po>\d{4,7})\s+"
    r"(?P<date>\d{1,2}/\d{1,2}/\d{4})\s*\|\s*(?P<cross>[A-Z]{2}\d{4,6})\s*$", re.M)
_FORM_ITEM_RE = re.compile(
    r"^(?P<style>[A-Z0-9]{1,6}[A-Z0-9-]{4,30})\s*\|\s*(?P<desc>[A-Z][^\n|]{2,60})\s*$", re.M)
_FORM_QTY_RE = re.compile(
    r"^(?P<colour>[A-Z][A-Z0-9 &.'/#()+-]{2,60}?)\s*\|\s*"
    r"(?P<qty>\d[\d,]{0,6})\s+(?P<rate>\d[\d,]*\.\d{1,4})\s+(?P<total>\d[\d,]*\.\d{2})\s*$", re.M)


_FORM_NUMS_RE = re.compile(
    r"^(?P<qty>\d[\d,]{0,6})\s+(?P<rate>\d[\d,]*\.\d{1,4})\s*"
    r"(?:\|\s*)?(?P<total>[\d,]*\.\d{2})$")


def _form_rows(block: str) -> list[dict]:
    """The quantity rows of the form.

    The colour spans ONE or MORE cells and the buyer's own print puts a pipe
    between rate and total on some POs, so the row is read from the tail: join the
    cells from position *i* and keep the first *i* that forms ``qty rate total``.
    Everything before it is the colour. (PO 70791 prints three cells, PO 70465 puts
    a pipe between 23.00 and 5,750.00, PO 69788 continues the shade on the next
    line — one regex cannot do all three, and a wrong colour is worse than none.)
    """
    rows = []
    for raw in block.splitlines():
        line = raw.strip()
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.split("|")]
        for i in range(1, len(cells)):
            m = _FORM_NUMS_RE.match(" ".join(c for c in cells[i:] if c))
            if not m:
                continue
            qty, rate, total = _int(m.group("qty")), _num(m.group("rate")), _num(m.group("total"))
            colour = " ".join(c for c in cells[:i] if c).strip()
            if not qty or qty < 10 or not colour:
                break                            # a size header / a totals row
            if rate and total and abs(qty * rate - total) > max(1.0, total * 0.005):
                break                            # arithmetic is a gate, not a check
            rows.append({"colour": colour, "qty": qty, "rate": rate, "total": total})
            break
    return rows


def _form_date(raw: str) -> str | None:
    """The form's dates are US **M/D/Y** (a US buyer prints them that way).

    ``_date_iso`` falls back to day-first when a date is ambiguous, which read
    PO 70790's 03/09/2026 as 3 September instead of 9 March and made the paper
    look like it shipped six months before it was placed (2026-11-03). Where the
    two readings disagree, this buyer's order wins.
    """
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", (raw or "").strip())
    if not m:
        return _date_iso(raw or "")
    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if a > 12 and b <= 12:
        d, mo = a, b
    elif b > 12 and a <= 12:
        mo, d = a, b
    else:
        mo, d = a, b                       # M/D/Y — this form's own convention
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return _date_iso(raw or "")


def _po_form(doc: str, layout: list | None = None) -> dict | None:
    """Read the client's PO form row by row. ``None`` when this is not that form."""
    text = doc or ""
    if "Vendor Item" not in text or "ORDER TOTAL" not in text:
        return None
    head = _FORM_HEAD_RE.search(text)
    if not head:
        return None

    out: dict = {"buyer": head.group("buyer").strip(" .,|"),
                 "po": head.group("po"),
                 "po_date": _form_date(head.group("date")),
                 "cross_ref": head.group("cross")}

    # the item block: from the table header to the ORDER TOTAL row
    start = text.find("Vendor Item")
    end = text.find("ORDER TOTAL", start)
    block = text[start:end if end > start else len(text)]

    item = _FORM_ITEM_RE.search(block)
    if item:
        out["style"] = item.group("style")
        out["description"] = item.group("desc").strip()
        # The middle segment of this client's style code IS the buyer's fabric code
        # (C9307-**U70**-630, C4825-**549**-527), and that string is exactly what the
        # Item Mapping register is keyed on. Reading it from the style replaces a hunt
        # through a letter-spaced notes box ("3.REF # L37 - U70 CO RTEX OPTION B").
        fm = re.match(r"^[A-Z]\d{3,4}-([A-Z]{0,2}\d{1,3})-\d{3}$", item.group("style"))
        if fm:
            out["fabric_code"] = fm.group(1)

    rows = _form_rows(block)
    if rows:
        out["lines"] = rows
        out["qty"] = sum(r["qty"] for r in rows)
        out["value"] = round(sum(r["qty"] * (r["rate"] or 0) for r in rows), 2)
        rates = {r["rate"] for r in rows}
        out["rate"] = rates.pop() if len(rates) == 1 else None

    # the ship date is the date printed against IN WAREHOUSE
    m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})\s*\|\s*IN\s*WAREHOUSE", text, re.I)
    if m:
        out["ship_date"] = _form_date(m.group(1))

    # letter-spaced on the paper: "15 D AYS ROG"
    m = re.search(r"(\d{1,3})\s*D\s*AYS?\s*(ROG|B/?L|BL|SIGHT)", text, re.I)
    if m:
        out["payment_terms"] = f"{m.group(1)} days from {m.group(2).upper()}"
    if re.search(r"\bD\s?D\s?P\b|DD\s?P\b", text):
        out["incoterm"] = "DDP"

    # The notes box prints the garment price on page 2. It is a FALLBACK only: the
    # line rate is what the buyer is charged, and on PO 70791 the box contradicts
    # its own line (13.98 vs 13.00). The line wins; the difference is recorded.
    m = re.search(r"GARME\s*N?T?\s*PRICE\s*[:|]?\s*(?:USD|US\$|\$)?\s*([\d.]+)", text, re.I)
    if m:
        out["garment_rate_notes_box"] = _num(m.group(1))
        if out.get("rate") and abs(out["rate"] - out["garment_rate_notes_box"]) > 0.004:
            out["rate_conflict"] = (out["rate"], out["garment_rate_notes_box"])
        elif not out.get("rate"):
            out["rate"] = out["garment_rate_notes_box"]
    m = re.search(r"FABRIC\s*PRICE\s*[:|]?\s*(?:USD|US\$|\$)?\s*([\d.]+)", text, re.I)
    if m:
        out["fabric_rate"] = _num(m.group(1))
    m = re.search(r"(?:PRODUCTION\s*)?LEAD\s*TIME\s*[:|]?\s*(\d{1,3})\s*(?:DAYS|D)\b", text, re.I)
    if m:
        out["lead_time_days"] = int(m.group(1))
    m = re.search(r"\bYIELD\s*\|?\s*[\d.]+\s*(?:YD|YDS|YARD)?\s*\|?\s*([\d.]+)", text, re.I) or \
        re.search(r"ESTIM\s*ATED\s*YIELD\s*[:|]?\s*([\d.]+)", text, re.I)
    if m:
        out["yield_per_pc"] = _num(m.group(1))

    grid = _size_grid(text, layout)
    if grid and grid.get("grid"):
        out["grid"] = grid["grid"]
        out["grid_confidence"] = grid.get("confidence")
        if out.get("qty") and sum(grid["grid"].values()) != out["qty"]:
            out["grid_total"] = sum(grid["grid"].values())
    return out


def _extract_lines(doc: str, facts: dict, layout: list | None = None) -> list[dict]:
    """Colour / size lines, from either a labelled list or a table.

    Two shapes are understood:
      1. inline list   ``Colours : Eucalyptus 1200, Ivory 800``   (confidence .9)
      2. table rows    ``Eucalyptus | #7C9A86 | 1,200 | 48``      (confidence .85)

    A row is only accepted when it looks like a row: at least three cells, the
    first cell a real word (not a label), a quantity of 10+ in a later cell. A
    loose pattern read ``Purchase Order | AO-5644`` as a colour line on the first
    real PO (2026-11-03) — that is what this rule prevents.
    """
    lines: list[dict] = []
    seen: set[str] = set()

    po_number = _int((facts.get("po") or {}).get("number")) if str((facts.get("po") or {}).get("number") or "").isdigit() else None

    def _add(name, qty, shade=None, cartons=None, conf=0.85):
        key = _slug(name or "")
        if not name or not qty or qty < 10 or len(key) < 3:
            return
        if key in seen or key in _LABEL_WORDS or key in ("total", "sub total", "colour", "color", "shade"):
            return
        # a document header ("EMJ APPAREL GROUP | 70465 12/11/2025 | EM92420") is
        # not a colour line — the giveaway is a qty equal to the PO number itself
        if po_number and int(qty) == po_number:
            return
        if re.search(r"\b(apparel|group|ltd|limited|llc|inc|gmbh|corp|company|holdings)\b", name, re.I):
            return
        seen.add(key)
        lines.append({"colour": name.strip(), "shade": shade, "qty": int(qty),
                      "cartons": cartons if cartons and 0 < cartons < qty else None,
                      "rate": None, "size": None, "confidence": conf})

    # 1 · labelled list (the cleanest source — the buyer wrote it as a list)
    blob = ""
    for pat in (r"colou?r\s*(?:break\s*-?\s*up|breakup|ways?|s)?\s*[:\-]\s*([^\n]{3,200})",
                r"colou?rs?\s*[:\-]\s*([^\n]{3,200})"):
        m = re.search(pat, doc, re.I)
        if m:
            blob = m.group(1)
            break
    if blob:
        for part in re.split(r"[,;]|\band\b", blob):
            mm = re.match(r"\s*([A-Za-z][A-Za-z' .&/-]{1,30}?)\s*[:(]?\s*(\d[\d,]{2,7})\s*\)?", part.strip())
            if mm:
                _add(mm.group(1), _int(mm.group(2)), conf=0.9)

    # 2 · table rows — only lines that really are rows
    if not lines:
        for raw in doc.splitlines():
            line = raw.strip()
            if not line or not re.search(r"\||\t|\s{2,}", line):
                continue
            cells = [c.strip() for c in re.split(r"\s*\|\s*|\t|\s{2,}", line) if c.strip()]
            if len(cells) < 3:
                continue
            name = cells[0]
            if not re.fullmatch(r"[A-Za-z][A-Za-z' &/.-]{2,30}", name):
                continue
            shade = next((c for c in cells[1:] if re.fullmatch(r"#[0-9A-Fa-f]{6}", c)), None)
            # a cell may hold "250 23.00" — the qty is the leading integer; a price
            # always carries a decimal point, so it is never mistaken for a qty
            nums = []
            for i, c in enumerate(cells):
                for tok in c.split():
                    if tok.isdigit():
                        nums.append((i, int(tok)))
            nums = [(i, v) for i, v in nums if v and v >= 10]
            if not nums:
                continue
            qty = nums[0][1]
            cartons = nums[1][1] if len(nums) > 1 else None
            _add(name, qty, shade, cartons, conf=0.85)

    # 3 · a single-line order with no colour split → one unnamed line
    if not lines and facts.get("commercial", {}).get("total_qty"):
        lines.append({"colour": None, "shade": None, "qty": facts["commercial"]["total_qty"],
                      "cartons": None, "rate": facts.get("commercial", {}).get("rate"),
                      "size": None, "confidence": 0.6})

    # enrich a list-read line with the paper's table columns (shade, cartons)
    if lines:
        by_slug = {_slug(l.get("colour") or ""): l for l in lines if l.get("colour")}
        for raw in doc.splitlines():
            if not re.search(r"\||\t|\s{2,}", raw.strip()):
                continue
            cells = [c.strip() for c in re.split(r"\s*\|\s*|\t|\s{2,}", raw.strip()) if c.strip()]
            if len(cells) < 3:
                continue
            key = _slug(cells[0])
            line = by_slug.get(key)
            if not line:
                continue
            shade = next((c for c in cells[1:] if re.fullmatch(r"#[0-9A-Fa-f]{6}", c)), None)
            nums = [_int(c) for c in cells[1:] if re.fullmatch(r"[\d,]+", c)]
            nums = [n for n in nums if n]
            if shade and not line.get("shade"):
                line["shade"] = shade
            if len(nums) > 1 and nums[1] < (line.get("qty") or 0) and not line.get("cartons"):
                line["cartons"] = nums[1]

    # carry the header rate onto lines that have none (a PO prints one rate)
    rate = facts.get("commercial", {}).get("rate")
    for line in lines:
        if line.get("rate") is None and rate:
            line["rate"] = rate

    # The size grid is evidence in its own right. It used to be attached ONLY when a
    # colour line had already been parsed, so a paper whose grid was read perfectly
    # was reported as "no size grid on the PO" (PO 70795, 2026-11-03). Read it
    # unconditionally; use it as the quantity when it is the only quantity present.
    sizes = re.findall(r"\b(XXS|XS|S|M|L|XL|XXL|2XL|3XL)\b", doc)
    if len({s.upper() for s in sizes}) >= 3:
        grid = _size_grid(doc, layout)
        if grid and grid.get("grid"):
            gsum = sum(grid["grid"].values())
            if not lines:
                lines.append({"colour": None, "shade": None, "qty": gsum, "cartons": None,
                              "rate": None, "size": None, "confidence": 0.6,
                              "qty_source": "size grid"})
            for line in lines:
                # one line + a grid = this line's grid. Several lines: attach only
                # where the total ties, otherwise the grid belongs to another line.
                if len(lines) > 1 and abs(gsum - (line.get("qty") or 0)) > max(2, gsum * 0.02):
                    continue
                line["size_grid"] = grid.get("grid")
                line["size_confidence"] = grid.get("confidence")
                if line.get("qty") != gsum:
                    line.setdefault("grid_total", gsum)
    return lines


_SIZE_RE = re.compile(r"^(?:XXS|XS|S|M|L|XL|XXL|2XL|3XL|4XL)$", re.I)


def _rows_from_layout(layout: list) -> list[tuple[int, list[tuple[float, str]]]]:
    """Group positioned tokens into visual rows, per page.

    A PDF's text carries no rows — only coordinates. Two lines 3 pt apart on the
    same page are one row; the same y on a different page is not.
    """
    if not layout:
        return []
    pages: dict[int, list[dict]] = {}
    for item in layout:
        try:
            if len(item) >= 4:
                page, y, x, text = int(item[0]), float(item[1]), float(item[2]), str(item[3])
            else:
                page, y, x, text = 0, float(item[0]), float(item[1]), str(item[2])
        except Exception:
            continue
        rows = pages.setdefault(page, [])
        for row in rows:
            if abs(row["y"] - y) <= 3:
                row["t"].append((x, text))
                break
        else:
            rows.append({"y": y, "t": [(x, text)]})
    out = []
    for page in sorted(pages):
        for row in sorted(pages[page], key=lambda r: -r["y"]):
            out.append((page, sorted(row["t"], key=lambda p: p[0])))
    return out


def _size_grid(doc: str, layout: list | None = None) -> dict | None:
    """The size grid, read by COLUMN position.

    A buyer's PO prints the sizes on one line and the quantities on the line
    below, aligned under each size. Reading the numbers in order and pairing them
    with the sizes in order is a guess (EMJ 70465 prints 7 sizes and 4 numbers).
    Mapping each number to the nearest size *by x* is not: 44 sits at x=135 under
    XS at x=136. Anything that cannot be placed within 25 pt is left blank.
    """
    rows = _rows_from_layout(layout or [])
    if rows:
        for i, (page, row) in enumerate(rows):
            sizes = [(x, t.upper()) for x, t in row if _SIZE_RE.match(t.strip())]
            if len(sizes) < 3:
                continue
            # the quantities sit a few lines BELOW the header, on the same page
            for j in range(i + 1, min(i + 6, len(rows))):
                bpage, below = rows[j]
                if bpage != page:
                    break
                nums = [(x, int(t.replace(",", ""))) for x, t in below
                        if re.fullmatch(r"[\d,]{1,5}", t.strip())
                        and 0 <= int(t.replace(",", "")) < 100000]
                if not nums:
                    continue
                grid, used = {}, 0
                for x, qty in nums:
                    nearest = min(sizes, key=lambda sv: abs(sv[0] - x))
                    if abs(nearest[0] - x) <= 25 and nearest[1] not in grid:
                        grid[nearest[1]] = qty
                        used += 1
                if used >= 2:
                    return {"grid": grid, "confidence": round(min(0.9, 0.55 + 0.05 * used), 2),
                            "method": "column"}
            break

    # fallback: header line, then a numeric line of the same length (text only)
    lines = (doc or "").splitlines()
    for i, line in enumerate(lines):
        cells = [c.strip() for c in re.split(r"\s*\|\s*|\t|\s{2,}", line) if c.strip()]
        size_cells = [c for c in cells if _SIZE_RE.match(c)]
        if len(size_cells) >= 3 and i + 1 < len(lines):
            nums = [int(c.replace(",", "")) for c in re.split(r"\s*\|\s*|\t|\s{2,}", lines[i + 1])
                    if re.fullmatch(r"[\d,]{1,5}", c.strip())]
            if len(nums) == len(size_cells):
                return {"grid": dict(zip([s.upper() for s in size_cells], nums)), "confidence": 0.7,
                        "method": "row"}
    return None


def _extract_claims(body: str) -> tuple[list[str], list[str]]:
    """Sentences that bind us (claims) and sentences that ask us something (asks).

    Labelled field lines (``Fabric : interlock 220 GSM``) are data, not prose, and
    are skipped — otherwise the whole header block ends up as one "claim".
    """
    if not body:
        return [], []
    claims, asks = [], []
    for line in re.split(r"\n+", body):
        text = re.sub(r"\s{2,}", " ", line).strip()
        if not text:
            continue
        if re.match(r"^[A-Za-z][A-Za-z /()]{1,24}\s*[:\-]", text) and len(text) < 120:
            continue                                    # a labelled field, not a sentence
        for s in re.split(r"(?<=[.!?])\s+", text):
            low = s.lower().strip()
            if len(low) < 12 or len(low) > 320:
                continue
            if "please find" in low or ("attached" in low and "purchase order" in low):
                continue
            if any(h in low for h in _ASK_HINTS):
                asks.append(s.strip())
            elif any(h in low for h in _CLAIM_HINTS):
                claims.append(s.strip())

    def _dedupe(rows):
        out, seen = [], set()
        for r in rows:
            k = _slug(r)[:80]
            if k and k not in seen:
                seen.add(k)
                out.append(r)
        return out[:8]

    return _dedupe(claims), _dedupe(asks)


def _finish(facts: dict) -> None:
    """Fill derived fields, list what is missing, and drop impossible values."""
    c = facts["commercial"]
    if c.get("total_qty") is None and facts.get("lines"):
        q = sum((l.get("qty") or 0) for l in facts["lines"])
        if q:
            _set(facts, "commercial.total_qty", q, 0.8)
    if facts["lines"] and not c.get("total_value"):
        total = sum((_num(l.get("qty")) or 0) * (_num(l.get("rate")) or 0) for l in facts["lines"])
        if total:
            _set(facts, "commercial.total_value", round(total, 2), 0.8)
    if facts["lines"] and c.get("rate") is None:
        for line in facts["lines"]:
            if line.get("rate"):
                _set(facts, "commercial.rate", line["rate"], 0.7)
                break

    missing = []
    if not facts["po"]["number"]:
        missing.append("po number")
    if not facts["buyer"]["name"]:
        missing.append("buyer name")
    if not c.get("currency"):
        missing.append("currency")
    if not c.get("total_qty"):
        missing.append("quantity")
    if not c.get("rate"):
        missing.append("rate")
    if not facts["ship_date"]:
        missing.append("ship date")
    if not facts["style"]["code"]:
        missing.append("style code")
    if facts["document_type"] in ("purchase_order", "po_revision"):
        if facts["lines"] and any(l.get("size_grid") for l in facts["lines"]):
            pass
        else:
            missing.append("size grid")
    facts["missing"] = missing


# ────────────────────────────────────────────────────────────────────────────
# Arithmetic gates
# ────────────────────────────────────────────────────────────────────────────
def check_arithmetic(facts: dict) -> dict:
    """Tie the numbers up. A field that fails its gate is demoted, never deleted."""
    checks = []
    c = facts["commercial"]
    lines = facts.get("lines") or []

    def _note(name: str, ok: bool | None, detail: str, demote: list[str] | None = None):
        checks.append({"check": name, "ok": ok, "detail": detail})
        if ok is False and demote:
            for p in demote:
                cur = _conf(facts, p)
                if cur:
                    facts["confidence"][p] = round(min(cur, 0.5), 2)

    # Σ lines == total
    if lines and c.get("total_qty"):
        s = sum((l.get("qty") or 0) for l in lines)
        ok = (s == c["total_qty"]) if s else None
        _note("lines_sum_matches_total", ok, f"Σ lines {s:,} vs total {c['total_qty']:,}",
              ["commercial.total_qty"] if ok is False else None)
        if ok is False and s:
            # trust the lines (they carry the colour split) and say the header disagrees
            facts["conflicts"].append({
                "field": "commercial.total_qty",
                "kept": s, "other": c["total_qty"],
                "reason": "sum of the colour lines differs from the stated total"})
            c["total_qty"] = s
            facts["confidence"]["commercial.total_qty"] = 0.6

    # rate × qty == value
    if c.get("rate") and c.get("total_qty") and c.get("total_value"):
        calc = round(c["rate"] * c["total_qty"], 2)
        ok = abs(calc - c["total_value"]) <= max(1.0, c["total_value"] * 0.005)
        _note("rate_times_qty_equals_value", ok,
              f"{c['rate']:,.2f} × {c['total_qty']:,} = {calc:,.2f} vs stated {c['total_value']:,.2f}",
              ["commercial.total_value"] if ok is False else None)
        if ok is False:
            facts["conflicts"].append({
                "field": "commercial.total_value", "kept": calc, "other": c["total_value"],
                "reason": "the stated value does not equal rate × quantity"})
            c["total_value"] = calc

    # Σ size grid == colour qty
    for i, line in enumerate(lines):
        grid = line.get("size_grid")
        if grid and line.get("qty"):
            s = sum(grid.values())
            ok = (s == line["qty"])
            _note(f"size_grid_line_{i + 1}", ok,
                  f"{line.get('colour') or 'line'}: Σ sizes {s:,} vs qty {line['qty']:,}",
                  [f"lines.{i}.size_grid"] if ok is False else None)
    if checks and not any(x["ok"] for x in checks):
        facts.setdefault("quality_flags", []).append("arithmetic_unverified")

    # ship after PO date
    if facts.get("ship_date") and facts["po"].get("date"):
        try:
            ok = date.fromisoformat(facts["ship_date"]) > date.fromisoformat(facts["po"]["date"])
        except Exception:
            ok = None
        _note("ship_after_po_date", ok, f"ship {facts['ship_date']} vs PO {facts['po']['date']}",
              ["ship_date"] if ok is False else None)

    # rate sanity: a garment rate of 3,00,000 is a value, not a rate
    if c.get("rate") and c.get("total_qty") and c.get("total_value"):
        implied = c["total_value"] / c["total_qty"] if c["total_qty"] else 0
        ok = abs(implied - c["rate"]) <= max(0.5, implied * 0.01)
        _note("rate_equals_value_per_piece", ok,
              f"value/qty = {implied:,.2f} vs rate {c['rate']:,.2f}", ["commercial.rate"] if ok is False else None)

    facts["arithmetic"] = checks
    return facts


# ────────────────────────────────────────────────────────────────────────────
# Merge two extractions
# ────────────────────────────────────────────────────────────────────────────
def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in (d or {}).items():
        path = f"{prefix}{k}"
        if isinstance(v, dict) and k not in ("confidence", "missing", "conflicts", "extractors"):
            out.update(_flatten(v, path + "."))
        else:
            out[path] = v
    return out


_MERGE_PATHS = (
    "document_type", "buyer.name", "buyer.country", "buyer.address", "buyer.contact", "buyer.email",
    "buyer.phone", "to.name", "to.address", "to.phone", "to.email",
    "po.number", "po.date", "po.reference", "commercial.currency", "commercial.rate",
    "commercial.incoterm", "commercial.named_place", "commercial.payment_terms",
    "commercial.total_qty", "commercial.total_value", "ship_date", "season",
    "style.code", "style.description", "style.fabric", "style.composition", "style.gsm",
    "style.fabric_code", "style.yield_per_pc", "quality.aql_major", "quality.aql_minor",
    "quality.carton_ratio", "lead_time_days", "commercial.fabric_rate",
)


def _get(facts: dict, path: str):
    node = facts
    for p in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(p)
    return node


def _det_strength(facts: dict) -> float:
    """How much the pattern read can be trusted on this document.

    A PO printed as ``Label : value`` scores ~0.95. A dense buyer sheet (EMJ's
    two-column PO) has almost no labels, so the pattern read picks up neighbouring
    numbers — it "reads" the fabric price as the garment rate. That is not a
    disagreement between two readers, it is one reader out of its depth, and the
    strength score is what lets the merge tell the two apart.
    """
    conf = facts.get("confidence") or {}
    vals = [float(conf.get(p) or 0) for p in _STRICT_FIELDS if p in conf]
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


def merge(det: dict, llm: dict | None) -> dict:
    """Merge the LLM read into the deterministic one, field by field."""
    if not llm:
        return det
    facts = det
    det_rate_before = _num((det.get("commercial") or {}).get("rate"))
    facts["extractors"].append("llm")
    facts["_det_strength"] = round(_det_strength(facts), 2)
    llm_conf = (llm.get("confidence") or {}) if isinstance(llm.get("confidence"), dict) else {}
    for path in _MERGE_PATHS:
        lv = _get(llm, path)
        if lv in (None, "", [], {}):
            continue
        dv = _get(facts, path)
        lc = float(llm_conf.get(path, 0.8) or 0.8)
        if dv in (None, "", [], {}):
            _set(facts, path, lv, lc)
            continue
        if _field_same(path, dv, lv):
            # agreement is evidence: lift the confidence
            facts["confidence"][path] = round(min(0.99, max(_conf(facts, path), lc) + 0.05), 2)
            continue
        # Disagreement. Which one to keep depends on the KIND of field, not on
        # who read it: a code/number/date is decided by the paper, but a free-text
        # field is decided by completeness ("Jonas Feld" beats the mailbox alias
        # "test4user"; "interlock 220 GSM" beats the model's "interlock").
        winner, reason = _resolve_disagreement(path, dv, lv, _conf(facts, path), lc,
                                               facts.get("_det_strength", 1.0), facts)
        if winner is not dv:
            _set(facts, path, winner, min(lc, 0.8))
        if reason:
            facts["conflicts"].append({"field": path, "kept": winner, "other": (lv if winner is dv else dv),
                                       "reason": reason})
        # a value the paper proves keeps its own confidence; a contested one is
        # demoted so a human looks at it.
        proved = winner is dv and reason.startswith("the paper")
        facts["confidence"][path] = (_conf(facts, path) if proved
                                     else round(min(_conf(facts, path) or lc, 0.7), 2))

    facts.pop("_det_strength", None)
    merged_rate = (facts.get("commercial") or {}).get("rate")
    det_rate = det_rate_before
    if merged_rate and det_rate and abs(_num(merged_rate) - _num(det_rate)) > 0.001:
        for line in facts.get("lines") or []:
            if line.get("rate") and abs(_num(line["rate"]) - _num(det_rate)) < 0.001:
                line["rate"] = merged_rate
    if isinstance(llm.get("lines"), list) and llm["lines"]:
        facts["lines"] = _merge_lines(facts.get("lines") or [], llm["lines"])
    for key in ("claims", "asks"):
        for item in (llm.get(key) or []):
            if isinstance(item, str) and len(item) > 8 and item not in facts[key]:
                facts[key].append(item)
    facts["claims"] = facts["claims"][:8]
    facts["asks"] = facts["asks"][:8]
    _finish(facts)
    return facts


def _is_free_mail(addr: str) -> bool:
    dom = (addr or "").split("@")[-1].lower()
    return any(dom.endswith(f) or dom.startswith(f) for f in _FREE_MAIL)


def _same_domain_hint(addr: str, cand_slug: str) -> bool:
    """``service@belladahl.com`` ↔ ``bella dahl`` — the domain carries the name."""
    dom = (addr or "").split("@")[-1].lower()
    root = dom.split(".")[0]
    flat = (cand_slug or "").replace(" ", "")
    return bool(root) and (root in flat or flat in root) and len(root) >= 4


# Fields decided by the paper (a code, a number, a date) vs fields decided by
# completeness (a description, a contact name, an address).
_STRICT_FIELDS = ("po.number", "po.date", "ship_date", "commercial.currency",
                  "commercial.rate", "commercial.total_qty", "commercial.total_value",
                  "commercial.incoterm", "style.code", "style.gsm", "quality.aql_major",
                  "quality.aql_minor", "quality.carton_ratio", "document_type")


def _numbers_tie(facts: dict) -> bool:
    """Do the paper's own numbers agree? ``qty x rate == total``, to the cent.

    This is the difference between "the pattern reader *found* a number" and "the
    paper *states* it". A consistent triple cannot be a mis-grab: no other field on
    the page would satisfy it. So the model is not allowed to override it — on
    PO 70795 the model read the FABRIC price (2.95) and the deterministic form read
    the garment price (13.60), and only one of them multiplies out to 10,880.00
    (2026-11-03).
    """
    c = facts.get("commercial") or {}
    q, r, v = _num(c.get("total_qty")), _num(c.get("rate")), _num(c.get("total_value"))
    if not q or not r or not v:
        return False
    return abs(q * r - v) <= max(1.0, v * 0.005)


def _fails_the_date_gate(facts: dict, value) -> bool:
    """A ship date on or before the PO date is not a ship date."""
    po_date = (facts.get("po") or {}).get("date")
    if not po_date or not value:
        return False
    try:
        return str(value) <= str(po_date)
    except Exception:
        return False


def _resolve_disagreement(path: str, dv, lv, dc: float, lc: float, det_strength: float = 1.0,
                          facts: dict | None = None):
    """Pick a winner for a contested field. Returns (value, reason_to_record)."""
    if path in _STRICT_FIELDS:
        # A value the paper itself proves outranks the model's opinion, whatever the
        # overall pattern hit rate was.
        if facts is not None:
            if path.startswith("commercial.") and _numbers_tie(facts):
                return dv, "the paper's numbers tie (qty x rate = total) — the model's value is not used"
            if path == "ship_date" and _fails_the_date_gate(facts, lv) and not _fails_the_date_gate(facts, dv):
                return dv, "the model's ship date is on or before the PO date — the paper's date kept"
        if det_strength < 0.75 and lc >= max(dc, 0.85):
            # the pattern reader could not find this field's own label on this
            # layout, and the model read it with high confidence → the model wins
            return lv, "pattern read was weak on this layout — the model's value kept"
        return dv, "extractors disagree — the paper wins on a number, code or date"
    ds, ls = _slug(str(dv)), _slug(str(lv))
    # one contains the other → keep the more complete one, it is not a conflict
    if ds and ls and (ds in ls or ls in ds):
        winner = lv if len(ls) > len(ds) else dv
        return winner, ""
    if abs(lc - dc) < 0.15:
        winner = lv if len(ls) > len(ds) else dv
        return winner, "extractors disagree — the fuller value kept"
    winner = lv if lc > dc else dv
    return winner, "extractors disagree — the more confident reader kept"


def _field_same(path: str, a, b) -> bool:
    """Same value? PO numbers compare on their comparable core, everything else on text."""
    if path in ("po.number", "po.reference"):
        return bool(po_core(str(a))) and po_core(str(a)) == po_core(str(b))
    return _same(a, b)


def _same(a, b) -> bool:
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        na, nb = _num(a), _num(b)
        return na is not None and nb is not None and abs(na - nb) < 0.01
    return _slug(str(a)) == _slug(str(b))


def _merge_lines(det_lines: list[dict], llm_lines: list[dict]) -> list[dict]:
    """Keep the deterministic line order; add what only the LLM read."""
    by_key = {_slug(l.get("colour") or "") or str(i): l for i, l in enumerate(det_lines)}
    out = []
    for i, ll in enumerate(llm_lines):
        if not isinstance(ll, dict):
            continue
        key = _slug(ll.get("colour") or ll.get("colour_name") or "")
        base = by_key.get(key) or (det_lines[i] if i < len(det_lines) else {})
        line = dict(base)
        for src, dst in (("colour", "colour"), ("colour_name", "colour"), ("color", "colour"),
                         ("shade", "shade"), ("qty", "qty"), ("quantity", "qty"),
                         ("rate", "rate"), ("price", "rate"), ("size", "size"),
                         ("cartons", "cartons"), ("size_grid", "size_grid")):
            if ll.get(src) not in (None, "") and line.get(dst) in (None, ""):
                line[dst] = _int(ll[src]) if dst in ("qty", "cartons") else (
                    _num(ll[src]) if dst == "rate" else ll[src])
        if line.get("qty"):
            out.append(line)
    if not out:
        return det_lines
    # keep any deterministic line the model missed
    have = {_slug(l.get("colour") or "") for l in out}
    for l in det_lines:
        if (_slug(l.get("colour") or "") not in have) and l.get("qty"):
            out.append(l)
    return out


# ────────────────────────────────────────────────────────────────────────────
# LLM extractor (optional — the pipeline works without it)
# ────────────────────────────────────────────────────────────────────────────
_SCHEMA_HINT = """Return ONE JSON object, no prose, with exactly these keys:
{
 "document_type": "purchase_order|po_revision|enquiry|invoice|remittance|other",
 "buyer": {"name": str|null, "country": str|null, "address": str|null, "contact": str|null, "email": str|null, "phone": str|null},
 "to": {"name": str|null, "address": str|null, "phone": str|null, "email": str|null},
 "po": {"number": str|null, "date": "YYYY-MM-DD"|null, "reference": str|null},
 "commercial": {"currency": "USD|EUR|INR|HKD|VND|CNY|GBP"|null, "rate": number|null,
                "incoterm": str|null, "named_place": str|null, "payment_terms": str|null,
                "total_qty": number|null, "total_value": number|null},
 "ship_date": "YYYY-MM-DD"|null,
 "season": str|null,
 "style": {"code": str|null, "description": str|null, "fabric": str|null,
           "composition": str|null, "gsm": number|null, "fabric_code": str|null},
 "lines": [{"colour": str|null, "shade": str|null, "qty": number|null, "rate": number|null,
            "size": str|null, "size_grid": {"XS": 0}|null}],
 "quality": {"aql_major": number|null, "aql_minor": number|null, "carton_ratio": number|null},
 "claims": [str], "asks": [str],
 "confidence": {"po.number": 0.0, "commercial.rate": 0.0, "ship_date": 0.0}
}
Rules:
- Copy values EXACTLY as printed. Do not compute, convert, round or translate.
- A value that is not on the page is null. Never infer a quantity, a size grid or a price.
- "lines" = one entry per colour (or per size if the page is per size). qty = that row's quantity.
- "claims" = instructions that bind the factory (must/do not/ensure). "asks" = questions to answer.
- confidence is 0..1 per field: 1.0 = printed with a label, 0.5 = inferred from context."""


def extract_with_llm(db, text: str, subject: str = "", body: str = "", timeout: int = 150) -> dict | None:
    """Ask the agent to read the document into the schema. None when unavailable."""
    if db is None:
        return None
    try:
        import ai_nextsteps as _ai
    except Exception:
        return None
    blob = _clean(text or "")
    if len(blob) > 24000:
        blob = blob[:24000]
    body_txt = _clean(body or "")[:4000]
    prompt = (f"Read this buyer document and extract the order facts.\n\n_SCHEMA_\n{_SCHEMA_HINT}\n\n"
              f"EMAIL SUBJECT: {subject}\n\nATTACHMENT TEXT:\n{blob}\n\nEMAIL BODY:\n{body_txt}\n")
    try:
        raw = _ai._llm(db, prompt, timeout=timeout)
    except Exception:
        return None
    if not raw:
        return None
    data = _parse_json(raw)
    if not isinstance(data, dict):
        return None
    # normalise dates the model may have written in another shape
    for path in ("po.date", "ship_date"):
        v = _get(data, path)
        if v and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(v)):
            iso = _date_iso(str(v))
            if iso:
                node = data
                parts = path.split(".")
                for p in parts[:-1]:
                    node = node.setdefault(p, {})
                node[parts[-1]] = iso
    return data


def _parse_json(raw: str) -> dict | None:
    txt = str(raw or "")
    txt = re.sub(r"<think[^>]*>.*?</think>", "", txt, flags=re.S | re.I)
    txt = re.sub(r"```(?:json)?", "", txt).strip()
    start, end = txt.find("{"), txt.rfind("}")
    if start < 0 or end <= start:
        return None
    for blob in (txt[start:end + 1],):
        try:
            return json.loads(blob)
        except Exception:
            # trailing commas / smart quotes are the usual offenders
            fixed = re.sub(r",\s*([}\]])", r"\1", blob).replace("\u2019", "'")
            try:
                return json.loads(fixed)
            except Exception:
                continue
    return None


# ────────────────────────────────────────────────────────────────────────────
# Matching against the live ERP
# ────────────────────────────────────────────────────────────────────────────
def match(db, facts: dict, erp=None) -> dict:
    """Resolve the buyer, the PO, the style and the fabric to real records."""
    # Normalise the structured nodes before anything reads them. A hand correction
    # (``edit_intake``) or an older stored run can leave ``style`` as a bare string, and every
    # reader below assumes a dict — the crash surfaced as "'str' object has no attribute 'get'"
    # three call sites deep (2026-11-06). One normalisation here beats patching each site.
    for _node_key in ("style", "buyer", "po", "commercial", "delivery_window"):
        _v = facts.get(_node_key)
        if isinstance(_v, str):
            facts[_node_key] = {"code": _v} if _node_key == "style" else {"name": _v}
        elif _v is not None and not isinstance(_v, dict):
            facts[_node_key] = {}
    import erp as _erp
    erp = erp or _erp
    out = {"customer": None, "customer_created": False, "customer_candidates": [],
           "po_existing": None, "po_revision_of": None, "style_item": None,
           "style_variants": [], "fabric_item": None, "fabric_mapping": None,
           "currency_rate": None, "warnings": [], "blocking": []}

    buyer_name = (facts.get("buyer") or {}).get("name") or ""
    buyer_email = (facts.get("buyer") or {}).get("email") or ""
    try:
        customers = erp.erp_get("Customer", fields=["name", "customer_name", "email_id"], limit=0) or []
    except Exception:
        customers = []

    # 1 · exact, then normalised, then domain, then fuzzy
    target = _company_slug(buyer_name)
    best, best_score = None, 0.0
    for c in customers:
        cand = _company_slug(c.get("customer_name") or c.get("name") or "")
        if not cand:
            continue
        score = 0.0
        if target and cand == target:
            score = 1.0
        elif target and (target in cand or cand in target) and min(len(cand), len(target)) >= 4:
            score = 0.85
        elif target:
            import difflib
            score = difflib.SequenceMatcher(None, target, cand).ratio()
        # The email is a TIE-BREAKER, never a trump card: a buyer's PO is often
        # sent from the brand's shared desk (belladahl.com) for the legal entity
        # (EMJ Apparel Group, LLC), and the two are different Customers here.
        if buyer_email and (c.get("email_id") or "").lower() == buyer_email.lower() and not _is_free_mail(buyer_email):
            if score >= 0.6:
                score = min(1.0, score + 0.05)
            elif not target or _same_domain_hint(buyer_email, cand):
                score = 0.9
        if score > best_score:
            best, best_score = c, score
    if best and best_score >= 0.85:
        out["customer"] = best.get("name")
    elif best and best_score >= 0.6:
        out["customer_candidates"] = [{"name": best.get("name"), "score": round(best_score, 2)}]
        out["warnings"].append(f"buyer match is not certain ({best.get('name')} · {best_score:.0%})")
    else:
        out["warnings"].append("buyer does not exist in the ERP — will be created on approval")

    # 1b · To / vendor → our own Company. The buyer addresses the PO to Cortex, and the
    #     specific entity decides the ledger (and prints on the CPO as "To"). Resolved here
    #     so `out["company"]` exists even when no currency was read.
    to_name = (facts.get("to") or {}).get("name") or ""
    try:
        companies = [c.get("name") for c in (erp.erp_get("Company", fields=["name"], limit=0) or [])]
    except Exception:
        companies = []
    out["company"] = _match_company(to_name, companies)

    # 2 · PO duplicate / revision — the key is (buyer, their number), never the number alone
    po_no = facts["po"].get("number")
    # What numbers this buyer prints, and which of them names the order (2026-11-03).
    # The classification is recorded on the plan so the executor writes typed rows instead of
    # guessing that the second number is an "EM" — it is one company's series, not the model's.
    try:
        import buyer_ref as _refs
        cls = _refs.classify(erp, out["customer"],
                             [facts["po"].get("number"), facts["po"].get("reference")])
        out["refs"] = cls["refs"]
        out["order_ref"] = cls["order_ref"]
        out["order_ref_label"] = cls["order_ref_label"]
        out["order_ref_type"] = cls["order_ref_type"]
        out["warnings"].extend(cls["warnings"])
    except Exception:                       # noqa: BLE001 — a reference model that fails must not
        out["refs"] = []                    # stop the plan; the CPO step then writes what it read
    if po_no:
        core = po_core(po_no)
        try:
            cpos = erp.erp_get("Client Purchase Order",
                               fields=["name", "client_po_no", "customer", "is_revision", "po_date",
                                       "linked_sales_order", "status", "total_qty", "order_ref"],
                               limit=0) or []
        except Exception:
            cpos = []
        for c in cpos:
            if po_core(c.get("client_po_no") or "") != core:
                continue
            if out["customer"] and c.get("customer") == out["customer"]:
                if not out["po_existing"]:
                    out["po_existing"] = c.get("name")
                    if facts["document_type"] == "po_revision":
                        out["po_revision_of"] = c.get("name")
                continue
            # Another company using the same digits is NORMAL — a PO number is unique per buyer,
            # not on the planet. Warn (it is worth a human glance when the buyer name was also
            # uncertain) and carry on; blocking here is what made the model work for one company
            # only (2026-11-03).
            out.setdefault("po_other_buyer", []).append(
                {"cpo": c.get("name"), "customer": c.get("customer")})
        if out.get("po_other_buyer"):
            others = ", ".join(f'{d["cpo"]} ({d["customer"]})' for d in out["po_other_buyer"])
            out["warnings"].append(
                f"PO {po_no} is also on file for another buyer: {others} — the number is per buyer")
            # Only a genuinely uncertain buyer is worth stopping for: if we cannot name the buyer,
            # creating a record may twin an order that already exists under its real name.
            if not out["customer"] and not out["customer_candidates"]:
                out["blocking"].append("po_number_on_file_for_another_buyer")

    # 3 · style
    # ``style`` is normally a structured node, but a hand edit (edit_intake) can leave a bare
    # string here — read both, or one malformed fact takes the whole match down (2026-11-06).
    style_node = facts.get("style")
    style_code = style_node.get("code") if isinstance(style_node, dict) else (style_node or "")
    if style_code:
        try:
            items = erp.erp_get("Item", fields=["name", "item_name", "has_variants", "custom_material_type"],
                                limit=0) or []
        except Exception:
            items = []
        base = style_code.upper()
        variants = [i["name"] for i in items
                    if (i.get("name") or "").upper().startswith(base + "-")
                    and (i.get("has_variants") or 0) == 0]
        template = next((i["name"] for i in items
                         if (i.get("name") or "").upper() == base and i.get("has_variants")), None)
        out["style_item"] = template or (base if any((i.get("name") or "").upper() == base for i in items) else None)
        out["style_variants"] = variants
        if not out["style_item"]:
            out["warnings"].append(f"style {base} is new — a template and one SKU per size will be created")

    # 4 · fabric — through the Item Mapping register only (never a bare code guess)
    fabric_code = (facts.get("style") or {}).get("fabric_code")
    fabric_text = (facts.get("style") or {}).get("fabric") or ""
    try:
        mappings = erp.erp_get("Item Mapping",
                               fields=["name", "customer", "buyer_code", "our_item", "status"], limit=0) or []
    except Exception:
        mappings = []
    if fabric_code:
        for m in mappings:
            if (m.get("buyer_code") or "").upper() == fabric_code.upper() and (
                    not out["customer"] or m.get("customer") == out["customer"]):
                out["fabric_mapping"] = m.get("name")
                out["fabric_item"] = m.get("our_item")
                break
    if not out["fabric_item"] and fabric_text:
        try:
            items = erp.erp_get("Item", fields=["name", "item_name", "custom_material_type"], limit=0) or []
        except Exception:
            items = []
        words = [w for w in re.findall(r"[A-Za-z]{4,}", fabric_text.lower())][:4]
        best, best_hits = None, 0
        for i in items:
            if (i.get("custom_material_type") or "").lower() != "fabric":
                continue
            hay = (i.get("item_name") or "").lower()
            hits = sum(1 for w in words if w in hay)
            if hits > best_hits:
                best, best_hits = i.get("name"), hits
        if best and best_hits >= 2:
            out["fabric_item"] = best
            out["warnings"].append(f"fabric matched by description, not by Item Mapping ({best})")
    if not out["fabric_item"]:
        out["blocking"].append("fabric_not_mapped")

    # 5 · currency rate against the SELLING COMPANY's currency (not the app default:
    #     CTXHK books in HKD, so a USD order needs USD→HKD or the GL is fiction)
    currency = (facts.get("commercial") or {}).get("currency")
    if currency:
        company_currency = config.DEFAULT_CURRENCY
        company = out.get("company") or ""
        if not company:
            # the selling entity decides the ledger currency, so resolve it here —
            # before the FX lookup, not after it
            try:
                companies = [c.get("name") for c in (erp.erp_get("Company", fields=["name"], limit=0) or [])]
                company = next((c for c in companies if "HK" in (c or "").upper()), None) or (companies[0] if companies else "")
                out["company"] = company
            except Exception:
                company = ""
        if company:
            try:
                co = erp.erp_doc("Company", company) or {}
                company_currency = co.get("default_currency") or company_currency
            except Exception:
                pass
        out["company_currency"] = company_currency
        if currency != company_currency:
            try:
                rows = erp.erp_get("Currency Exchange",
                                   fields=["name", "date", "from_currency", "to_currency", "exchange_rate"],
                                   filters=[["from_currency", "=", currency]], limit=50) or []
                pair = [r for r in rows if (r.get("to_currency") or "") == company_currency]
                if pair:
                    row = sorted(pair, key=lambda r: str(r.get("date") or ""))[-1]
                    out["currency_rate"] = float(row.get("exchange_rate") or 0) or None
                    out["currency_rate_date"] = row.get("date")
                else:
                    out["blocking"].append(f"no_fx_rate_{currency}_{company_currency}")
            except Exception:
                out["blocking"].append(f"no_fx_rate_{currency}")

    # 5b · defaults for a style we have never sold (an Item needs a group + a UOM)
    try:
        items2 = erp.erp_get("Item", fields=["name", "item_group", "stock_uom"], limit=0) or []
        sample = next((i for i in items2 if (i.get("name") or "")[:1].upper() == "C"
                       and "-" in (i.get("name") or "")), None)
        if sample:
            full = erp.erp_doc("Item", sample["name"]) or {}
            out["item_group"] = full.get("item_group") or sample.get("item_group")
            out["stock_uom"] = full.get("stock_uom") or sample.get("stock_uom")
    except Exception:
        pass

    # 6 · company (the selling entity)
    try:
        companies = [c.get("name") for c in (erp.erp_get("Company", fields=["name"], limit=0) or [])]
    except Exception:
        companies = []
    preferred = next((c for c in companies if "HK" in (c or "").upper()), None) or (companies[0] if companies else None)
    out["company"] = preferred
    return out


# ────────────────────────────────────────────────────────────────────────────
# Route
# ────────────────────────────────────────────────────────────────────────────
# ── what each attachment IS (a mail can carry several documents) ────────────
_KIND_HINTS = (
    ("revision", ("revised po", "revision", "amended", "supersedes", "change order")),
    ("purchase_order", ("purchase order", "p.o. no", "po no", "po number", "po#", "order no",
                        "order confirmation", "buyer po")),
    ("invoice", ("invoice", "tax invoice", "proforma", "debit note", "credit note")),
    ("tech_pack", ("tech pack", "techpack", "spec sheet", "measurement", "size spec",
                   "grading", "grade rule", "construction", "sketch")),
    ("bom", ("bill of material", "bom", "material list", "trim list", "fabric list",
             "consumption", "bom sheet")),
    ("remittance", ("remittance", "payment advice", "swift copy", "tt copy")),
)


def doc_kind(text: str, filename: str = "") -> str:
    """What is this ONE file? 2026-11-03: a mail carried 3 POs + 3 BOMs and the intake read
    the single biggest one, so two orders and every BOM were silently dropped.

    Filename first (a buyer names their files), then the first 4 000 characters of the text —
    a purchase order says "purchase order" on page 1, a BOM sheet says "bill of material".
    """
    name = (filename or "").lower()
    blob = f"{name}\n{(text or '')[:4000]}".lower()
    # a buyer names their files: "HL93312 PO71242 … PO.pdf", "… BOM.xlsx", "… tech pack.pdf"
    if (re.match(r"^po[\s_\-.]", name) or re.search(r"\bpo[\s_\-.]*\d", name)
            or re.search(r"purchase[\s_\-]?order", name) or re.search(r"\bpo\b", name)):
        return "purchase_order"
    if re.search(r"\b(tech[\s_-]?pack|spec)\b", name):
        return "tech_pack"
    if re.search(r"\bbom\b", name):
        return "bom"
    for kind, words in _KIND_HINTS:
        if any(w in name for w in words):
            return kind
    for kind, words in _KIND_HINTS:
        if any(w in blob for w in words):
            return kind
    return "other"


_ORDER_KINDS = ("purchase_order", "revision", "invoice", "remittance")


def is_order_document(kind: str) -> bool:
    return kind in _ORDER_KINDS


def route(facts: dict, matches: dict) -> str:
    """Which process does this mail start?"""
    dt = facts.get("document_type") or "other"
    # A document that IS a document always wins: an order in a live thread is still an
    # order, and an invoice is still an invoice. The chain only decides what to do with
    # mail that is not a document of its own.
    #
    # `enquiry` is checked AFTER the chain on purpose: `document_type` flips to enquiry on the
    # bare word "quote" (intake.py §document type), so a reply that says "thanks for the quote"
    # would otherwise start a second Opportunity inside a deal that is already open.
    if dt == "po_revision":
        return "revision"
    if dt == "purchase_order":
        return "new_order"
    if dt in ("invoice", "remittance"):
        return "finance"
    if (matches.get("chain") or {}).get("live"):
        return "chain_reply"
    if dt == "enquiry":
        return "enquiry"
    # an order-shaped mail with no PO words still starts an order
    if facts.get("po", {}).get("number") and facts.get("commercial", {}).get("total_qty"):
        return "new_order"
    return "other"


ROUTE_LABEL = {
    "new_order": "New purchase order",
    "revision": "PO revision",
    "enquiry": "Enquiry / RFQ",
    "chain_reply": "Reply in a live thread",
    "finance": "Invoice or remittance",
    "other": "General mail",
}

ROUTE_PROCESS = {
    "new_order": ["Customer", "Client Purchase Order (+ lines)", "Sales Order (draft)",
                  "Project", "BOM per size", "Fabric / Trim requisition"],
    "revision": ["Client Purchase Order (revision)", "Sales Order change proposal"],
    "enquiry": ["Customer (create or link)", "Opportunity", "Cost Sheet (draft)", "Quotation (draft)"],
    "chain_reply": ["Buyer Tech Pack + BOM per size (when the pack is attached)", "Answer the buyer"],
    "finance": ["Match invoice / payment", "Task"],
    "other": ["Task"],
}


def render_pages(layout: list, width_pt: float | None = None, char_pt: float = 4.4) -> list[dict]:
    """The customer's page as it is laid out — text placed back at its x.

    A buyer's PO is not a form we designed: every buyer sends its own sheet. So the
    honest way to show it is to put every string back where it was printed, columns
    and all, instead of re-flowing it into our idea of an order.
    """
    rows = _rows_from_layout(layout or [])
    if not width_pt:
        widest = max((float(x) for _, row in rows for x, _ in row), default=540.0)
        width_pt = min(max(widest + 80, 480), 900)
    pages: dict[int, list[str]] = {}
    for page, row in rows:
        chars = int(width_pt / char_pt)
        buf = [" "] * chars
        cursor = 0                      # where the last token ended
        for x, text in row:
            text = str(text)
            col = min(int(float(x) / char_pt), chars - 1)
            if col < cursor:            # never write over a neighbour: shift right
                col = min(cursor + 1, chars - 1)
            for i, ch in enumerate(text):
                if 0 <= col + i < chars:
                    buf[col + i] = ch
            cursor = col + len(text)
        line = "".join(buf).rstrip()
        line = re.sub(r" {3,}", "   ", line)
        if line.strip():
            pages.setdefault(page, []).append(line)
    return [{"page": p + 1, "lines": pages[p]} for p in sorted(pages)]
