"""Buyer enquiries — the register, and what we already know about every style asked for.

Why this exists
---------------
An enquiry mail opened a card, was approved into an Opportunity, and then… nowhere. It did
not sit anywhere a merchandiser would look, and it was read as if every style in it were
brand new. But a buyer re-asking about a style we made two seasons ago is the *easiest*
enquiry there is: we hold the cost sheet, the BOM, the tech pack and the price we last
sold it at, and the answer is already on file.

So this module does two things:

1. **The register.** One `buyer_inquiry` row per enquiry mail — buyer, styles, quantity,
   the date they want the quote by, what the mail asked, and where it stands
   (`new → costing → quoted → won | lost`). It is the place an enquiry sits.
2. **The history, per style.** For every style code in the mail it reads the live ERP and
   answers: have we made it (`Sales Order` lines) · have we costed it (`Cost Sheet`,
   `Item Price`) · do we have the BOM (`BOM` per size) · do we have the buyer's pack
   (`Buyer Tech Pack`) — and what did we last sell it for.

Nothing here writes to the ERP. The Opportunity and its lines are written by
``intake_exec`` (which calls :func:`lines`) — this module only reads.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Optional

import erp
from models import BuyerInquiryModel

# ── style codes ─────────────────────────────────────────────────────────────
# The client's own shapes, and ONLY them:
#   C9533-U71-725 · C2027-S84-304 · C7540-S99-304   a 1-3 letter prefix + digits, then a
#                                                    compound suffix — a style always has one
#   C9533 · C9112                                    a single letter + 4-5 digits
#   GGI-26-SS-131                                    the season sits in the middle
# Deliberately NOT matched: FUS004 / TH000 / BT301 / LB030 — those are trim and material
# codes in the same pack, and reading them as styles put 9 trim lines on the Opportunity
# (2026-11-03). A short letter-block + 3 digits is a material, not a garment.
_STYLE = re.compile(
    r"\b([A-Z]{2,4}-\d{2}-[A-Z]{2}-\d{2,4}"                       # GGI-26-SS-131
    r"|[A-Z]{1,3}\d{3,5}(?:[-/][A-Z0-9]{2,5})+"                     # C9533-U71-725 (compound)
    r"|[A-Z]\d{4,5}(?![0-9])(?![-/]))\b")                          # C9533 (bare style)

# Identifiers that look like a style and are not one: order numbers, PO numbers, document
# series. `EM92409` is an order, not a style (the Tower read one as a style on 2026-11-03).
_NOT_A_STYLE = {"EM", "PO", "P", "INV", "SAL", "BOM", "BTP", "BBOM", "CPO", "CTX", "CORTEX",
                "SKU", "REF", "TNA", "WIP", "FR", "TR", "CAD", "PP"}

_VERDICT_LABEL = {
    "made": "made before",
    "costed": "costed, never ordered",
    "on_file": "style on file, never costed",
    "new": "new style",
}


def styles_in(text: str, limit: int = 12) -> list[str]:
    """Every style code in the mail, longest form first, duplicates and look-alikes dropped."""
    blob = (text or "").upper()
    found: list[str] = []
    for m in _STYLE.finditer(blob):
        code = m.group(1).strip("-/")
        if code.split("-")[0][:2].strip("0123456789") and code[:2] in _NOT_A_STYLE:
            continue
        if len(code) < 5:
            continue
        if code not in found:
            found.append(code)
    # `C9533` inside `C9533-U71-725` is the same style, not a second one
    keep = [c for c in found if not any(o != c and o.startswith(c + "-") for o in found)]
    return keep[:limit]


def styles_for_mail(subject: str = "", body: str = "", doc_text: str = "",
                    limit: int = 12) -> list[str]:
    """The styles the buyer is ASKING about — read from the mail, completed by the pack.

    The ask comes from what the buyer wrote. The attachment is evidence, not the ask: the
    pack's material list names buttons and threads by code (`#J5031-FL` on a button line),
    and reading those as styles put four "styles" on one enquiry (2026-11-03).

    What the pack IS good for is completing a bare code: the subject says `C9533` and the
    pack says `C9533-U71-725`, and only the full code reaches the item master, the cost
    sheet and the sales history.
    """
    asked = styles_in(f"{subject or ''}\n{body or ''}", limit=limit)
    deep = styles_in(doc_text or "", limit=60)
    out: list[str] = []
    for code in asked:
        if "-" in code:
            out.append(code)
            continue
        full = sorted((d for d in deep if d.startswith(code + "-")), key=len, reverse=True)
        out.append(full[0] if full else code)
    for code in out:
        if code not in out[:out.index(code)]:
            pass
    out = list(dict.fromkeys(out))
    # if the mail itself carried the full code, drop the bare form it came from
    return [c for c in out if not any(o != c and o.startswith(c + "-") for o in out)][:limit]


# ── the pools: one read each, not one per style ─────────────────────────────
_POOL = {"at": 0.0, "pool": None}


def _pool(max_age: float = 60.0) -> dict:
    """The ERP reads the history needs, memoised for a minute.

    Planning and the register both ask for the same pools several times per click; the
    pool is keyed on nothing but the instance, so a short memo cannot go stale in a way
    that matters. ``refresh_history`` bypasses it by passing ``max_age=0``.
    """
    if _POOL["pool"] is not None and (time.time() - _POOL["at"]) < max_age:
        return _POOL["pool"]
    pool = _pool_read()
    _POOL.update({"at": time.time(), "pool": pool})
    return pool


def _pool_read() -> dict:
    """Everything the history needs, read once. Failures are recorded, never swallowed."""
    out: dict = {"items": [], "prices": [], "costs": [], "boms": [], "packs": [],
                 "orders": [], "errors": []}

    def take(key, doctype, fields, **kw):
        ok, rows = erp.erp_get_checked(doctype, fields=fields, limit=0, **kw)
        if not ok:
            out["errors"].append(f"{doctype}: read failed")
            return []
        out[key] = rows
        return rows

    take("items", "Item", ["name", "item_name", "has_variants", "item_group", "stock_uom",
                           "disabled", "variant_of"])
    take("prices", "Item Price", ["item_code", "price_list_rate", "currency", "valid_from"])
    take("costs", "Cost Sheet", ["name", "buyer_style_ref", "customer", "total_fob",
                                 "locked_fob", "status", "valid_till", "delivery_date",
                                 "opportunity"])
    take("boms", "BOM", ["name", "item", "is_active", "docstatus", "creation"])
    take("packs", "Buyer Tech Pack", ["name", "style_no", "pack_revision", "status"])
    # the orders, with their lines: a style's last price lives on a line, not on the header
    soles = take("orders", "Sales Order", ["name", "customer", "transaction_date", "status",
                                           "grand_total", "currency", "items"])
    detailed = []
    for so in soles or []:
        doc = erp.erp_doc("Sales Order", so.get("name")) if not so.get("items") else so
        if not doc:
            continue
        detailed.append(doc)
    out["orders"] = detailed
    return out


def _style_base(code: str) -> str:
    return (code or "").upper().strip()


def history(style: str, pool: Optional[dict] = None) -> dict:
    """What the ERP already knows about one style. Reads only."""
    pool = pool or _pool()
    code = _style_base(style)
    out = {"style": code, "verdict": "new", "label": _VERDICT_LABEL["new"],
           "errors": list(pool.get("errors") or []),
           "item": None, "sizes": [], "uom": "", "item_group": "",
           "price": None, "cost": None, "bom": {"count": 0, "names": []},
           "tech_pack": None, "orders": [], "order_count": 0, "last_order": None,
           "last_price": None, "currency": ""}

    # 1 · the item master — the template is the style, one SKU per size
    items = pool.get("items") or []
    template = next((i for i in items if (i.get("name") or "").upper() == code), None)
    variants = [i for i in items
                if (i.get("name") or "").upper().startswith(code + "-")
                and not i.get("has_variants")]
    if template:
        out["item"] = template.get("name")
        out["uom"] = template.get("stock_uom") or ""
        out["item_group"] = template.get("item_group") or ""
    out["sizes"] = sorted((v.get("name") or "")[len(code) + 1:] for v in variants) if variants else []

    # 2 · what we last sold it for
    rows = []
    for so in pool.get("orders") or []:
        for line in (so.get("items") or []):
            if (line.get("item_code") or "").upper().startswith(code):
                rows.append({"sales_order": so.get("name"), "customer": so.get("customer"),
                             "date": so.get("transaction_date"), "status": so.get("status"),
                             "item": line.get("item_code"), "qty": line.get("qty"),
                             "rate": line.get("rate"), "amount": line.get("amount"),
                             "currency": so.get("currency")})
    rows.sort(key=lambda r: (r.get("date") or ""), reverse=True)
    out["orders"] = rows
    out["order_count"] = len({r.get("sales_order") for r in rows})
    if rows:
        live = [r for r in rows if (r.get("status") or "") != "Cancelled"] or rows
        out["last_order"] = live[0]
        out["last_price"] = live[0].get("rate")
        out["currency"] = live[0].get("currency") or ""

    # 3 · the price list, when there is no order yet
    if out["last_price"] in (None, 0, 0.0):
        prices = [p for p in (pool.get("prices") or [])
                  if (p.get("item_code") or "").upper().startswith(code)]
        prices.sort(key=lambda p: (p.get("valid_from") or ""), reverse=True)
        if prices:
            out["price"] = prices[0]
            out["last_price"] = prices[0].get("price_list_rate")
            out["currency"] = out["currency"] or (prices[0].get("currency") or "")

    # 4 · the cost sheet drawn for this style
    costs = [c for c in (pool.get("costs") or [])
             if (c.get("buyer_style_ref") or "").upper().strip() == code]
    costs.sort(key=lambda c: c.get("name") or "", reverse=True)
    if costs:
        out["cost"] = costs[0]
        if out["last_price"] in (None, 0, 0.0):
            out["last_price"] = costs[0].get("locked_fob") or costs[0].get("total_fob")

    # 5 · the BOM per size, and the buyer's pack
    boms = [b for b in (pool.get("boms") or []) if (b.get("item") or "").upper().startswith(code)]
    active = [b for b in boms if int(b.get("is_active") or 0) == 1 and int(b.get("docstatus") or 0) == 1]
    out["bom"] = {"count": len(active) or len(boms),
                  "names": [b.get("name") for b in (active or boms)][:8],
                  "active": len(active)}
    packs = [p for p in (pool.get("packs") or [])
             if (p.get("style_no") or "").upper().strip() == code]
    packs.sort(key=lambda p: p.get("name") or "", reverse=True)
    if packs:
        out["tech_pack"] = packs[0]

    # 6 · the verdict — what a merchandiser needs to know before reading any further
    if out["orders"]:
        out["verdict"] = "made"
    elif out["cost"] or out["price"]:
        out["verdict"] = "costed"
    elif template or variants:
        out["verdict"] = "on_file"
    out["label"] = _VERDICT_LABEL[out["verdict"]]
    out["quote_ready"] = bool(out["verdict"] in ("made", "costed") and out["last_price"])
    return out


# ── the lines of one enquiry ────────────────────────────────────────────────
def lines(facts: dict, text: str = "", pool: Optional[dict] = None,
          codes: Optional[list[str]] = None) -> list[dict]:
    """One line per style in the mail, each carrying the ERP's history for it."""
    style = facts.get("style") or {}
    codes = ([c for c in (codes or []) if c]
             or [c for c in (facts.get("styles") or []) if c]
             or styles_in(text or "")
             or ([style.get("code")] if style.get("code") else []))
    if not codes:
        return []
    pool = pool or _pool()
    total = (facts.get("commercial") or {}).get("total_qty")
    out = []
    for code in codes:
        hist = history(code, pool)
        same = (style.get("code") or "").upper() == code
        out.append({
            "style": code,
            "description": (style.get("description") if same else "") or "",
            "colour": "",
            # one style in the mail = the mail's quantity belongs to it. Several styles and
            # no split = the split is unknown, and a guess would become a promise.
            "qty": total if (len(codes) == 1 and total) else None,
            **{k: hist[k] for k in ("verdict", "label", "quote_ready", "item", "sizes", "uom",
                                    "item_group", "price", "cost", "bom", "tech_pack",
                                    "orders", "order_count", "last_order", "last_price",
                                    "currency", "errors")},
        })
    return out


# ── the register ────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()[:40]


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def open_rows(db) -> list[BuyerInquiryModel]:
    return db.query(BuyerInquiryModel).order_by(BuyerInquiryModel.id.desc()).all()


def from_run(db, run, mail, text: str = "", refresh: bool = True) -> Optional[BuyerInquiryModel]:
    """Create or update the register row for one enquiry run."""
    facts = json.loads(run.facts or "{}")
    matches = json.loads(run.matches or "{}")
    buyer = facts.get("buyer") or {}
    c = facts.get("commercial") or {}
    # one enquiry per CONVERSATION: a follow-up in the same thread adds a style to the ask
    # that is already in the register instead of opening a second enquiry beside it
    chain_id = run.chain_id or getattr(mail, "chain_id", None)
    row = db.query(BuyerInquiryModel).filter(BuyerInquiryModel.run_id == run.id).first()
    if row is None and chain_id:
        row = (db.query(BuyerInquiryModel)
               .filter(BuyerInquiryModel.chain_id == chain_id)
               .order_by(BuyerInquiryModel.id.desc()).first())
    if row is None and run.mail_id:
        # the same mail read twice (a re-read, or a run opened again) is the same enquiry
        row = (db.query(BuyerInquiryModel)
               .filter(BuyerInquiryModel.mail_id == run.mail_id)
               .order_by(BuyerInquiryModel.id.desc()).first())
    fresh = row is None
    if fresh:
        row = BuyerInquiryModel(run_id=run.id, status="new")
        db.add(row)
        row.lines = "[]"
    elif not row.run_id:
        row.run_id = run.id
    row.chain_id = chain_id or row.chain_id
    row.mail_id = run.mail_id
    row.subject = ((mail.subject if mail else "") or run.summary or "")[:600]
    row.buyer_name = (buyer.get("name") or "")[:300]
    row.buyer_email = (buyer.get("email") or "")[:320]
    row.customer = (matches.get("customer") or "")[:200]
    # A later mail in the same chain must not ERASE what the approval produced: this ran for
    # every run in the chain, so a chain_reply with no Opportunity of its own blanked the
    # name the enquiry had created (2026-11-03). Only overwrite when there is something to say.
    try:
        made = json.loads(run.created_refs or "[]")
        opp = next((r["name"] for r in made if r.get("doctype") == "Opportunity"), "")
        if opp:
            row.opportunity = opp[:140]
        # the Customer this approval created IS the buyer, and the register should say which
        created_customer = next((r["name"] for r in made if r.get("doctype") == "Customer"), "")
        if created_customer:
            row.customer = created_customer[:200]
    except Exception:
        pass
    row.received_at = (mail.received_at if mail and mail.received_at else "") or _now()
    row.target_ship = (facts.get("ship_date") or "")[:40] or None
    due = _quote_due(facts)
    row.quote_due = (due.get("iso") or "")[:40] or None
    row.quote_due_raw = (due.get("raw") or "")[:60] or None
    row.quote_due_note = ("as written " + due["raw"] + " — " + due["convention"]
                          + (f"; it also reads {due['other']}" if due.get("ambiguous") else ""))[:200] \
        if due.get("raw") else None
    row.currency = (c.get("currency") or "")[:10]
    row.total_qty = _num(c.get("total_qty"))
    row.asks = json.dumps(facts.get("asks") or [])
    row.missing = json.dumps(facts.get("missing") or [])
    # A follow-up in the same conversation ADDS a style to the ask — it does not wipe the
    # ones already in the register (a buyer who sends "and also C9208" has asked for both).
    try:
        have = {l.get("style") for l in json.loads(row.lines or "[]")}
    except Exception:
        have = set()
    wanted = ([c for c in (facts.get("styles") or []) if c]
              or styles_for_mail("", text, text))
    if refresh or not have or (wanted and set(wanted) - have):
        read = lines(facts, text, pool=_pool() if refresh else None)
        merged = {l.get("style"): l for l in json.loads(row.lines or "[]")} if row.lines else {}
        for l in read:
            merged[l.get("style")] = l
        if merged:
            row.lines = json.dumps(list(merged.values()), default=str)
            row.history_at = _now()
    db.commit()
    db.refresh(row)
    return row


# A date written 11/09/2026 is two different days. Which one is not a guess — it is the
# buyer's own country, which is on the record: a US buyer writes month first, an EU/IN buyer
# writes day first. `intake._date_iso` defaults to day-first for everyone, which read this
# enquiry's quote-by date as 11 Sep when the buyer is in Los Angeles (2026-11-03).
_MONTH_FIRST = ("united states", "usa", "u.s", "canada", "philippines")


def read_date(token: str, country: str = "") -> dict:
    """One date token, both readings when it is ambiguous. Never silently picks."""
    t = (token or "").strip().strip(",.;")
    out = {"raw": t, "iso": "", "other": "", "convention": "", "ambiguous": False}
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", t)
    if m:
        out["iso"] = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        out["convention"] = "iso"
        return out
    m = re.match(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})$", t)
    if not m:
        from intake import _date_iso                  # "9 Nov 2026", "Nov 9, 2026"
        iso = _date_iso(t)
        out["iso"] = iso or ""
        out["convention"] = "text" if iso else ""
        return out
    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y = y + 2000 if y < 100 else y
    def _safe(mm, dd):
        try:
            return datetime(y, mm, dd).date().isoformat()
        except Exception:
            return ""
    if a > 12 >= b:
        out["iso"], out["convention"] = _safe(b, a), "d/m/y"
        return out
    if b > 12 >= a:
        out["iso"], out["convention"] = _safe(a, b), "m/d/y"
        return out
    us = (country or "").strip().lower().startswith(_MONTH_FIRST)
    first, second = ("m/d/y", "d/m/y") if us else ("d/m/y", "m/d/y")
    out["iso"] = _safe(a, b) if us else _safe(b, a)
    out["other"] = _safe(b, a) if us else _safe(a, b)
    out["convention"] = first
    out["ambiguous"] = True
    return out


def _quote_due(facts: dict) -> dict:
    """The date the buyer wants the quote by, as written and as read."""
    country = ((facts.get("buyer") or {}).get("country") or "")
    for ask in (facts.get("asks") or []):
        low = (ask or "").lower()
        if any(w in low for w in ("quote", "quotation", "offer", "price")):
            m = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}"
                          r"|\d{1,2}[\s-]+[A-Za-z]{3,9}\.?[\s,-]+\d{2,4}"
                          r"|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})\b", ask)
            if m:
                return read_date(m.group(1), country)
    return {"raw": "", "iso": "", "other": "", "convention": "", "ambiguous": False}


def sync(db, text_for=None, styles_for=None) -> dict:
    """Import every enquiry run into the register. Idempotent; no ERP write."""
    from models import IntakeRunModel, MailMessageModel
    made = 0
    runs = (db.query(IntakeRunModel)
            .filter(IntakeRunModel.route.in_(("enquiry", "chain_reply")))
            .order_by(IntakeRunModel.id).all())
    for run in runs:
        mail = db.query(MailMessageModel).filter(MailMessageModel.id == run.mail_id).first()
        facts = json.loads(run.facts or "{}")
        text = (text_for(run, mail) if callable(text_for) else "") or ""
        codes = (styles_for(mail, text) if callable(styles_for) else []) or \
            (facts.get("styles") or [])
        if not codes and not (facts.get("style") or {}).get("code"):
            continue
        if codes and not facts.get("styles"):
            facts["styles"] = codes
            run.facts = json.dumps(facts, default=str)
            db.commit()
        exists = db.query(BuyerInquiryModel).filter(BuyerInquiryModel.run_id == run.id).first()
        from_run(db, run, mail, text=text, refresh=not bool(exists))
        made += 1
    return {"ok": True, "synced": made}


def refresh_history(db, row: BuyerInquiryModel, text: str = "") -> BuyerInquiryModel:
    """Re-read the ERP for this enquiry's styles (the button, not the page load)."""
    from models import IntakeRunModel, MailMessageModel
    run = db.query(IntakeRunModel).filter(IntakeRunModel.id == row.run_id).first()
    mail = db.query(MailMessageModel).filter(MailMessageModel.id == row.mail_id).first()
    if run is None:
        return row
    return from_run(db, run, mail, text=text, refresh=True)


def summary(rows: list[BuyerInquiryModel]) -> dict:
    out = {"total": len(rows), "new": 0, "costing": 0, "quoted": 0, "won": 0, "lost": 0,
           "with_old_styles": 0, "quote_ready": 0, "styles": 0}
    for r in rows:
        st = (r.status or "new").lower()
        if st in out:
            out[st] += 1
        try:
            ls = json.loads(r.lines or "[]")
        except Exception:
            ls = []
        out["styles"] += len(ls)
        if any(l.get("verdict") in ("made", "costed") for l in ls):
            out["with_old_styles"] += 1
        if any(l.get("quote_ready") for l in ls):
            out["quote_ready"] += 1
    return out
