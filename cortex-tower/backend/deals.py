"""Deals: one buyer conversation, from the inquiry to the Sales Order, on the ERP's own documents.

    Inquiry (mail + BOM)  →  Opportunity + one Tech Pack per style            [register]
    Costing               →  Cost Sheet per style (the ERP's rules price it) [cost_open / cost_save / cost_submit]
    Quote                 →  Price Negotiation ("Our Offer") + the quote mail in the same thread  [quote_send]
    Buyer's answer        →  negotiation rounds: Buyer Counter / Our Counter / Agreed / Lost      [record_reply]
    Contract              →  Quotation (agreed prices) → Sales Contract (sizes, dates, terms)     [contract_*]
    Order                 →  Sales Order (draft, one row per colour/size)                         [make_order]

Every ERP write goes through ``pipeline.execute`` (role check, field guard, the Arinox business rules run in the tower,
journal, audit). The ``make_*`` steps call the same Arinox API scripts the ERP's buttons call, so a document made here
is the document the ERP desk would have made. Prices, costs and margins are read back from the ERP documents.

An inquiry never needs a price: the target price is optional and is never asked of the buyer.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Optional

import bom_reader
import config
import inbound
import pipeline
import write_gate
from models import KVModel, MailAttachmentModel, MailMessageModel
from models_deal import STAGE_LABEL, STAGES, DealModel

#: tests set this to a FakeBackend; production uses the configured ERP
BACKEND = None
SYS = {"name", "docstatus", "owner", "creation", "modified", "modified_by", "idx", "parent", "parentfield", "parenttype",
       "amended_from", "_user_tags", "_comments", "_assign", "_liked_by", "_seen", "arinox_name"}


class DealError(Exception):
    pass


def _be():
    if BACKEND is not None:
        return BACKEND
    from tsr import connection
    return connection.get_backend()


#: Fields the ERP keeps for itself. A client may never send them back: Frappe refuses the whole save with
#: *"<table> row N: docstatus changes only through Submit / Cancel"*. Two screens were broken by this one mistake
#: (the costing on 2026-11-07 and the buyer's answer the same afternoon), because both took the **stored** child rows and
#: sent them straight back with an edit applied. Stripping happens here so no screen can make that mistake again.
_READ_ONLY_KEYS = frozenset({"docstatus", "doctype", "parent", "parentfield", "parenttype", "owner", "creation",
                             "modified", "modified_by", "amended_from", "name"})


def _writable(value: Any, _depth: int = 0) -> Any:
    """The payload as the ERP will accept it: read-only bookkeeping removed at every level of the document."""
    if _depth > 6:
        return value
    if isinstance(value, list):
        return [_writable(v, _depth + 1) for v in value]
    if isinstance(value, dict):
        return {k: _writable(v, _depth + 1) for k, v in value.items() if k not in _READ_ONLY_KEYS}
    return value


def _ex(db, me: dict, req: dict, _setup_retry: bool = True) -> dict:
    """Every write goes through here: the payload is cleaned, and a missing ERP master record is repaired once.

    A rebuilt ERP whose **Apparel Settings** still point at the previous company's warehouses answers
    *"Could not find … Warehouse"* on the first real write. That is configuration, not a business refusal, so it is fixed
    (:func:`erp_setup`) and the same write is tried once more. Only once, and only for "could not find" - a genuine
    refusal is never retried.
    """
    if isinstance(req.get("data"), (dict, list)):
        req = {**req, "data": _writable(req["data"])}
    res = pipeline.execute(db, me, req, backend=_be())
    if _setup_retry and not res.get("ok") and "could not find" in _strip_html(str(res.get("error") or "")).lower():
        try:
            fixed = erp_setup(db, me)
        except Exception:
            fixed = {"changed": False}
        if fixed.get("changed"):
            res = _ex(db, me, req, _setup_retry=False)
    return res


def _must(res: dict, what: str) -> dict:
    if not res.get("ok"):
        if res.get("technical") and DEBUG:
            print("TECHNICAL:", res["technical"])
        raise DealError(f"{what}: {_strip_html(res.get('error') or 'the ERP refused it')}")
    return res


DEBUG = False


def clean(d: Any) -> Any:
    """A document from a ``make_*`` script, ready to insert: no name, docstatus, owner or row bookkeeping."""
    if isinstance(d, list):
        return [clean(x) for x in d]
    if not isinstance(d, dict):
        return d
    out = {}
    for k, v in d.items():
        if k in SYS or k.startswith("__"):
            continue
        if isinstance(v, (date, datetime)):
            v = v.isoformat()[:10] if isinstance(v, date) and not isinstance(v, datetime) else v.isoformat()
        out[k] = clean(v)
    return out


def _today() -> str:
    return date.today().isoformat()


def _kv_get(db, key):
    r = db.query(KVModel).filter(KVModel.key == key).first()
    return r.value if r else None


def _kv_set(db, key, value):
    r = db.query(KVModel).filter(KVModel.key == key).first()
    if r:
        r.value = value
    else:
        db.add(KVModel(key=key, value=value))
    db.commit()


# ───────────────────────── deal record helpers ─────────────────────────

def _get(db, deal_id) -> DealModel:
    d = db.query(DealModel).get(int(deal_id or 0))
    if not d:
        raise DealError("This deal no longer exists.")
    return d


def _save_styles(d: DealModel, styles: list) -> None:
    d.styles = json.dumps(styles, default=str)


def _set_refs(d: DealModel, **kw) -> None:
    r = d.refs_dict()
    r.update({k: v for k, v in kw.items() if v})
    d.refs = json.dumps(r)


def live_contract(db, d: DealModel, be=None) -> str:
    """The Sales Contract that is actually editable for this deal, not the one on file if that one is cancelled.

    A contract that is cancelled in the ERP cannot be edited or signed - Frappe refuses with *"Cannot edit cancelled
    document"*. And it is cancelled for a good reason: cancelling is how a submitted contract is corrected, and the ERP
    then makes an **amendment** (``<name>-1``) that is a fresh draft, carrying ``amended_from``. The deal's reference
    still points at the dead document, so every save and every signature would fail on a document nobody can edit.

    So the reference is re-pointed at the amendment the first time the deal is opened after it happened, and the move is
    written on the deal's timeline - never silently. With no amendment on file the reference is dropped, and the next
    contract is built from the quotation again (which is exactly what ``contract_prepare`` does).

    Returns the live contract name, or ``""`` when there is none.
    """
    name = d.refs_dict().get("sales_contract")
    if not name:
        return ""
    be = be or _be()
    try:
        doc = be.get_doc("Sales Contract", name)
    except Exception:
        return name                                  # cannot ask the ERP now: leave it alone and let the ERP answer
    if int(doc.get("docstatus") or 0) != 2 and not doc.get("amended_from"):
        return name
    if int(doc.get("docstatus") or 0) != 2:
        return name
    # cancelled: adopt the amendment the ERP made when it was cancelled
    try:
        rows = be.get_list("Sales Contract", [["amended_from", "=", name]], ["name", "docstatus", "modified"],
                           order_by="modified desc", limit=5) or []
    except Exception:
        rows = []
    live_rows = [r for r in rows if int(r.get("docstatus") or 0) != 2]
    if live_rows:
        new = live_rows[0]["name"]
        _set_refs(d, sales_contract=new)
        _event(d, "erp", f"Contract {name} was cancelled in the ERP; the deal now points at its amendment {new}.",
               doc=["Sales Contract", new])
        db.commit()
        return new
    r = d.refs_dict()
    r.pop("sales_contract", None)
    d.refs = json.dumps(r)
    _event(d, "erp", f"Contract {name} was cancelled in the ERP and no amendment exists; prepare the contract again "
                      f"from the quotation (the draft is still here).")
    db.commit()
    return ""


def _event(d: DealModel, kind: str, text: str, by: str = "", **extra) -> None:
    ev = json.loads(d.events or "[]")
    ev.append({"at": datetime.now().isoformat(timespec="seconds"), "kind": kind, "text": text, "by": by, **extra})
    d.events = json.dumps(ev[-200:], default=str)


def _style(styles: list, key: str) -> dict:
    s = next((x for x in styles if x.get("key") == key), None)
    if not s:
        raise DealError("That style is not on this deal.")
    return s


def new_style(**kw) -> dict:
    s = {"key": uuid.uuid4().hex[:8], "style_no": "", "style_name": "", "colour": "", "fabric": "", "qty": None, "sizes": [],
         "product_type": "", "bom": [], "bom_file": "", "warnings": [], "tech_pack": "", "style_item": "", "cost_sheet": "",
         "cost_status": "", "cost": {}, "offer_price": None, "buyer_price": None, "agreed_price": None, "target_price": None,
         "status": "open"}
    s.update({k: v for k, v in kw.items() if v not in (None, "", [])})
    return s


def live(styles: list) -> list:
    return [s for s in styles if s.get("status") != "dropped"]


# ───────────────────────── reading an inquiry mail ─────────────────────────

_PRODUCT_WORDS = [("Woven Top", r"shirt|blouse|poplin|button[- ]?down|camp collar|tunic|woven top"),
                  ("Knit Top", r"\btee\b|t-shirt|polo|knit|jersey|henley|tank|hoodie|sweatshirt"),
                  ("Bottom", r"pant|trouser|short|skirt|skort|jean|chino|jogger|legging"),
                  ("Dress", r"dress|jumpsuit|romper"), ("Outerwear", r"jacket|coat|parka|blazer|vest|gilet"),
                  ("Sleepwear", r"pajama|pyjama|sleep|lounge")]


def guess_product_type(text: str, available: list[str]) -> str:
    t = (text or "").lower()
    for name, pat in _PRODUCT_WORDS:
        if name in available and re.search(pat, t):
            return name
    return ""


def _load_bytes(att: MailAttachmentModel) -> bytes:
    """The stored bytes of an attachment. Paths were written three ways over time (relative to backend/, relative to
    the working directory, absolute on an earlier install); all resolve to ``backend/data/mail/<mail_id>/<file>``, and
    nothing outside ``backend/data`` is ever read."""
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    base = os.path.realpath(os.path.join(here, "data"))
    raw = att.path or ""
    cands = [raw if os.path.isabs(raw) else os.path.join(here, raw)]
    if raw:
        cands.append(os.path.join(base, "mail", str(att.mail_id), os.path.basename(raw)))
    for c in cands:
        p = os.path.realpath(c)
        if p.startswith(base + os.sep) and os.path.isfile(p):
            with open(p, "rb") as f:
                return f.read()
    return b""


def read_inquiry(subject: str, body: str, attachments: list[dict], product_types: list[str]) -> dict:
    """Mail + attachments → ``{styles, season, incoterm, destination, ex_factory, in_warehouse, sizes, company, notes}``.

    ``attachments``: ``[{filename, data}]``. Styles come from the mail's style table (or the codes it names) and from the
    header of each BOM sheet; a code that appears only inside a BOM line (a button's article number) is not a style.
    """
    fresh = inbound.strip_quoted(body or "") or (body or "")
    text = f"{subject}\n{fresh}"
    styles: dict[str, dict] = {}
    order: list[str] = []

    def add(code: str, **kw):
        code = (code or "").strip().upper()
        if not code:
            return
        if code not in styles:
            styles[code] = {"style_no": code}
            order.append(code)
        for k, v in kw.items():
            if v not in (None, "", []) and not styles[code].get(k):
                styles[code][k] = v

    for rec in bom_reader.styles_from_body(text):
        add(rec["style_no"], **{k: v for k, v in rec.items() if k != "style_no"})
    boms, notes, company, header_season = [], [], "", ""
    for a in attachments or []:
        name = a.get("filename") or ""
        if not name.lower().endswith((".xls", ".xlsx", ".xlsm", ".csv")):
            continue
        r = bom_reader.read_bom(name, a.get("data") or b"")
        if not r.get("rows"):
            if r.get("error"):
                notes.append(f"{name}: could not read a BOM table")
            continue
        h = r.get("header") or {}
        code = r.get("style") or (order[0] if len(order) == 1 else "")
        if not code:
            notes.append(f"{name}: BOM read, but the sheet does not say which style it is for")
            continue
        colour = h.get("color") or h.get("colour") or ""
        colour = colour.split(" - ", 1)[-1] if " - " in colour else colour
        add(code, style_name=h.get("description") or h.get("style_name"), colour=colour.title() if colour.isupper() else colour,
            fabric=h.get("fabric_content") or h.get("fabric") or h.get("content"))
        styles[code]["bom"] = r["rows"]
        styles[code]["bom_file"] = name
        styles[code]["warnings"] = r.get("warnings") or []
        header_season = header_season or h.get("season") or ""
        company = company or r.get("company") or ""
        boms.append(name)
    season = (header_season or bom_reader.season_from(text)).upper()
    terms = bom_reader.terms_from_body(text)
    dates = bom_reader.dates_from_body(text)
    out_dates, ambiguous = {}, []
    for k, raw in dates.items():
        iso, amb = bom_reader.iso_date(raw)
        if iso:
            out_dates[k] = iso
            if amb:
                ambiguous.append(f"{k.replace('_', '-')} read as {iso} from “{raw}” — check the day and month")
    sizes = bom_reader.sizes_from(text)
    out_styles = []
    for code in order:
        s = styles[code]
        desc = " ".join(str(s.get(k) or "") for k in ("style_name", "fabric")) + " " + subject
        out_styles.append(new_style(style_no=code, style_name=(s.get("style_name") or "")[:140], colour=s.get("colour") or "",
                                    fabric=s.get("fabric") or "", qty=s.get("qty"), sizes=sizes, bom=s.get("bom") or [],
                                    bom_file=s.get("bom_file") or "", warnings=s.get("warnings") or [],
                                    product_type=guess_product_type(desc, product_types)))
    target = None
    m = re.search(r"target (?:price|fob)\D{0,12}(\d+(?:\.\d{1,3})?)", fresh, re.I)
    if m:
        target = float(m.group(1))
        for s in out_styles:
            s["target_price"] = target
    return {"styles": out_styles, "season": season, "incoterm": terms.get("incoterm", ""), "destination": terms.get("destination", ""),
            "ex_factory": out_dates.get("ex_factory", ""), "in_warehouse": out_dates.get("in_warehouse", ""), "sizes": sizes,
            "company": company, "boms": boms, "notes": notes + ambiguous, "target_price": target}


# ───────────────────────── BOM: from a file, from the mail, from the ERP ─────────────────────────
# An inquiry does not always arrive with a readable BOM (a scan, a photo, an empty attachment, or a buyer who
# sends it later). These three doors put lines on a style anyway: upload a sheet, pick one of the mail's own
# attachments, or read the BOM the ERP already holds for the style's Item.

_MT_HINTS = (("contrast", "Contrast Fabric"), ("lining", "Lining"), ("self", "Fabric"), ("shell", "Fabric"),
             ("fabric", "Fabric"), ("cotton", "Fabric"), ("lyocell", "Fabric"), ("linen", "Fabric"), ("viscose", "Fabric"),
             ("polyester", "Fabric"), ("nylon", "Fabric"), ("denim", "Fabric"), ("knit", "Fabric"), ("woven", "Fabric"),
             ("thread", "Thread"), ("fusing", "Fusing"), ("interlin", "Fusing"), ("fusible", "Fusing"),
             ("label", "Label"), ("hangtag", "Label"), ("tag", "Label"), ("button", "Trim"), ("zip", "Trim"),
             ("zipper", "Trim"), ("trim", "Trim"), ("accessor", "Trim"), ("poly", "Packaging"), ("carton", "Packaging"),
             ("pack", "Packaging"))


def _mt(*parts) -> str:
    """Guess the material type from what the sheet or the ERP says. Only the nine types the UI offers."""
    text = " ".join(p for p in parts if p).lower()
    for key, mt in _MT_HINTS:
        if key in text:
            return mt
    return "Other"


def _bom_row(**kw) -> dict:
    row = {"item_code": "", "material_type": "Other", "description": "", "colour": "", "uom": "",
           "consumption": None, "rate": None, "remarks": "", "placement": "", "supplier": ""}
    row.update({k: v for k, v in kw.items() if v not in (None, "")})
    return row


def _bom_reason(filename: str, r: dict) -> str:
    if r.get("error") == "unreadable":
        return (f"{filename} could not be opened. Excel (.xlsx, .xls) and CSV/TSV are read; a PDF, a photo or an "
                "old .xlsb has to be uploaded as a sheet or typed in.")
    if r.get("error") == "no_table":
        return (f"No BOM table was found in {filename}: the sheet needs a header row with something like "
                "Description / Item / Qty / UOM. The buyer's own layout works best, but a plain two-column list does too.")
    return f"No usable line was found in {filename}."


def tp_measurements(spec: dict) -> tuple[list, list]:
    """A specification's measurement chart -> the rows the ERP's ``Tech Pack Measurement`` child accepts.

    That child has one row per point of measure and a column per size, but only XXS … XXL exist. Values for any other
    size (2, 4, 6 …) cannot be charted and are reported instead of being dropped silently.
    """
    rows, unmapped = [], []
    for m in (spec or {}).get("measurements") or []:
        row = {"pom_code": str(m.get("pom_code") or "")[:20],
               "point_of_measure": str(m.get("point_of_measure") or "")[:60],
               "section": str(m.get("section") or "")[:40]}
        tol = _ai_number(m.get("tolerance"))
        if tol is not None:
            row["tolerance"] = tol
        for size, val in (m.get("values") or {}).items():
            key = str(size).strip().upper()
            num = _ai_number(val)
            if num is None:
                continue
            if key in _TP_SIZE_COLS:
                row[key.lower()] = num
            else:
                unmapped.append(key)
        if row.get("point_of_measure") or any(k in row for k in ("xxs", "xs", "s", "m", "l", "xl", "xxl")):
            rows.append(row)
    return rows, sorted(set(unmapped))


def _fill_style_from_read(st: dict, got: dict) -> list[str]:
    """Put what the sheet says onto the style **where the style is still blank** - a person's edit is never replaced.

    The buyer's own sheet prints the description, the colour, the fabrication and the size range; asking a merchandiser
    to type them again is asking twice for something that already arrived.
    """
    filled: list[str] = []
    for key, label in (("style_name", "description"), ("colour", "colour"), ("fabric", "fabric"),
                       ("product_type", "product type")):
        v = str((got or {}).get(key) or "").strip()
        if v and not str(st.get(key) or "").strip():
            st[key] = v[:140]
            filled.append(label)
    sizes = [str(x).strip().upper() for x in ((got or {}).get("sizes") or []) if str(x).strip()]
    if sizes and not (st.get("sizes") or []):
        st["sizes"] = sizes
        filled.append("sizes")
    qty = (got or {}).get("qty")
    if qty and not st.get("qty"):
        st["qty"] = qty
        filled.append("quantity")
    return filled


def _put_bom(db, me: dict, d, style_key: str, rows: list, source: str, warnings: list | None = None, header: dict | None = None,
             style_detected: str = "", apply_to_erp: bool = True, got: dict | None = None) -> dict:
    """Write the lines onto the style, keep the old warnings that are not about the BOM, and record it on the timeline."""
    styles = json.loads(d.styles or "[]")
    st = _style(styles, style_key)
    st["bom"] = rows
    st["bom_file"] = source
    warn = list(warnings or [])
    if style_detected and not (st.get("style_no") or "").strip():
        st["style_no"] = style_detected.strip()[:60]      # the sheet names the style the buyer is asking about
    mine = (st.get("style_no") or "").strip().upper()
    theirs = (style_detected or "").strip().upper()
    if mine and theirs and theirs != mine:
        warn.insert(0, f"This sheet is for {style_detected}, but the style on the deal is {st.get('style_no')} - check that "
                       f"you picked the right BOM.")
    keep = [w for w in (st.get("warnings") or []) if not w.lower().startswith(("bom", "no quantity per garment", "this sheet is for"))]
    st["warnings"] = list(dict.fromkeys(keep + warn))
    header = header or {}
    if not st.get("colour") and header.get("color"):
        st["colour"] = str(header["color"])[:40]
    if not st.get("fabric") and header.get("fabric"):
        st["fabric"] = str(header["fabric"])[:80]
    filled = _fill_style_from_read(st, {**(header or {}), **(got or {})})
    _save_styles(d, styles)
    text = f"BOM read from {source}: {len(rows)} line(s)."
    if filled:
        text += f" The sheet also gave the style's {', '.join(dict.fromkeys(filled))}."
    _event(d, "bom", text, "")
    db.commit()
    erp = apply_bom_to_erp(db, me, d, style_key) if apply_to_erp else []
    return {"rows": len(rows), "source": source, "warnings": st["warnings"], "style_detected": style_detected or "",
            "filled": filled, "erp": erp}


def _tp_materials(be, rows: list) -> list:
    """BOM lines in the shape the Tech Pack's material child wants (the same mapping register() uses)."""
    mats = []
    for r in rows or []:
        if not (r.get("description") or r.get("item_code")):
            continue
        mats.append({k: v for k, v in {
            "material_type": r.get("material_type") or "Other",
            "description": (r.get("description") or r.get("item_code"))[:140],
            "consumption": r.get("consumption") or 0,
            "uom": _uom(be, r.get("uom")),
            "colour": (r.get("colour") or "")[:60],
            "buyer_item_code": r.get("item_code") or None,
            "placement": r.get("placement") or None,
            "remarks": r.get("remarks") or None,
            "composition": None}.items() if v not in (None, "")})
    return mats


def apply_bom_to_erp(db, me: dict, d, style_key: str) -> list:
    """Put the style's BOM lines where the ERP keeps them: the Tech Pack's materials, and the draft Cost Sheet.

    The ERP copies the Tech Pack's materials when it makes a Cost Sheet (``arinox_tech_pack_make_cost_sheet``), so a
    draft sheet made before the BOM arrived would stay empty for ever. Such a sheet is therefore replaced by a fresh
    one built from the updated Tech Pack. A submitted sheet is never touched - the answer says so instead.
    """
    styles = json.loads(d.styles or "[]")
    s = _style(styles, style_key)
    if not s.get("tech_pack"):
        return []
    be = _be()
    notes: list = []
    mats = _tp_materials(be, s.get("bom") or [])
    if not mats:
        return ["There are no material lines to send to the ERP yet."]
    tp = be.get_doc("Tech Pack", s["tech_pack"])
    if int(tp.get("docstatus") or 0) == 1:
        raise DealError(f"Tech Pack {s['tech_pack']} is submitted, so its materials cannot be changed here. "
                        f"Amend it in the ERP.")
    res = _ex(db, me, {"op": "save", "doctype": "Tech Pack", "name": s["tech_pack"], "data": {"materials": mats},
                       "modified": tp.get("modified")})
    if not res.get("ok"):
        raise DealError("The Tech Pack was not updated: " + _strip_html(res.get("error") or "the ERP refused it"))
    notes.append(f"Tech Pack {s['tech_pack']} carries {len(mats)} material line(s) now.")
    if not s.get("cost_sheet"):
        return notes
    cs = be.get_doc("Cost Sheet", s["cost_sheet"])
    if int(cs.get("docstatus") or 0) == 1:
        notes.append(f"Cost Sheet {s['cost_sheet']} is submitted, so it was left alone - amend it in the ERP to price "
                     f"these materials.")
        return notes
    # the sheet takes the lines as a save (deleting a document is a bigger write than this needs)
    lines = [{k: v for k, v in {
        "material_type": m.get("material_type"), "description": m.get("description"), "consumption": m.get("consumption"),
        "uom": m.get("uom"), "rate": m.get("rate"), "remarks": m.get("remarks")}.items() if v not in (None, "")}
        for m in mats]
    res = _ex(db, me, {"op": "save", "doctype": "Cost Sheet", "name": s["cost_sheet"], "data": {"materials": lines},
                       "modified": cs.get("modified")})
    if not res.get("ok"):
        notes.append(f"Cost Sheet {s['cost_sheet']} was not changed: {_strip_html(res.get('error') or 'the ERP refused it')}.")
        return notes
    doc = res.get("doc") or {}
    s["cost"] = _cost_summary(doc) or s.get("cost")
    notes.append(f"Cost Sheet {s['cost_sheet']} now carries {len(doc.get('materials') or lines)} material line(s).")
    msgs = [m.get("message") for m in (res.get("messages") or []) if isinstance(m, dict) and m.get("message")]
    notes += [m[:180] for m in msgs[:2]]
    _save_styles(d, styles)
    db.commit()
    return notes


def thread_documents(db, d) -> list[dict]:
    """Every attachment on the deal's conversation, newest mail first, with its bytes when they are still on disk."""
    mails = [d.mail_id] if d.mail_id else []
    if d.thread_key:
        try:
            mails += [row.id for row in db.query(MailMessageModel).filter(MailMessageModel.thread_key == d.thread_key).all()]
        except Exception:
            pass
    mails = [m for m in dict.fromkeys(mails) if m]
    if not mails:
        return []
    out = []
    rows = (db.query(MailAttachmentModel).filter(MailAttachmentModel.mail_id.in_(mails))
            .order_by(MailAttachmentModel.mail_id.desc(), MailAttachmentModel.id.asc()).all())
    for a in rows:
        out.append({"attachment_id": a.id, "mail_id": a.mail_id, "filename": a.filename or "", "mime": a.mime or "",
                    "size": a.size or 0, "ok": bool(a.ok), "error": a.error or "", "data": _load_bytes(a)})
    return out


def read_documents_again(db, me: dict, deal_id: int) -> dict:
    """Read everything this conversation carries, again — the whole point of a mail with a Tech Pack AND a BOM.

    Used when a document arrives late, when a mail was stored before a reader existed, or when someone simply wants the
    buyer's files re-read. Nothing is invented: a document that cannot be read is reported with the reason (and its row
    stays on the conversation).
    """
    d = _get(db, deal_id)
    docs = thread_documents(db, d)
    if not docs:
        raise DealError("This conversation has no attachments. Upload the sheet on the style, or ask the buyer to resend.")
    if not config.llm_available():
        raise DealError("Reading documents needs the signed-in KOGO session (it carries the model's key).")
    readable = [{"filename": x["filename"], "data": x["data"]} for x in docs if x.get("data")]
    if not readable:
        raise DealError("None of this conversation's attachments could be opened. "
                        + " ".join(f"{x['filename']}: {x['error'] or 'no bytes'}" for x in docs)[:400])
    styles = d.styles_list()
    info = read_with_model(db, {"styles": styles, "boms": [], "notes": []}, readable, timeout=240)
    new_styles = info.get("styles") or styles
    _save_styles(d, new_styles)
    lines = sum(len(s.get("bom") or []) for s in new_styles)
    specs = [s.get("style_no") or "style" for s in new_styles if s.get("spec")]
    reads = info.get("document_reads") or []
    skipped = [f"{x['filename']}: {x['error']}" for x in docs if not x.get("data")]
    failed = [f"{r['file']}: {r['error']}" for r in reads if r.get("error")]
    text = f"Read the conversation's documents: {len(readable)} file(s) sent to the model; {lines} BOM line(s)"
    if specs:
        text += f"; tech pack read for {', '.join(specs)}"
    if failed:
        text += ". Could not read — " + "; ".join(failed)
    if skipped:
        text += ". Not read — " + "; ".join(skipped)
    _event(d, "bom", text + ".", me.get("email", ""))
    db.commit()
    return {"documents": [x["filename"] for x in readable], "skipped": skipped, "failed": failed, "reads": reads,
            "bom_lines": lines, "spec_styles": specs, "deal": d}


def bom_from_bytes(db, me: dict, deal_id: int, style_key: str, filename: str, data: bytes) -> tuple:
    """A sheet the person uploads (xlsx / xls / csv) → the style's BOM lines."""
    d = _get(db, deal_id)
    if not data:
        raise DealError("That file came through empty. Try again, or type the lines in.")
    r = bom_reader.read_bom(filename, data)
    if not r.get("ok"):
        raise DealError(_bom_reason(filename, r))
    rep = _put_bom(db, me, d, style_key, r["rows"], filename, r.get("warnings") or [], r.get("header") or {}, r.get("style") or "")
    return d, rep


def bom_attachments(db, d: DealModel) -> list[dict]:
    """The deal's mail attachments that could be a BOM (spreadsheets), newest first."""
    mails = [d.mail_id] if d.mail_id else []
    if d.thread_key:
        try:
            mails += [row.id for row in db.query(MailMessageModel).filter(MailMessageModel.thread_key == d.thread_key).all()]
        except Exception:
            pass
    mails = [m for m in dict.fromkeys(mails) if m]
    if not mails:
        return []
    out = []
    for a in db.query(MailAttachmentModel).filter(MailAttachmentModel.mail_id.in_(mails)).all():
        name = a.filename or ""
        if name.lower().endswith((".xlsx", ".xls", ".xlsm", ".csv", ".tsv")):
            out.append({"id": a.id, "filename": name, "mail_id": a.mail_id, "size": a.size or 0})
    return out


def bom_from_mail(db, me: dict, deal_id: int, style_key: str, attachment_id: int) -> tuple:
    """One of the mail's own attachments → the style's BOM lines."""
    d = _get(db, deal_id)
    att = db.query(MailAttachmentModel).get(int(attachment_id or 0))
    if not att:
        raise DealError("That attachment is not on this deal any more.")
    data = _load_bytes(att)
    if not data:
        raise DealError(f"{att.filename} is no longer on disk. Upload the sheet again and it will be read.")
    r = bom_reader.read_bom(att.filename or "", data)
    if not r.get("ok"):
        raise DealError(_bom_reason(att.filename or "the attachment", r))
    rep = _put_bom(db, me, d, style_key, r["rows"], att.filename or "the mail", r.get("warnings") or [], r.get("header") or {},
                   r.get("style") or "")
    return d, rep


# ───────────────────────── BOM read by the model ─────────────────────────
# Every buyer prints their BOM differently, so a fixed column map will always meet a sheet it cannot read.
# The model is given the sheet as plain text (no interpretation) and asked for the rows; everything it
# returns is validated here before it reaches the deal or the ERP.

_AI_TYPES = ("Fabric", "Lining", "Contrast Fabric", "Trim", "Label", "Packaging", "Thread", "Fusing", "Other")


def bom_ai_prompt(style_no: str, filename: str, grid: str, product_options=()) -> str:
    """The one prompt: plain-text sheet in, JSON out."""
    types_list = ", ".join(product_options) or "any garment type"
    return f"""Read a buyer's Bill of Materials and return it as JSON. Reply with the JSON only - no prose, no code fence.

The sheet came as the buyer sent it, so the layout is whatever their system prints. Columns are separated by " | ".

The sheet is the buyer's own document: it says what the style IS as well as what it is made of. Read both. A person
should not have to type in anything the sheet already prints.

STYLE FIELDS
- "style_no" the style code the sheet is for. "colour" the colour code or name. "style_name" the style's own
  description (for example "1 POCKET CROPPED BUTTON DOWN"), not a heading and not the buyer's name.
- "fabric" the main/self fabric as the sheet prints it, content first (for example "100% LYOCELL (F85 LIKE QUALITY)").
  Take it from a fabric line or from a header row; leave it empty rather than invent one.
- "sizes" every size the sheet lists for the style, in the order the sheet lists them, as separate short tokens
  ("XXS", "XS", "S", "M", "L", "XL", "XXL", "2", "4", "6", "OS"). The sizes may be on one row, in a size
  column, or in a heading such as "Available Sizes" - read whichever the sheet uses. Never a range of numbers.
- "qty" the order/buyer quantity only if the sheet states one. Do not guess it, do not add up the garment parts.
- "product_type" what the garment IS, judged from its description and materials (a button-down is a top, a skort is a
  bottom). Copy it EXACTLY as written from this list - it is the only set the ERP has - or use an empty string when the
  sheet does not let you tell: {types_list}.

MATERIAL LINES
- One row per MATERIAL the garment is made of. Skip title blocks, column headings, subtotal/total rows, notes and
  anything that is not a material line.
- "consumption" is the quantity needed for ONE garment, as a plain number (1.47, not "1.47 YD"). If the sheet only
  gives a total for the whole order, divide it by the order quantity; if the sheet does not say, use null.
- "item_code" is the buyer's own item/reference code for that line, exactly as printed. Never invent one.
- "material_type" must be one of: {', '.join(_AI_TYPES)}. Use the sheet's own category when it maps to one of these.
- "colour" is the colour code or name printed on that line; "uom" is the unit printed (Yard, Mtr, Nos, Set, Kgs, Roll).
- Copy descriptions as printed, shortened to 120 characters. Do not translate, do not correct spelling, do not add
  materials that are not on the sheet. If a value is not on the sheet, use an empty string.

The style on this deal is "{style_no}". The file is "{filename}".

Reply with exactly this shape:
{{"style_no": "", "style_name": "", "colour": "", "fabric": "", "sizes": [], "qty": null, "product_type": "", "rows": [{{"item_code": "", "material_type": "Fabric", "description": "", "colour": "", "uom": "Yard", "consumption": 0.0, "remarks": ""}}]}}

SHEET:
{grid}
"""


# ───────────────────────── the model reads the WHOLE mail ─────────────────────────
# A real inquiry mail carries two documents and they are two different things: the **Tech Pack** (the specification -
# measurement chart, construction, wash & care, packing) and the **BOM** (the requirement list - which materials and how
# much per garment). One mail, two documents, two homes in the ERP:
#   BOM lines        -> the Tech Pack's "Buyer BOM" tab  -> copied onto the Cost Sheet for pricing
#   Tech Pack spec   -> the Tech Pack's own spec fields  (measurements, construction, wash & care, packing, sizes)
# One prompt asks the model which it is holding and reads whichever parts are there.

_TP_TEXT_FIELDS = ("construction_notes", "wash_care", "packing_notes")
_TP_SIZE_COLS = ("XXS", "XS", "S", "M", "L", "XL", "XXL")     # the columns the ERP's measurement chart has


def attachment_text(filename: str, data: bytes) -> str:
    """The attachment as text the model can read. A spreadsheet keeps its columns (grid), anything else is read by
    ``docread`` (PDF text layer, docx, csv, plain text)."""
    name = (filename or "").lower()
    if name.endswith((".xls", ".xlsx", ".xlsm", ".csv", ".tsv")):
        return bom_reader.grid_text(filename, data)
    try:
        import docread
        r = docread.read_attachment(filename, "", data or b"")
        return r.get("text") or ""
    except Exception:
        return ""


def documents_ai_prompt(style_no: str, filename: str, text: str, product_options=()) -> str:
    """One prompt for one attachment: say what kind of document it is, and read whichever parts it holds."""
    types_list = ", ".join(product_options) or "any garment type"
    return f"""Read one document that a buyer sent with an inquiry, and return its content as JSON. Reply with the JSON
only - no prose, no code fence.

A buyer usually sends TWO documents: a TECH PACK (the specification) and a BOM (the requirement list). They are
different things, and this one might be either, or both.

- kind "tech_pack": a specification. It holds a measurement chart, construction / cutting details, wash & care, packing
  instructions, size range, colourways. It may carry no material quantities at all.
- kind "bom": a list of materials with a quantity per garment (consumption), unit, colour, buyer item code.
- kind "spec_and_bom": one file with both.
- kind "other": neither (an invoice, a photo, a packing list).

STYLE FIELDS (fill what the document says, leave the rest empty)
- "style_no", "style_name", "colour", "fabric", "sizes" (each size as its own short token, in the document's order),
  "qty" (only if an order quantity is printed), "size_range" (as printed, e.g. "XXS-XXL" or "2-12").
- "product_type" must be copied exactly from this list or left empty: {types_list}.

BOM ROWS (only when the document holds material lines) - one row per material: "item_code" (the buyer's own code, never
invented), "material_type" (one of {', '.join(_AI_TYPES)}), "description" as printed (max 120 chars), "colour", "uom",
"consumption" (quantity for ONE garment, a plain number; null when the document does not say), "remarks".

MEASUREMENTS (only when the document holds a measurement chart) - one row per point of measure:
"pom_code", "point_of_measure" (e.g. "Chest", "Waist", "Shoulder"), "section" (e.g. "Body", "Sleeve"), "tolerance" (a
number if printed), and "values" as an object of size -> number, e.g. {{"S": 20.5, "M": 21.5}}. Use the size names the
document prints. Never invent a value that is not printed; leave a size out instead.

NOTES - copy the document's own words, shortened: "construction_notes" (construction, cutting, stitching, seams),
"wash_care", "packing_notes". Keep them as plain text with line breaks. If the document does not have them, use "".

The style on this deal is "{style_no}". The file is "{filename}".

Reply with exactly this shape:
{{"kind": "", "style_no": "", "style_name": "", "colour": "", "fabric": "", "sizes": [], "size_range": "", "qty": null, "product_type": "",
 "rows": [], "measurements": [{{"pom_code": "", "point_of_measure": "", "section": "", "tolerance": null, "values": {{}}}}],
 "construction_notes": "", "wash_care": "", "packing_notes": ""}}

DOCUMENT:
{text}
"""


def _text_block(v, limit: int = 4000) -> str:
    """A note block from the model: plain text, no tags, no runaway length."""
    t = re.sub(r"<[^>]+>", " ", str(v or ""))
    t = re.sub(r"[ \t]{2,}", " ", t).strip()
    return t[:limit]


def spec_from_ai(reply: str, style_no: str = "", product_options=()) -> dict:
    """Validate the specification half of the model's answer."""
    data = _json_block(reply)
    if not isinstance(data, dict):
        raise DealError("The model did not answer with JSON. Try again, or read the file another way.")
    styles = data.get("styles")
    if isinstance(styles, list) and styles and isinstance(styles[0], dict):
        want = (style_no or "").strip().upper()
        pick = next((x for x in styles if str(x.get("style_no") or "").strip().upper() == want), styles[0]) if want else styles[0]
        data = {**data, **pick}
    measurements, dropped = [], []
    for m in data.get("measurements") or []:
        if not isinstance(m, dict):
            continue
        point = str(m.get("point_of_measure") or m.get("point") or m.get("description") or "").strip()[:60]
        values = m.get("values") or m.get("sizes") or {}
        if not isinstance(values, dict):
            values = {}
        row = {"pom_code": str(m.get("pom_code") or m.get("code") or "").strip()[:20], "point_of_measure": point,
               "section": str(m.get("section") or "").strip()[:40], "values": {}}
        tol = _ai_number(m.get("tolerance"))
        if tol is not None:
            row["tolerance"] = tol
        for size, val in values.items():
            num = _ai_number(val)
            if num is None:
                continue
            row["values"][str(size).strip()[:8]] = num
        if row["values"] or point:
            measurements.append(row)
            for size in row["values"]:
                if size.upper() not in _TP_SIZE_COLS:
                    dropped.append(size.upper())
    kind = str(data.get("kind") or "").strip().lower()
    return {
        "kind": kind,
        "style_no": str(data.get("style_no") or "").strip()[:60],
        "style_name": str(data.get("style_name") or data.get("description") or "").strip()[:140],
        "colour": str(data.get("colour") or data.get("color") or "").strip()[:60],
        "fabric": str(data.get("fabric") or "").strip()[:80],
        "sizes": _sizes_from_ai(data.get("sizes") or data.get("size")),
        "size_range": str(data.get("size_range") or "").strip()[:40],
        "qty": _ai_number(data.get("qty") if data.get("qty") is not None else data.get("quantity")),
        "product_type": (_product_type_from_ai(data.get("product_type") or data.get("garment_type"), product_options)
                         or guess_product_type(f"{data.get('style_name') or ''} {data.get('construction_notes') or ''}",
                                               list(product_options))),
        "measurements": measurements,
        "construction_notes": _text_block(data.get("construction_notes") or data.get("construction") or data.get("cutting_notes")),
        "wash_care": _text_block(data.get("wash_care") or data.get("washing") or data.get("care_instructions")),
        "packing_notes": _text_block(data.get("packing_notes") or data.get("packing")),
        "unmapped_sizes": sorted(set(dropped)),
    }


def _json_junk_strip(t: str) -> str:
    """Remove text that cannot be JSON while *outside* a string literal.

    The model's stream sometimes injects a progress note ("Hold tight…", "On it…") in the middle of the answer, which
    turns a good object into an unparseable one. Inside string literals nothing is touched.
    """
    out: list[str] = []
    i, n, in_str, esc = 0, len(t), False, False
    keep = set('{}[],:0123456789.-+eE \t\n\r')
    while i < n:
        c = t[i]
        if in_str:
            if esc:                                   # an escape the model already wrote stays exactly as it is
                out.append(c)
                esc = False
            elif c == "\\":
                out.append(c)
                esc = True
            elif c == '"':
                out.append(c)
                in_str = False
            elif ord(c) < 0x20:
                # a raw newline/tab inside a string is invalid JSON, and multi-line notes are exactly where models
                # put them ("construction_notes"). Escape it instead of losing the whole answer.
                out.append({0x0A: "\\n", 0x0D: "\\r", 0x09: "\\t"}.get(ord(c), "\\u%04x" % ord(c)))
            else:
                out.append(c)
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
        elif c in keep:
            out.append(c)
        else:
            for lit in ("true", "false", "null"):      # these need all their letters kept, not just the first
                if t.startswith(lit, i):
                    out.append(lit)
                    i += len(lit) - 1
                    break
        i += 1
    return "".join(out)


def _json_block(reply: str):
    """The model's answer -> the first JSON object or array in it. Tolerates fences, an intro and <think> traces."""
    t = (reply or "").strip()
    t = re.sub(r"^.*?</think>", "", t, flags=re.S | re.I)
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t.strip(), flags=re.I)
    if "{" in t or "[" in t:
        t = _json_junk_strip(t)
    starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
    if not starts:
        return None
    start = min(starts)
    for end in range(len(t), start, -1):
        try:
            return json.loads(t[start:end])
        except Exception:
            continue
    return None


def _ai_number(v):
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d+(?:\.\d+)?", str(v or ""))
    return float(m.group(0)) if m else None


_SIZE_WORDS = ("XXS", "XS", "S", "M", "L", "XL", "XXL", "2XL", "3XL", "4XL", "5XL", "OS")


def _sizes_from_ai(v) -> list[str]:
    """The model may hand sizes as a list, as "S, M, L", as "S-M-L" or as a ratio object. Take the real tokens only."""
    if isinstance(v, dict):
        v = list(v.keys())
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    out: list[str] = []
    for item in v:
        for t in re.split(r"[^A-Za-z0-9]+", str(item or "")):
            t = t.upper().strip()
            if not t:
                continue
            if t in ("FREE", "ONESIZE", "ALL", "ONE"):
                t = "OS"
            if t in _SIZE_WORDS or re.fullmatch(r"\d{1,3}(?:\.5)?", t):
                if t not in out:
                    out.append(t)
    return out[:16]


def _product_type_from_ai(v, options=()) -> str:
    """The garment type the model judged - only accepted when it is one the app can actually store."""
    want = str(v or "").strip()
    if not want:
        return ""
    for o in options or ():
        if want.lower() == str(o).strip().lower():
            return str(o)
    return ""


def bom_rows_from_ai(reply: str, style_no: str = "", product_options=()) -> dict:
    """Validate what the model returned. Anything unusable is dropped and reported, never guessed."""
    data = _json_block(reply)
    if data is None:
        raise DealError("The model did not answer with JSON. Try again, or use the sheet reader.")
    if isinstance(data, list):
        data = {"rows": data}
    if not isinstance(data, dict):
        raise DealError("The model's answer was not the shape asked for.")
    styles = data.get("styles")
    if isinstance(styles, list) and styles and isinstance(styles[0], dict):
        want = (style_no or "").strip().upper()
        pick = next((x for x in styles if str(x.get("style_no") or "").strip().upper() == want), styles[0]) if want else styles[0]
        data = {**data, **pick}
    raw = data.get("rows") or data.get("materials") or []
    if not isinstance(raw, list):
        raw = []
    rows, dropped = [], 0
    for r in raw:
        if not isinstance(r, dict):
            dropped += 1
            continue
        desc = str(r.get("description") or "").strip()[:140]
        code = str(r.get("item_code") or r.get("code") or "").strip()[:60]
        if not desc and not code:
            dropped += 1
            continue
        mt = str(r.get("material_type") or r.get("category") or "").strip()
        match = next((t for t in _AI_TYPES if t.lower() == mt.lower()), None) or _mt(mt, desc, code)
        rows.append({"item_code": code, "material_type": match, "description": desc,
                     "colour": str(r.get("colour") or r.get("color") or "").strip()[:60],
                     "uom": str(r.get("uom") or r.get("unit") or "").strip()[:12],
                     "consumption": _ai_number(r.get("consumption") if r.get("consumption") is not None else r.get("qty")),
                     "rate": _ai_number(r.get("rate")), "remarks": str(r.get("remarks") or "").strip()[:200],
                     "placement": str(r.get("placement") or "").strip()[:80], "supplier": ""})
    if not rows:
        raise DealError("The model found no material lines on this sheet.")
    warn = []
    missing = [x.get("description") or x.get("item_code") for x in rows if x.get("consumption") is None]
    if missing:
        warn.append(f"No quantity per garment for {', '.join(str(m) for m in missing[:4])}")
    if dropped:
        warn.append(f"{dropped} row(s) on the sheet were not material lines")
    return {"rows": rows, "style_no": str(data.get("style_no") or "").strip()[:60],
            "style_name": str(data.get("style_name") or data.get("description") or "").strip()[:140],
            "colour": str(data.get("colour") or data.get("color") or "").strip()[:60],
            "fabric": str(data.get("fabric") or "").strip()[:80],
            "sizes": _sizes_from_ai(data.get("sizes") or data.get("size_range") or data.get("size")),
            "qty": _ai_number(data.get("qty") if data.get("qty") is not None else data.get("quantity")),
            "product_type": (_product_type_from_ai(data.get("product_type") or data.get("garment_type"), product_options)
                             or guess_product_type(f"{data.get('style_name') or ''} "
                                                   f"{' '.join(str(r.get('description') or '') for r in raw)}", list(product_options))),
            "warnings": warn}


def bom_from_ai(db, me: dict, deal_id: int, style_key: str, filename: str, data: bytes) -> tuple:
    """Send the sheet to the KOGO model and put the rows it returns on the style."""
    d = _get(db, deal_id)
    grid = bom_reader.grid_text(filename, data)
    if not grid:
        raise DealError(_bom_reason(filename, {"error": "unreadable"}))
    if not config.llm_available() or not getattr(config, "USER_JWT_TOKEN", ""):
        raise DealError("Reading with the model needs the signed-in KOGO session (it carries the model's key). The sheet "
                        "reader and the paste box work without it.")
    import ai_nextsteps
    st = _style(json.loads(d.styles or "[]"), style_key)
    raw = ai_nextsteps._llm(db, bom_ai_prompt(st.get("style_no") or "", filename, grid), timeout=180)
    if not raw:
        raise DealError("The model did not answer in time. Try again, or use the sheet reader.")
    got = bom_rows_from_ai(raw, st.get("style_no") or "", product_types())
    rep = _put_bom(db, me, d, style_key, got["rows"], f"{filename} (read by the model)", got["warnings"],
                   {"color": got.get("colour"), "fabric": got.get("fabric")}, got.get("style_no") or "", got=got)
    return d, rep


def bom_from_rows(db, me: dict, deal_id: int, style_key: str, rows, source: str = "pasted lines") -> tuple:
    """Rows typed in, or the model's JSON pasted from any chat window -> the style's BOM lines."""
    d = _get(db, deal_id)
    payload = rows if isinstance(rows, str) else json.dumps({"rows": rows or []})
    got = bom_rows_from_ai(payload, "")
    rep = _put_bom(db, me, d, style_key, got["rows"], source, got["warnings"], {}, got=got)
    return d, rep


# ───────────────────────── the model reads the inquiry itself ─────────────────────────
# A buyer's mail and its sheet carry the style's own facts (description, colour, fabrication, size range). The
# sheet reader gets the materials; the model is asked for the whole picture so nothing that already arrived has to
# be typed in again. Every value is validated by ``bom_rows_from_ai`` and only fills a BLANK field.

def read_with_model(db, info: dict, attachments: list[dict], timeout: int = 180) -> dict:
    """Ask the model to read **every** document the mail carries, and put each part where it belongs.

    A buyer's mail usually holds two different documents - the Tech Pack (specification: measurement chart,
    construction, wash & care, packing) and the BOM (materials and how much per garment). Each attachment is read on its
    own and the answer decides what it was: material lines go to the style's BOM, a specification goes to ``style["spec"]``
    (which ``register`` writes onto the Tech Pack's own spec fields). A document that is neither is left alone.
    """
    if not attachments or not config.llm_available():
        return info
    styles = info.get("styles") or []
    opts = product_types()
    checks = [a for a in attachments
              if not (a.get("filename") or "").lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".eml", ".zip"))]
    read_any = False
    outcomes: list[dict] = []
    for a in checks[:4]:
        name = a.get("filename") or ""
        outcome = {"file": name, "kind": "", "rows": 0, "measurements": 0, "error": ""}
        outcomes.append(outcome)
        text = attachment_text(name, a.get("data") or b"")
        if not text.strip():
            outcome["error"] = "nothing readable in the file (a scan, or a format no reader here opens)"
            continue
        want = (styles[0].get("style_no") if len(styles) == 1 else "")
        spec, raw = None, None
        last = ""
        for attempt in range(2):                    # a malformed answer is worth one clean retry
            try:
                import ai_nextsteps
                prompt = documents_ai_prompt(want, name, text, opts)
                if attempt:
                    prompt += "\nYour previous answer could not be read as JSON. Reply with the JSON object only.\n"
                raw = ai_nextsteps._llm(db, prompt, timeout=timeout)
                if not raw:
                    last = "the model did not answer in time"
                    continue
                spec = spec_from_ai(raw, want, opts)
                break
            except Exception as e:                  # noqa: BLE001
                last = f"{type(e).__name__}: {str(e)[:120]}"
                spec = None
        if spec is None:
            outcome["error"] = last or "the answer could not be read"
            continue
        outcome["kind"] = spec.get("kind") or ""
        rows: list = []
        warn: list = []
        if spec["kind"] in ("bom", "spec_and_bom", "tech_pack", "other", ""):
            try:
                got = bom_rows_from_ai(raw, want, opts)
                rows, warn = got["rows"], got.get("warnings") or []
            except Exception:
                rows, warn = [], []
        code = (spec.get("style_no") or want or "").strip().upper()
        if not code and not rows and not spec.get("measurements"):
            continue
        target = next((s for s in styles if (s.get("style_no") or "").upper() == code), None) if code else None
        if target is None:
            target = styles[0] if len(styles) == 1 else new_style(style_no=code)
            if target not in styles:
                styles.append(target)
            if code and not (target.get("style_no") or "").strip():
                target["style_no"] = code
        if rows:
            target["bom"] = rows
            target["bom_file"] = f"{name} (read by the model)"
            target["warnings"] = list(dict.fromkeys((target.get("warnings") or []) + warn))
            info["boms"] = list(dict.fromkeys((info.get("boms") or []) + [name]))
            read_any = True
        if spec.get("measurements") or spec.get("construction_notes") or spec.get("wash_care") or spec.get("packing_notes"):
            spec["source"] = name
            target["spec"] = spec
            info["spec_files"] = list(dict.fromkeys((info.get("spec_files") or []) + [name]))
            if spec.get("unmapped_sizes"):
                target["warnings"] = list(dict.fromkeys((target.get("warnings") or []) +
                    [f"{name}: sizes {', '.join(spec['unmapped_sizes'])} are not columns in the ERP's measurement chart "
                     f"(XXS-XXL), so their values could not be charted"]))
            read_any = True
        _fill_style_from_read(target, spec)
        if spec.get("size_range") and not (target.get("sizes") or []):
            target["sizes"] = _sizes_from_ai(spec["size_range"])
        outcome["rows"] = len(rows)
        outcome["measurements"] = len(spec.get("measurements") or [])
    info["document_reads"] = outcomes
    if read_any:
        info["styles"] = styles
        info["read_by_model"] = True
    return info


def bom_from_erp(db, me: dict, deal_id: int, style_key: str) -> tuple:
    """The BOM the ERP already holds for the style's Item (the default active one) → the style's BOM lines."""
    d = _get(db, deal_id)
    styles = json.loads(d.styles or "[]")
    st = _style(styles, style_key)
    if st.get("tech_pack"):
        raise DealError("This style is in the ERP already. Its materials live in the Cost Sheet now (step 2).")
    be = _be()
    code = (st.get("style_item") or st.get("style_no") or "").strip()
    item = st.get("style_item") or ""
    if not item and code:
        for flt in ([['item_code', '=', code]], [['name', '=', code]], [['item_name', 'like', f'%{code}%']]):
            item = _first(be, "Item", flt)
            if item:
                break
    if not item:
        raise DealError(f"The ERP has no Item for {code or 'this style'} yet. Send the inquiry to the ERP first (that makes "
                        f"the style Item), or upload the buyer's BOM.")
    try:
        boms = be.get_list("BOM", [["item", "=", item], ["is_active", "=", 1], ["docstatus", "=", 1]],
                           ["name", "quantity", "is_default"], limit=20) or []
    except Exception as e:
        raise DealError(f"The ERP could not be asked for {item}'s BOM: {_strip_html(str(e))[:140]}")
    if not boms:
        raise DealError(f"The ERP has no active submitted BOM for Item {item}. Make the BOM in the ERP, or upload the "
                        f"buyer's sheet.")
    boms.sort(key=lambda b: (0 if int(b.get("is_default") or 0) else 1, str(b.get("name"))))
    name = boms[0]["name"]
    doc = be.get_doc("BOM", name) or {}
    per = float(doc.get("quantity") or 1) or 1.0
    rows = []
    for it in doc.get("items") or []:
        qty = float(it.get("qty") or 0)
        if not (it.get("item_code") or it.get("description")):
            continue
        rows.append(_bom_row(item_code=it.get("item_code") or "",
                             material_type=_mt(it.get("item_group") or "", it.get("item_name") or "", it.get("item_code") or ""),
                             description=(it.get("description") or it.get("item_name") or "")[:140],
                             uom=it.get("uom") or "", consumption=round(qty / per, 4), rate=it.get("rate")))
    if not rows:
        raise DealError(f"The ERP BOM {name} has no lines.")
    # the Buyer-side type comes off the Item master when the description alone does not say it
    unknown = [r["item_code"] for r in rows if r.get("material_type") == "Other" and r.get("item_code")]
    if unknown:
        try:
            groups = {i["name"]: i.get("item_group") or ""
                      for i in be.get_list("Item", [["name", "in", list(dict.fromkeys(unknown))]], ["name", "item_group"], limit=50) or []}
            for r in rows:
                if r.get("material_type") == "Other" and groups.get(r.get("item_code")):
                    r["material_type"] = _mt(groups[r["item_code"]])
        except Exception:
            pass
    rep = _put_bom(db, me, d, style_key, rows, f"ERP BOM {name}", [], {})
    return d, rep


# ───────────────────────── the buyer's own costing sheet ─────────────────────────
# A merchandiser already costs a style in a spreadsheet ("APPAREL COSTING DETAILED", "INTERNAL COSTING" …): usage per
# piece, wastage, rate, CMT, overheads, profit, FOB. That sheet is the *source* of the numbers; the ERP's Cost Sheet is
# where they have to live, because the ERP's own rules turn them into the price. So the sheet is read (by the model,
# because every factory prints it differently), recorded on the deal, and then **applied** to the Cost Sheet with one
# button - after which the ordinary editor takes over for hand changes.

def costing_ai_prompt(style_no: str, filename: str, text: str, cost_heads: list[str]) -> str:
    heads = ", ".join(cost_heads) or "the ERP's own cost heads"
    return f"""Read a garment COSTING sheet (a cost breakdown made in Excel by a merchandiser) and return it as JSON. Reply
with the JSON only - no prose, no code fence.

The sheet is somebody's own layout. Columns may be titled USAGE / CONSUMPTION / QTY, WASTAGE %, RATE / PRICE / COST,
UNIT, COST/PC. Rows fall into three groups, and they must not be mixed up:

1. "materials" - things the garment is made of, each with a usage per piece, a unit and a rate:
   {", ".join('"' + t + '"' for t in _AI_TYPES)} are the only material types.
2. "charges" - processing and expense lines that are NOT materials: making/CMT, washing, printing, embroidery, testing,
   rejection, financing, banking, freight, overheads, buying agent commission, depreciation, profit. Each carries a rate
   or a percentage and often an "apply 1/0" flag. A cost that is charged ON the fabric - "fabric export cost per metre",
   "fabric import cost per metre", duty, handling - is a charge, not a material, and belongs to the matching cost head
   when the list below has one. Map every one of them to a cost head from this list, copying the name
   EXACTLY: {heads}. A line that fits none of them gets an empty cost_head.
3. "totals" - the sheet's own sums (raw material total, processing total, other expenses, FOB cost before profit, profit
   amount, FOB price per piece, order value). Use the numbers printed; do not recompute them.

Rules
- "usage" is per ONE piece, as printed (0.6, 1.26, 200). "wastage_pct" as printed: the sheet may show 0.05 for 5% or 5
  for 5% - give the fraction (0.05) and say in "wastage_note" if you had to convert it.
- "rate" is the money per unit as printed, in the sheet's own currency. "cost_per_pc" is the printed cost per piece.
- "wastage_reason" is why that wastage applies, when the sheet says (a note column, "cutting loss", "shrinkage" ...).
  Leave it empty when the sheet does not say - do not invent a reason.
- "currency" and "pcs_per_carton", "vnd_per_usd", "fob_port", "order_qty", "style_no", "style_name", "buyer", "season",
  "costing_date", "version" come from the header block when the sheet has one.
- If a processing line has an apply/flag column of 0, still return it, with "apply": false - the app decides what to do
  with it.
- Never invent a line, a rate or a total. A value that is not printed stays null.

The style on this deal is "{style_no}". The file is "{filename}".

Reply with exactly this shape:
{{"kind": "costing", "currency": "", "style_no": "", "style_name": "", "buyer": "", "season": "", "order_qty": null,
 "pcs_per_carton": null, "fob_port": "", "vnd_per_usd": null, "costing_date": "", "version": "",
 "materials": [{{"label": "", "material_type": "Fabric", "usage": 0.0, "uom": "MTR", "wastage_pct": 0.0, "wastage_reason": "", "rate": 0.0, "cost_per_pc": 0.0}}],
 "charges": [{{"label": "", "cost_head": "", "calc_type": "", "value": 0.0, "apply": true, "cost_per_pc": 0.0}}],
 "totals": {{"raw_material": null, "processing": null, "other_expenses": null, "fob_before_profit": null,
            "profit": null, "fob_usd": null, "fob_local": null, "order_value": null, "profit_pct": null}},
 "wastage_note": "", "notes": ""}}

COSTING SHEET:
{text}
"""


def costing_from_ai(reply: str, cost_heads: list[str]) -> dict:
    """The model's costing answer, validated against the ERP's own cost heads and material types."""
    data = _json_block(reply)
    if not isinstance(data, dict):
        raise DealError("The model did not answer with JSON. Try again, or give the sheet another format.")
    heads = {str(h).strip().lower(): str(h) for h in cost_heads or []}
    types = {t.lower(): t for t in _AI_TYPES}
    materials, charges = [], []
    for m in data.get("materials") or []:
        if not isinstance(m, dict):
            continue
        label = str(m.get("label") or m.get("description") or m.get("name") or "").strip()[:140]
        if not label:
            continue
        mt = str(m.get("material_type") or "").strip()
        wastage = _ai_number(m.get("wastage_pct"))
        if wastage is not None and wastage > 1:          # the sheet printed 5, meaning 5%
            wastage = round(wastage / 100.0, 6)
        materials.append({"label": label, "material_type": types.get(mt.lower()) or _mt(mt, label),
                          "usage": _ai_number(m.get("usage")), "uom": str(m.get("uom") or "").strip()[:12],
                          "wastage_pct": wastage, "wastage_reason": str(m.get("wastage_reason") or "").strip()[:140],
                          "rate": _ai_number(m.get("rate")),
                          "cost_per_pc": _ai_number(m.get("cost_per_pc"))})
    for c in data.get("charges") or []:
        if not isinstance(c, dict):
            continue
        label = str(c.get("label") or c.get("description") or c.get("name") or "").strip()[:140]
        head = str(c.get("cost_head") or c.get("head") or "").strip()
        head = next((h for k, h in heads.items() if k == head.lower()), "")
        if not label and not head:
            continue
        apply_flag = c.get("apply")
        charges.append({"label": label or head, "cost_head": head, "calc_type": str(c.get("calc_type") or "")[:40],
                        "value": _ai_number(c.get("value") if c.get("value") is not None else c.get("rate")),
                        "cost_per_pc": _ai_number(c.get("cost_per_pc")),
                        "apply": True if apply_flag is None else bool(apply_flag)})
    totals = {k: _ai_number((data.get("totals") or {}).get(k)) for k in
              ("raw_material", "processing", "other_expenses", "fob_before_profit", "profit", "fob_usd", "fob_local",
               "order_value", "profit_pct")}
    return {"kind": "costing", "currency": str(data.get("currency") or "").strip()[:8],
            "style_no": str(data.get("style_no") or "").strip()[:60],
            "style_name": str(data.get("style_name") or "").strip()[:140],
            "buyer": str(data.get("buyer") or "").strip()[:80], "season": str(data.get("season") or "").strip()[:40],
            "order_qty": _ai_number(data.get("order_qty")), "pcs_per_carton": _ai_number(data.get("pcs_per_carton")),
            "fob_port": str(data.get("fob_port") or "").strip()[:40], "vnd_per_usd": _ai_number(data.get("vnd_per_usd")),
            "costing_date": str(data.get("costing_date") or "").strip()[:20],
            "version": str(data.get("version") or "").strip()[:20],
            "materials": materials, "charges": charges, "totals": totals,
            "wastage_note": str(data.get("wastage_note") or "").strip()[:200],
            "notes": str(data.get("notes") or "").strip()[:400],
            "unmapped_charges": [c["label"] for c in charges if not c["cost_head"]]}


def _norm_desc(text: str) -> set[str]:
    """Words of a material description, for matching a costing-sheet line to a Cost Sheet line."""
    t = re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower())
    stop = {"the", "and", "for", "per", "with", "pc", "pcs", "mtr", "yd", "nos", "cm", "of", "a", "to"}
    return {w for w in t.split() if len(w) > 1 and w not in stop}


def _match_material(label: str, rows: list, used=()) -> int:
    """Which Cost Sheet material line a costing-sheet line is (``-1`` when it is a new one).

    Overlap is measured against the **union** of both word sets, and a line already claimed by another sheet line is
    skipped. With a "min" denominator the shared word "main" made "MAIN LABEL" match "MAIN FABRIC 100% COTTON" and quietly
    overwrite the fabric's usage and rate (2026-11-07) - one word in common is not the same material.
    """
    want = _norm_desc(label)
    if not want:
        return -1
    best, score = -1, 0.0
    for i, r in enumerate(rows):
        if i in used:
            continue
        have = _norm_desc(f"{r.get('description') or ''} {r.get('material_type') or ''}")
        if not have:
            continue
        overlap = len(want & have) / max(1, len(want | have))
        if overlap > score:
            best, score = i, overlap
    return best if score >= 0.5 else -1


def cost_document_read(db, me: dict, deal_id: int, style_key: str, filename: str, data: bytes) -> tuple:
    """Read a costing sheet (uploaded, or one of the mail's attachments) and record it on the style."""
    d = _get(db, deal_id)
    styles = d.styles_list()
    s = _style(styles, style_key)
    text = attachment_text(filename, data or b"")
    if not text.strip():
        raise DealError(f"{filename} could not be read: no text came out of it (a scan, or a format nothing here opens).")
    if not config.llm_available():
        raise DealError("Reading a costing sheet needs the signed-in KOGO session (it carries the model's key).")
    import ai_nextsteps
    heads = [h.get("name") for h in (_be().get_list("Cost Head", None, ["name"], limit=60) or []) if h.get("name")]
    raw = ai_nextsteps._llm(db, costing_ai_prompt(s.get("style_no") or "", filename, text, heads), timeout=240)
    if not raw:
        raise DealError("The model did not answer in time. Try again, or upload the sheet again.")
    doc = costing_from_ai(raw, heads)
    doc["source"] = filename
    if not (doc["materials"] or doc["charges"]):
        raise DealError(f"{filename} did not read as a costing sheet: no material or charge lines were found in it.")
    s["cost_doc"] = doc
    _save_styles(d, styles)
    _event(d, "costing", f"Costing sheet {filename} read: {len(doc['materials'])} material line(s), "
                         f"{len(doc['charges'])} charge line(s)"
                         + (f", FOB {doc['totals']['fob_usd']}" if doc["totals"].get("fob_usd") else "") + ".",
           me.get("email", ""))
    db.commit()
    return d, doc


def cost_sheet_transfer(db, me: dict, deal_id: int, style_key: str, replace: bool = False) -> dict:
    """Transfer the app's own costing sheet into the ERP Cost Sheet.

    This is the step the module exists for: the sheet is worked out **here** (usage, wastage, rate, per-metre charges,
    percentages, profit, FOB — see ``costing_sheet.compute``) and one click moves the prices into the ERP, which stays a
    draft for its own rules and a person's last look.
    """
    import costing_sheet as cs
    d = _get(db, deal_id)
    styles = d.styles_list()
    s = _style(styles, style_key)
    sheet, lines, totals = cs.open_sheet(db, d, s)
    # the workbook keeps the fabric export/import cost inside the materials block, but in the ERP they are cost heads
    # priced "Per Metre of Fabric" - so they travel as charges, and only real materials become material lines
    doc = {"source": f"the costing sheet{' (imported from ' + sheet.imported_from + ')' if sheet.imported_from else ''}",
           "materials": [{"label": ln.label, "material_type": ln.material_type, "usage": ln.usage, "uom": ln.uom,
                          "wastage_pct": ln.wastage_pct, "wastage_reason": ln.wastage_reason, "rate": ln.rate}
                         for ln in lines if ln.kind == "material" and ln.apply and ln.rule != "fabric_metres"],
           "charges": [{"label": ln.label, "cost_head": ln.cost_head, "apply": bool(ln.apply),
                        "value": (ln.share if ln.kind == "expense" else ln.rate)}
                       for ln in lines
                       if (ln.kind in ("processing", "expense") or ln.rule == "fabric_metres") and ln.cost_head],
           "totals": {"fob_usd": totals.get("fob_usd")}}
    out = _apply_costing_doc(db, me, deal_id, style_key, doc, replace)
    sheet.transferred_at = datetime.utcnow()
    sheet.totals = json.dumps(totals)
    db.commit()
    _event(d, "costing", f"Costing sheet transferred to the ERP: {out['applied']['materials_updated']} material line(s) "
                         f"updated, {out['applied']['materials_added']} added, {out['applied']['charges_set']} cost head(s) "
                         f"set, quoted {totals.get('fob_usd')}.", me.get("email", ""))
    db.commit()
    out["deal"] = d
    out["sheet"] = sheet.to_dict()
    out["totals"] = totals
    return out


def apply_prices_to_bom(db, me: dict, deal_id: int, style_key: str) -> dict:
    """One click: the price kept for each item goes onto the BOM item it belongs to.

    The sheet carries *what item* and *what price*; the prices are kept in the app's own price book (``item_price``) and
    this walks the style's Cost Sheet — whose material rows are the BOM items that came in with the inquiry — and puts each
    item's price on it. Nothing else is touched: no consumption, no charges, no quoted price. The merchandiser can then
    change whatever they like in the ERP. The Cost Sheet stays a draft.
    """
    import costing_sheet as cs
    d = _get(db, deal_id)
    s = _style(d.styles_list(), style_key)
    cur = cost_open(db, me, deal_id, style_key)["cost_sheet"]      # makes the Cost Sheet if the style has none
    if int(cur.get("docstatus") or 0) == 1:
        raise DealError("This costing is submitted in the ERP. Amend it there to change a price.")
    rows = [dict(m) for m in cur.get("materials") or []]
    updated = priced = 0
    missing: list[str] = []
    for m in rows:
        found = cs.lookup_price(db, m.get("item"), m.get("description"))
        if not found or found.get("rate") is None:
            missing.append(str(m.get("description") or m.get("item") or "")[:60])
            continue
        priced += 1
        if _ai_number(m.get("rate")) != _ai_number(found["rate"]):
            m["rate"] = found["rate"]
            updated += 1
    out: dict = {"items": len(rows), "priced": priced, "updated": updated, "missing": missing, "written": False}
    if updated:
        res = cost_save(db, me, deal_id, style_key, rows, None, quoted_price=None)
        out["cost_sheet"] = res.get("cost_sheet")
        out["messages"] = res.get("messages") or []
        out["written"] = True
        s = _style(d.styles_list(), style_key)
        _event(d, "costing", f"{s['style_no']}: {updated} BOM item(s) priced from the app's price book "
                             f"({priced} of {len(rows)} items have a price)."
                             + (f" No price yet for: {', '.join(missing[:6])}." if missing else ""), me.get("email", ""))
        db.commit()
    else:
        out["cost_sheet"] = cost_view(_be().get_doc("Cost Sheet", s["cost_sheet"]))
    return out


def cost_autofill(db, me: dict, deal_id: int, style_key: str) -> dict:
    """Fill the ERP Cost Sheet from the style's costing sheet, so nobody types the same costing twice.

    The ERP refuses to submit a costing that leaves a mandatory cost head at 0 without N/A ticked. Every number it wants
    is already on the app's own sheet (the workbook: a rate on every line, CMT 5.000, rejection 3 %, the lines the
    workbook turns off at APPLY 0), so this walks the Cost Sheet the ERP made from the Buyer BOM and puts them there:

    * a **material** line with no price takes the price of the sheet line that carries the same item, then the price the
      app has kept for that item (``item_price``); a wastage that comes with it brings its reason, because the ERP
      refuses a wastage % without one;
    * a **cost head** line at 0 takes the sheet's figure for that same head (a processing rate per piece, a percentage
      for the expense heads) and the sheet's APPLY column becomes the N/A tick — a head the sheet turns off is N/A, a
      head the sheet prices is priced;
    * **nothing else is touched**: no consumption, no submit. The Cost Sheet stays a draft, and the merchandiser changes
      whatever they like in the ERP afterwards. A **quote somebody chose is left alone**; while a quote was never chosen
      (0, or the computed price itself) it follows the new computed price, so filling a line never leaves a fresh
      costing flagged "below the margin floor".

    Nothing here runs on its own — the Cost sheet tab of the Costing page has one button for it. Only blanks are filled
    and an N/A a person ticked is never cleared, so pressing it again is harmless (idempotent).
    Returns ``{ok, materials, heads, priced, na, missing, unmatched, quoted, written, cost_sheet, messages}``.
    """
    import costing_sheet as cs
    d = _get(db, deal_id)
    s = _style(d.styles_list(), style_key)
    cur = cost_open(db, me, deal_id, style_key)["cost_sheet"]      # makes the Cost Sheet if the style has none
    out: dict = {"materials": 0, "heads": 0, "priced": 0, "na": 0, "missing": [], "unmatched": [], "written": False}
    if int(cur.get("docstatus") or 0) == 1:
        out["cost_sheet"] = cur
        out["note"] = "This costing is submitted in the ERP, so it is left exactly as it is."
        return out

    sheet, lines, _totals = cs.open_sheet(db, d, s)
    mat_lines = [ln for ln in lines if ln.kind == "material"]
    by_item = {str(ln.item_code).lower(): ln for ln in mat_lines if ln.item_code}
    by_head = {str(ln.cost_head or "").lower(): ln for ln in lines if ln.cost_head}
    used: set[int] = set()

    rows = [dict(m) for m in cur.get("materials") or []]
    for m in rows:
        out["materials"] += 1
        if _ai_number(m.get("rate")):
            continue
        ln = by_item.get(str(m.get("item") or "").lower())
        if ln is None:
            idx = _match_material(m.get("description") or m.get("item") or "",
                                  [{"description": f"{x.label} {x.item_desc or ''}"} for x in mat_lines], used)
            ln = mat_lines[idx] if idx >= 0 else None
            if ln is not None:
                used.add(idx)
        rate = _ai_number(ln.rate) if ln is not None else None
        if not rate:
            found = cs.lookup_price(db, m.get("item"), m.get("description"))
            rate = _ai_number((found or {}).get("rate"))
        if not rate:
            out["missing"].append(str(m.get("description") or m.get("item") or "")[:60])
            continue
        m["rate"] = rate
        out["priced"] += 1
        if ln is not None and _ai_number(ln.wastage_pct) and not _ai_number(m.get("wastage_pct")):
            m["wastage_pct"] = _ai_number(ln.wastage_pct)
            if not (m.get("wastage_reason") or "").strip():
                m["wastage_reason"] = (ln.wastage_reason or "Wastage from the standard costing sheet")[:140]

    charges = [dict(c) for c in cur.get("charges") or []]
    for c in charges:
        out["heads"] += 1
        if c.get("not_applicable"):          # a person ticked N/A in the ERP - that stands
            continue
        if _ai_number(c.get("rate")):
            continue
        ln = by_head.get(str(c.get("cost_head") or "").lower())
        if ln is None:
            # a head the workload sheet does not cost at all (this site has Depreciation on its Cost Head list): who
            # decides is a person, so it is reported rather than silently ticked N/A or filled with a guess
            out["unmatched"].append(str(c.get("cost_head") or ""))
            continue
        value = _ai_number(ln.share) if ln.kind == "expense" else _ai_number(ln.rate)
        if not ln.apply or not value:
            # the sheet turns this head off (APPLY 0) or prices it at 0 % - the ERP needs the N/A tick, not a 0
            c["not_applicable"] = 1
            out["na"] += 1
            continue
        c["rate"] = value
        c["not_applicable"] = 0
        out["priced"] += 1

    if out["priced"] or out["na"]:
        # the ERP keeps a costing's quote equal to its computed price until somebody chooses one. Honour that: if the
        # quote was never chosen (0, or the computed price itself), it follows the new computed price instead of going
        # stale - otherwise filling a line leaves "below the margin floor" on a costing nobody has priced yet.
        prev_computed = _ai_number(cur["totals"].get("computed_price")) or 0
        prev_quoted = _ai_number(cur["totals"].get("quoted_price")) or 0
        quoted = None
        if not prev_quoted or abs(prev_quoted - prev_computed) <= 0.02:
            seen = cost_save(db, me, deal_id, style_key, rows, charges, quoted_price=None, preview=True)
            fresh = _ai_number(((seen.get("cost_sheet") or {}).get("totals") or {}).get("computed_price"))
            if fresh:
                quoted = round(fresh, 2)
        res = cost_save(db, me, deal_id, style_key, rows, charges, quoted_price=quoted)
        out["cost_sheet"] = res.get("cost_sheet")
        out["quoted"] = quoted
        out["messages"] = res.get("messages") or []
        out["written"] = True
        s = _style(d.styles_list(), style_key)
        _event(d, "costing", f"{s['style_no']}: the cost sheet was filled from the standard costing - "
                             f"{out['priced']} line(s) priced, {out['na']} cost head(s) marked N/A"
                             + (f", {len(out['missing'])} material line(s) still without a price." if out["missing"] else "."),
               me.get("email", ""))
        db.commit()
    else:
        out["cost_sheet"] = cost_view(_be().get_doc("Cost Sheet", s["cost_sheet"]))
    return out


def cost_document_apply(db, me: dict, deal_id: int, style_key: str, replace: bool = False) -> dict:
    """Put the recorded costing sheet's numbers into the ERP Cost Sheet - then a person can edit them there.

    Materials are matched by description (a line the Cost Sheet already has is *updated*, a new one is added); charges
    are matched by the ERP's own cost head; the sheet's FOB price, when it prints one, becomes the quoted price. Nothing
    is submitted: the Cost Sheet stays a draft for the merchandiser to check and change.
    """
    d = _get(db, deal_id)
    s = _style(d.styles_list(), style_key)
    doc = s.get("cost_doc") or {}
    if not doc:
        raise DealError("Read a costing sheet first: upload it, or pick one of the mail's attachments.")
    return _apply_costing_doc(db, me, deal_id, style_key, doc, replace)


def _apply_costing_doc(db, me: dict, deal_id: int, style_key: str, doc: dict, replace: bool = False) -> dict:
    """The one merge: a costing document's numbers -> the ERP Cost Sheet (draft)."""
    d = _get(db, deal_id)
    styles = d.styles_list()
    s = _style(styles, style_key)
    cur = cost_open(db, me, deal_id, style_key)["cost_sheet"]     # makes the Cost Sheet if the style has none yet
    src = cur.get("materials") or []
    rows = [{k: m.get(k) for k in _MAT_FIELDS if m.get(k) not in (None, "")} for m in src]
    updated = added = 0
    used: set[int] = set()
    for line in doc.get("materials") or []:
        picked = -1 if replace else _match_material(line["label"], rows, used)
        if picked >= 0:
            used.add(picked)
        target = rows[picked] if picked >= 0 else None
        if target is None:
            target = {"material_type": line.get("material_type") or "Other", "description": line["label"][:140],
                      "consumption": line.get("usage"), "uom": line.get("uom") or "", "is_selected": 1}
            rows.append(target)
            added += 1
        else:
            updated += 1
        if line.get("usage") is not None:
            target["consumption"] = line["usage"]
        if line.get("rate") is not None:
            target["rate"] = line["rate"]
        if line.get("wastage_pct") is not None:
            target["wastage_pct"] = line["wastage_pct"]
            # the ERP refuses a wastage % without a reason; the sheet's own words, or where the figure came from
            if line["wastage_pct"] and not (target.get("wastage_reason") or "").strip():
                target["wastage_reason"] = (line.get("wastage_reason") or f"From {doc.get('source') or 'the costing sheet'}"
                                            )[:140]
        if line.get("uom") and not target.get("uom"):
            target["uom"] = line["uom"]
    charges = [{k: c.get(k) for k in _CHG_FIELDS if c.get(k) not in (None, "")} for c in (cur.get("charges") or [])]
    by_head = {str(c.get("cost_head") or "").lower(): c for c in charges}
    set_heads, unmapped = 0, []
    for line in doc.get("charges") or []:
        head = (line.get("cost_head") or "").strip()
        if not head:
            unmapped.append(line.get("label") or "")
            continue
        row = by_head.get(head.lower())
        if row is None:
            continue
        if line.get("value") is not None:
            row["rate"] = line["value"]
        row["not_applicable"] = 0 if line.get("apply", True) else 1
        if not line.get("apply", True):
            row["rate"] = 0
        set_heads += 1
    quoted = doc.get("totals", {}).get("fob_usd")
    out = cost_save(db, me, deal_id, style_key, rows, charges, quoted_price=quoted)
    doc["applied_at"] = _today()
    doc["applied"] = {"materials_updated": updated, "materials_added": added, "charges_set": set_heads,
                      "quoted_price": quoted, "unmapped": unmapped}
    s["cost_doc"] = doc
    _save_styles(d, styles)
    _event(d, "costing", f"Costing sheet applied: {updated} material line(s) updated, {added} added, "
                         f"{set_heads} cost head(s) set" + (f", quoted {quoted}" if quoted else "")
                         + (f". Not mapped to a cost head: {', '.join(unmapped)}" if unmapped else "") + ".",
           me.get("email", ""))
    db.commit()
    out["applied"] = doc["applied"]
    out["deal"] = d
    return out


# ───────────────────────── customers ─────────────────────────

_FREE_MAIL = ("gmail.", "yahoo.", "hotmail.", "outlook.", "live.", "icloud.", "aol.", "proton", "qq.com", "163.com", "rediffmail.")


def list_customers(q: str = "", limit: int = 50) -> list[dict]:
    flt = [["customer_name", "like", f"%{q}%"]] if q else None
    try:
        rows = _be().get_list("Customer", flt, ["name", "customer_name", "default_currency", "territory", "customer_group"],
                              order_by="modified desc", limit=limit)
    except Exception:
        rows = []
    return rows


def match_customer(db, email: str, name: str = "", text: str = "") -> dict:
    """Who is writing? A sender we linked before, an ERP Contact with this e-mail, or a customer whose name or domain the
    mail carries. Returns ``{customer, customer_name, how}``, or ``{suggestion}`` with a name the person can confirm."""
    email = (email or "").strip().lower()
    if email:
        hit = _kv_get(db, f"email_customer:{email}")
        if hit:
            return {"customer": hit, "customer_name": hit, "how": "linked before"}
        try:
            rows = _be().get_list("Contact", [["email_id", "=", email]], ["name"], limit=3)
            for r in rows:
                doc = _be().get_doc("Contact", r["name"])
                for link in doc.get("links") or []:
                    if link.get("link_doctype") == "Customer" and link.get("link_name"):
                        return {"customer": link["link_name"], "customer_name": link["link_name"], "how": "ERP contact"}
        except Exception:
            pass
    customers = list_customers(limit=2000)
    domain = email.split("@")[-1] if "@" in email else ""
    hay = f"{name} {text}".lower()
    for c in customers:
        cn = (c.get("customer_name") or c.get("name") or "")
        core = re.sub(r"\b(llc|inc|ltd|limited|co|corp|group|company|apparel|the)\b|[^a-z0-9 ]", " ", cn.lower()).split()
        core = [w for w in core if len(w) > 2]
        if core and all(w in hay for w in core[:2]):
            return {"customer": c["name"], "customer_name": cn, "how": "name in the mail"}
        if domain and not domain.startswith(_FREE_MAIL) and core and core[0] in domain:
            return {"customer": c["name"], "customer_name": cn, "how": "mail domain"}
    return {"customer": "", "suggestion": {"customer_name": "", "email": email}}


def create_customer(db, me: dict, customer_name: str, email: str = "", currency: str = "", country: str = "",
                    customer_group: str = "", territory: str = "", contact_name: str = "") -> dict:
    name = (customer_name or "").strip()
    if len(name) < 2:
        raise DealError("Type the customer's company name.")
    be = _be()
    if be.exists("Customer", {"customer_name": name}):
        return {"customer": be.exists("Customer", {"customer_name": name}), "existing": True}
    group = customer_group or _first(be, "Customer Group", [["is_group", "=", 0]]) or "Commercial"
    terr = territory or _first(be, "Territory", [["is_group", "=", 0]]) or "Rest Of The World"
    data = {"customer_name": name, "customer_type": "Company", "customer_group": group, "territory": terr}
    if currency:
        data["default_currency"] = currency
    if country:
        data["country"] = country
    res = _must(_ex(db, me, {"op": "insert", "doctype": "Customer", "data": data, "idem_key": f"cust-{name.lower()}"[:80]}),
                "Customer not created")
    cust = (res.get("doc") or {}).get("name") or name
    if email:
        contact = {"first_name": (contact_name or email.split("@")[0])[:60], "email_ids": [{"email_id": email, "is_primary": 1}],
                   "links": [{"link_doctype": "Customer", "link_name": cust}]}
        c = _ex(db, me, {"op": "insert", "doctype": "Contact", "data": contact, "idem_key": f"contact-{email}"[:80]})
        _kv_set(db, f"email_customer:{email.lower()}", cust)
        return {"customer": cust, "contact": (c.get("doc") or {}).get("name"), "contact_error": None if c.get("ok") else c.get("error")}
    return {"customer": cust}


def _first(be, doctype, filters) -> str:
    try:
        rows = be.get_list(doctype, filters, ["name"], limit=1)
        return rows[0]["name"] if rows else ""
    except Exception:
        return ""


def _company(be) -> str:
    try:
        g = be.get_single("Global Defaults") or {}
        if g.get("default_company"):
            return g["default_company"]
    except Exception:
        pass
    return _first(be, "Company", None) or config.DEFAULT_COMPANY


def product_types() -> list[str]:
    try:
        return [r["name"] for r in _be().get_list("Product Type", None, ["name"], limit=100)]
    except Exception:
        return []


# ───────────────────────── create / edit ─────────────────────────

def from_thread(db, me: dict, key: str) -> DealModel:
    existing = db.query(DealModel).filter(DealModel.thread_key == key).first()
    if existing:
        return existing
    import mailbox
    t = mailbox.get_thread(db, key, mark_read=False)
    if not t.get("ok"):
        raise DealError(t.get("error") or "Conversation not found.")
    mail = db.query(MailMessageModel).get(int(t.get("inquiry_mail_id") or 0))
    if not mail:
        raise DealError("This conversation has no mail from the buyer.")
    atts = [{"filename": a.filename, "data": _load_bytes(a)} for a in db.query(MailAttachmentModel).filter(MailAttachmentModel.mail_id == mail.id)]
    if not atts:      # mail stored before attachments were kept: the forwarded copy in the same thread may have them
        for m in db.query(MailMessageModel).filter(MailMessageModel.thread_key == key).all():
            atts += [{"filename": a.filename, "data": _load_bytes(a)} for a in db.query(MailAttachmentModel).filter(MailAttachmentModel.mail_id == m.id)]
    info = read_inquiry(mail.subject or "", mail.body_text or "", atts, product_types())
    info = read_with_model(db, info, atts)          # the sheet says what the style is, not only what it is made of
    who = match_customer(db, mail.from_addr or "", mail.from_name or "", f"{mail.subject}\n{info.get('company')}\n{(mail.body_text or '')[:3000]}")
    styles = info["styles"]
    title = mailbox.clean_subject(mail.subject or "")[:200]
    d = DealModel(title=title, stage="inquiry", thread_key=key, mail_id=mail.id, customer=who.get("customer") or None,
                  customer_name=who.get("customer_name") or None, contact_email=mail.from_addr, contact_name=mail.from_name,
                  currency=config.DEFAULT_CURRENCY if config.DEFAULT_CURRENCY in ("USD", "EUR", "GBP") else "USD",
                  incoterm=info["incoterm"] or None, destination=info["destination"] or None, season=info["season"] or None,
                  ex_factory=info["ex_factory"] or None, in_warehouse=info["in_warehouse"] or None,
                  product_type=(styles[0]["product_type"] if styles else None), owner=me.get("email"),
                  notes="\n".join(info["notes"]) or None)
    _save_styles(d, styles)
    _event(d, "created", f"Deal started from the buyer's mail: {len(styles)} style(s), {len(info['boms'])} BOM sheet(s) read"
           + (" by the model." if info.get("read_by_model") else "."), me.get("email", ""))
    for s in styles:
        if s.get("bom"):
            gave = [label for label, key in (("description", "style_name"), ("colour", "colour"),
                                             ("fabric", "fabric"), ("sizes", "sizes")) if s.get(key)]
            tail = f" The sheet also gave the style's {', '.join(gave)}." if gave else ""
            _event(d, "bom", f"{s.get('style_no') or 'Style'}: {len(s['bom'])} line(s) read from "
                              f"{s.get('bom_file') or 'the mail'}.{tail}", me.get("email", ""))
    if who.get("customer"):
        _event(d, "customer", f"Customer {who['customer']} recognised ({who['how']}).")
    elif info.get("company"):
        d.attention = json.dumps({"kind": "customer", "text": f"Customer not found. The BOM is from “{info['company']}”.",
                                  "suggest": info["company"]})
    db.add(d)
    db.commit()
    for m in db.query(MailMessageModel).filter(MailMessageModel.thread_key == key).all():
        m.deal_id = d.id
    db.commit()
    return d


def create_manual(db, me: dict, customer: str = "", title: str = "", contact_email: str = "") -> DealModel:
    d = DealModel(title=(title or "New inquiry")[:200], stage="inquiry", customer=customer or None, customer_name=customer or None,
                  contact_email=contact_email or None, owner=me.get("email"), currency="USD")
    _save_styles(d, [new_style()])
    _event(d, "created", "Deal created by hand.", me.get("email", ""))
    db.add(d)
    db.commit()
    return d


_EDITABLE = ("title", "customer", "customer_name", "contact_email", "contact_name", "currency", "incoterm", "destination",
             "season", "product_type", "ex_factory", "in_warehouse", "notes")
_STYLE_EDITABLE = ("style_no", "style_name", "colour", "fabric", "qty", "sizes", "product_type", "bom", "target_price", "status")


def update(db, me: dict, deal_id: int, patch: dict) -> DealModel:
    d = _get(db, deal_id)
    registered = bool(d.refs_dict().get("opportunity"))
    for k in _EDITABLE:
        if k in (patch or {}):
            v = patch[k]
            if k == "customer" and registered and v != d.customer:
                raise DealError("The customer cannot change after the inquiry is in the ERP.")
            setattr(d, k, (str(v).strip() or None) if v is not None else None)
    if d.customer and d.contact_email and "customer" in (patch or {}):
        _kv_set(db, f"email_customer:{d.contact_email.lower()}", d.customer)
        att = json.loads(d.attention or "null")
        if att and att.get("kind") == "customer":
            d.attention = None
    if "styles" in (patch or {}):
        cur = {s["key"]: s for s in d.styles_list()}
        out = []
        for s in patch["styles"] or []:
            base = cur.get(s.get("key")) or new_style()
            if base.get("tech_pack") and s.get("style_no") and s["style_no"] != base["style_no"]:
                raise DealError(f"Style {base['style_no']} is already in the ERP; its number cannot change.")
            for k in _STYLE_EDITABLE:
                if k in s:
                    base[k] = s[k]
            if base.get("qty") not in (None, ""):
                try:
                    base["qty"] = int(float(base["qty"]))
                except Exception:
                    raise DealError(f"Quantity for {base.get('style_no') or 'a style'} is not a number.")
            out.append(base)
        removed = [s for k, s in cur.items() if k not in {x["key"] for x in out}]
        for s in removed:
            if s.get("tech_pack"):
                s["status"] = "dropped"              # in the ERP already: keep it, marked dropped
                out.append(s)
        _save_styles(d, out)
    _event(d, "edit", "Details updated.", me.get("email", ""))
    db.commit()
    return d


# ───────────────────────── 1 · register the inquiry in the ERP ─────────────────────────

def _written_name(res: dict, doctype: str) -> str:
    """The name of the document a write produced, whichever way the answer carries it.

    A write that has already run once is **replayed**, not repeated: ``pipeline.execute`` stores the result without the
    document body (it keeps ``written: ["insert Opportunity CRM-OPP-2026-00003"]``) and hands that back. Reading
    ``res["doc"]["name"]`` therefore raised a bare ``KeyError: 'doc'`` on any second attempt - which is exactly what a
    merchandiser sees after deleting an inquiry and reading it again (the deal id is reused, so the idempotency key
    matched the first attempt). The name is in ``written``; take it from there.
    """
    name = str(((res.get("doc") or {}).get("name")) or "").strip()
    if name:
        return name
    for w in res.get("written") or []:
        w = str(w)
        if w.startswith("call "):                 # an api call, not a document write
            continue
        op, _, rest = w.partition(" ")            # "insert Tech Pack TP-2026-00003"
        rest = rest.strip()
        if op in ("insert", "save", "submit", "cancel") and rest.startswith(doctype + " "):
            got = rest[len(doctype) + 1:].strip()
            if got:
                return got
    return ""


def _attempt_key(d, what: str) -> str:
    """An idempotency key that belongs to THIS deal, not to the id it happens to hold.

    Deleting an inquiry and starting it again from the same mail gives the new deal the same id (SQLite reuses it),
    so ``deal1-opp`` collided with the deleted deal's finished run and the "create the Opportunity" step was answered
    with a replay instead of a write. The creation stamp makes the key unique to the deal instance.
    """
    stamp = str(d.created_at or "")
    token = hashlib.sha1(f"{d.id}|{stamp}".encode()).hexdigest()[:8]
    return f"deal{d.id}-{token}-{what}"


def _adopt_open_opportunity(be, d, styles):
    """An Opportunity this same inquiry already made in the ERP (a re-read must not make a second one)."""
    if not d.customer:
        return ""
    try:
        rows = be.get_list("Opportunity", [["party_name", "=", d.customer], ["status", "=", "Open"], ["docstatus", "=", 0]],
                           ["name", "apparel_source_email", "apparel_target_qty", "apparel_product_type"], limit=20) or []
    except Exception:
        return ""
    want_mail = (d.contact_email or "").strip().lower()
    for r in rows:
        if want_mail and (r.get("apparel_source_email") or "").strip().lower() != want_mail:
            continue
        return str(r.get("name") or "")
    return ""


def _adopt_draft_tech_pack(be, d, style_no: str):
    """A draft Tech Pack this same customer already has for this style (with its draft Cost Sheet, if any)."""
    try:
        rows = be.get_list("Tech Pack", [["customer", "=", d.customer], ["style_no", "=", style_no], ["docstatus", "=", 0]],
                           ["name", "creation"], limit=10) or []
    except Exception:
        return "", ""
    if not rows:
        return "", ""
    rows.sort(key=lambda r: str(r.get("creation") or ""), reverse=True)
    tp = str(rows[0].get("name") or "")
    cs = ""
    if tp:
        try:
            sheets = be.get_list("Cost Sheet", [["tech_pack", "=", tp], ["docstatus", "=", 0]], ["name", "creation"], limit=5) or []
            sheets.sort(key=lambda r: str(r.get("creation") or ""), reverse=True)
            cs = str(sheets[0].get("name") or "") if sheets else ""
        except Exception:
            cs = ""
    return tp, cs


def _single(be, doctype: str) -> dict:
    """A Single's values (``Apparel Settings``): ``get_single`` first, the document form second."""
    try:
        got = dict(be.get_doc(doctype, doctype) or {})
        if got:
            return got
    except Exception:
        pass
    try:
        return dict(be.get_single(doctype) or {})
    except Exception:
        return {}


def _exists(be, doctype: str, name: str) -> bool:
    try:
        return bool(be.get_list(doctype, [["name", "=", name]], ["name"], limit=1))
    except Exception:
        return False


def _company_abbr(be) -> str:
    try:
        g = be.get_single("Global Defaults") or {}
        comp = g.get("default_company") or ""
        if comp:
            rows = be.get_list("Company", [["name", "=", comp]], ["name", "abbr"], limit=1)
            if rows and rows[0].get("abbr"):
                return str(rows[0]["abbr"])
    except Exception:
        pass
    try:
        rows = be.get_list("Company", None, ["name", "abbr"], limit=1)
        return str(rows[0].get("abbr") or "") if rows else ""
    except Exception:
        return ""


def _warehouse_name_for(current: str, abbr: str) -> str:
    """``Finished Goods - GGI`` becomes ``Finished Goods - CI`` on a company whose abbreviation is CI."""
    cur = str(current or "").strip()
    if not cur or not abbr:
        return ""
    if " - " in cur:
        head = cur.rsplit(" - ", 1)[0].strip()
        return f"{head} - {abbr}" if head else ""
    return f"{cur} - {abbr}"


def erp_setup(db, me: dict) -> dict:
    """Fill the ERP master data the Arinox scripts demand, when it points at records that do not exist.

    The site was rebuilt after a wipe (2026-11-05) and its **Apparel Settings** still pointed at the old company's
    warehouses (``… - GGI``), so the very next script refused: *"Could not find Finished Goods Warehouse: Finished Goods -
    GGI, Fabric Inspection Warehouse …"*. Every one of those links is a plain `Link` field on a Single, so instead of
    hardcoding a list of names, this walks the Settings' own **Link fields**, asks the ERP whether the record is there,
    and for a **Warehouse** makes the same one under this company's abbreviation. Anything it cannot fix mechanically is
    reported, never invented.

    Returns ``{"created": [...], "set": {field: value}, "unresolved": [...], "changed": bool}``.
    """
    be = _be()
    try:
        meta = be.get_doc("DocType", "Apparel Settings") or {}
    except Exception:
        return {"created": [], "set": {}, "unresolved": [], "changed": False}
    settings = _single(be, "Apparel Settings")
    if not settings:
        return {"created": [], "set": {}, "unresolved": [], "changed": False}
    abbr = _company_abbr(be)
    created: list[str] = []
    fixes: dict = {}
    unresolved: list[str] = []
    for f in meta.get("fields") or []:
        if (f.get("fieldtype") or "") != "Link":
            continue
        opt = str(f.get("options") or "").strip()
        val = str(settings.get(f.get("fieldname")) or "").strip()
        if not opt or not val:
            continue
        if _exists(be, opt, val):
            continue
        if opt == "Warehouse":
            new = _warehouse_name_for(val, abbr)
            if not new:
                unresolved.append(f"{f.get('label') or f.get('fieldname')}: {val}")
                continue
            if not _exists(be, "Warehouse", new):
                res = _ex(db, me, {"op": "insert", "doctype": "Warehouse",
                                   "data": {"warehouse_name": new.rsplit(" - ", 1)[0], "company": _company(be)},
                                   "idem_key": f"wh-{new}"[:60]}, _setup_retry=False)
                if res.get("ok"):
                    made = _written_name(res, "Warehouse") or ((res.get("doc") or {}).get("name")) or new
                    created.append(made)
                    new = made                      # the site names it: "<name> - <abbr>"
                else:
                    unresolved.append(f"{f.get('label') or f.get('fieldname')}: {val} ({_strip_html(str(res.get('error')))[:60]})")
                    continue
            fixes[f["fieldname"]] = new
        else:
            unresolved.append(f"{f.get('label') or f.get('fieldname')}: {val}")
    if fixes:
        data = dict(fixes)
        res = _ex(db, me, {"op": "save", "doctype": "Apparel Settings", "name": "Apparel Settings", "data": data,
                           "modified": settings.get("modified")}, _setup_retry=False)
        if not res.get("ok"):
            unresolved.append("Apparel Settings: " + _strip_html(str(res.get("error")))[:160])
            fixes = {}
    if created or fixes:
        try:
            write_gate.audit(db, "erp_setup", "Apparel Settings defaults",
                             f"created {', '.join(created) or 'nothing'}; pointed {', '.join(fixes) or 'nothing'}",
                             actor=me.get("email") or "")
        except Exception:
            pass
    return {"created": created, "set": fixes, "unresolved": unresolved, "changed": bool(created or fixes)}


def _item_group_for_style(be) -> str:
    """An Item Group that suits a style (the ERP refuses an Item without one).

    Preference: a leaf group that says garment/finished, then any leaf group that is not raw material, then anything.
    Nothing is invented: only a group that already exists in the ERP can be chosen.
    """
    try:
        groups = [r for r in (be.get_list("Item Group", [["is_group", "=", 0]], ["name"], limit=200) or []) if r.get("name")]
    except Exception:
        return ""
    names = [str(g["name"]) for g in groups]
    for want in ("finished garment", "garment", "finished good", "product"):
        hit = next((n for n in names if want in n.lower()), "")
        if hit:
            return hit
    skip = ("fabric", "trim", "pack", "dye", "chemical", "consumable", "service", "job work", "sub assembl", "scrap")
    for n in names:
        if not any(k in n.lower() for k in skip):
            return n
    return names[0] if names else ""


def _ensure_item_group(db, me: dict, be, style: dict, product_type: str) -> str:
    """Make sure the Product Type has an Item Group, so the ERP's style-item script can make the Item.

    The ERP's own script says it plainly: *"Set an Item Group on Product Type X or a Style Item Group in Apparel
    Settings"* - and on this site every Product Type had **none**, so the contract stopped dead at the Item step
    (2026-11-07). The tower sets the missing default on the Product Type it needs, records it on the timeline, and moves
    on; nothing else about the master data is touched.
    """
    pt = str(product_type or "").strip()
    if not pt:
        return ""
    try:
        cur = be.get_doc("Product Type", pt) or {}
    except Exception:
        return ""
    have = str(cur.get("item_group") or "").strip()
    if have:
        return have
    group = _item_group_for_style(be)
    if not group:
        return ""
    res = _ex(db, me, {"op": "save", "doctype": "Product Type", "name": pt, "data": {"item_group": group},
                       "modified": cur.get("modified"), "idem_key": f"pt-{pt}-itemgroup"})
    if not res.get("ok"):
        return ""
    try:
        _event_note = f"Product Type {pt} had no Item Group (the ERP needs one to make a style Item); set it to {group}."
        return group
    except Exception:
        return group


def _make_style_item(db, me: dict, be, d, s: dict, idem: str) -> tuple[bool, str]:
    """The ERP's own style-item script, with the Item Group repaired first if that is what it is missing."""
    def call():
        return _ex(db, me, {"op": "api", "method": "arinox_tech_pack_create_style_item",
                            "params": {"tech_pack": s["tech_pack"]}, "idem_key": idem})

    res = call()
    if res.get("ok") and isinstance(res.get("result"), str):
        return True, res["result"]
    err = _strip_html(str(res.get("error") or ""))
    if "item group" in err.lower() and s.get("product_type"):
        group = _ensure_item_group(db, me, be, s, s["product_type"])
        if group:
            _event(d, "erp", f"Product Type {s['product_type']} had no Item Group; set it to {group} so the style Item "
                             f"could be made.", me.get("email", ""))
            db.commit()
            res = call()
            if res.get("ok") and isinstance(res.get("result"), str):
                return True, res["result"]
            err = _strip_html(str(res.get("error") or err))
    return False, err or "refused"


def register(db, me: dict, deal_id: int) -> DealModel:
    """Opportunity + one Tech Pack per style (BOM, colour, sizes). No price is asked for or needed."""
    d = _get(db, deal_id)
    styles = d.styles_list()
    problems = []
    if not d.customer:
        problems.append("pick or add the customer")
    if not live(styles):
        problems.append("add at least one style")
    for s in live(styles):
        if not (s.get("style_no") or "").strip():
            problems.append("every style needs its style number")
        if not s.get("product_type"):
            problems.append(f"{s.get('style_no') or 'a style'}: choose the product type (costing rates depend on it)")
    if problems:
        raise DealError("Before this goes to the ERP: " + "; ".join(dict.fromkeys(problems)) + ".")
    be = _be()
    refs = d.refs_dict()
    if not refs.get("opportunity"):
        qty = sum(int(s.get("qty") or 0) for s in live(styles))
        data = {"opportunity_from": "Customer", "party_name": d.customer, "company": _company(be), "status": "Open",
                "transaction_date": _today(), "currency": d.currency, "apparel_product_type": d.product_type or live(styles)[0]["product_type"],
                "apparel_season": d.season, "apparel_target_qty": qty or None, "apparel_source_email": (d.contact_email or "")[:140],
                "apparel_delivery_from": d.ex_factory, "apparel_delivery_to": d.in_warehouse}
        if live(styles)[0].get("target_price"):
            data["apparel_target_fob"] = live(styles)[0]["target_price"]
        if d.contact_email:
            data["contact_email"] = d.contact_email
        existing = _adopt_open_opportunity(be, d, live(styles))
        if existing:
            _set_refs(d, opportunity=existing)
            _event(d, "erp", f"Opportunity {existing} adopted (this inquiry was already in the ERP, so no second one was "
                             f"made).", me.get("email", ""), doc=["Opportunity", existing])
            db.commit()
        else:
            res = _must(_ex(db, me, {"op": "insert", "doctype": "Opportunity", "data": {k: v for k, v in data.items() if v not in (None, "")},
                                     "idem_key": _attempt_key(d, "opp")}), "Opportunity not created")
            name = _written_name(res, "Opportunity")
            if not name:
                raise DealError("The ERP accepted the Opportunity but did not say which document it is. Open the ERP and "
                                "check the Opportunity for this buyer before trying again.")
            _set_refs(d, opportunity=name)
            _event(d, "erp", f"Opportunity {name} created.", me.get("email", ""), doc=["Opportunity", name])
            db.commit()
    opp = d.refs_dict()["opportunity"]
    for s in live(styles):
        if s.get("tech_pack"):
            continue
        mats = []
        for r in s.get("bom") or []:
            if not (r.get("description") or r.get("item_code")):
                continue
            mats.append({k: v for k, v in {
                "material_type": r.get("material_type") or "Other", "description": (r.get("description") or r.get("item_code"))[:140],
                "consumption": r.get("consumption") or 0, "uom": _uom(be, r.get("uom")), "colour": (r.get("colour") or "")[:60],
                "buyer_item_code": r.get("item_code") or None, "placement": r.get("placement") or None,
                "remarks": r.get("remarks") or None, "composition": None}.items() if v not in (None, "")})
        data = {"customer": d.customer, "opportunity": opp, "style_no": s["style_no"], "style_name": s.get("style_name") or None,
                "season": d.season, "product_type": s["product_type"], "fabric_content": (s.get("fabric") or "")[:140] or None,
                "source": "Email", "source_reference": (d.title or "")[:140], "received_on": _today(), "materials": mats,
                "colours": [{"colour": c.strip()} for c in re.split(r"[,/;]", s.get("colour") or "") if c.strip()][:20],
                "sizes": [{"size": z} for z in (s.get("sizes") or [])]}
        if s.get("bom_file"):
            data["ai_extraction_notes"] = f"BOM read from {s['bom_file']} ({len(mats)} lines)."[:140]
            data["extracted_by_ai"] = 0
        # the Tech Pack's OWN content (a different document from the BOM): the measurement chart, construction, wash &
        # care and packing, as the buyer's tech pack prints them.
        spec = s.get("spec") or {}
        if spec:
            chart, unmapped = tp_measurements(spec)
            if chart:
                data["measurements"] = chart
            for key in _TP_TEXT_FIELDS:
                if spec.get(key):
                    data[key] = str(spec[key])[:8000]
            if spec.get("size_range"):
                data["size_range"] = str(spec["size_range"])[:40]
            elif s.get("sizes"):
                data["size_range"] = ("-".join([str(s["sizes"][0]), str(s["sizes"][-1])])
                                      if len(s["sizes"]) > 1 else str(s["sizes"][0]))[:40]
            if s.get("colour"):
                data.setdefault("fabric_code", None)
            notes = []
            if spec.get("source"):
                notes.append(f"Tech pack read from {spec['source']}")
            if chart:
                notes.append(f"{len(chart)} measurement row(s)")
            if unmapped:
                notes.append(f"sizes not charted: {', '.join(unmapped)}")
            if notes:
                s["warnings"] = list(dict.fromkeys((s.get("warnings") or []) + [" · ".join(notes)]))
        # a re-read of the same inquiry must not leave a second Tech Pack behind for the same style
        tp, cs = _adopt_draft_tech_pack(be, d, s["style_no"])
        if tp:
            s["tech_pack"] = tp
            if cs:
                s["cost_sheet"], s["cost_status"] = cs, s.get("cost_status") or "draft"
            _save_styles(d, styles)
            _event(d, "erp", f"Tech Pack {tp} adopted for {s['style_no']} (a draft for this buyer and style was already in "
                             f"the ERP, so no second one was made)" + (f", with Cost Sheet {cs}" if cs else "") +
                             "; it was refreshed from the buyer's sheet (materials, sizes, description).",
                   me.get("email", ""), doc=["Tech Pack", tp])
            # an adopted pack is brought up to date from the sheet we just read - that is the point of adopting it
            refresh = {k: v for k, v in data.items() if v not in (None, "", [])}
            _ex(db, me, {"op": "save", "doctype": "Tech Pack", "name": tp, "data": refresh,
                         "modified": (be.get_doc("Tech Pack", tp) or {}).get("modified"),
                         "idem_key": _attempt_key(d, f"tp-refresh-{s['key']}")})
        else:
            res = _must(_ex(db, me, {"op": "insert", "doctype": "Tech Pack",
                                     "data": {k: v for k, v in data.items() if v not in (None, "", [])},
                                     "idem_key": _attempt_key(d, f"tp-{s['key']}")}), f"Tech Pack for {s['style_no']} not created")
            name = _written_name(res, "Tech Pack")
            if not name:
                raise DealError(f"The ERP accepted the Tech Pack for {s['style_no']} but did not say which document it is. "
                                f"Open the ERP and check before trying again.")
            s["tech_pack"] = name
            _event(d, "erp", f"Tech Pack {name} for {s['style_no']} ({len(mats)} BOM lines).", me.get("email", ""), doc=["Tech Pack", name])
        # the style as an Item (colours × sizes) — needed for the Sales Order; a failure here is a note, not a stop
        ok_item, item_res = _make_style_item(db, me, be, d, s, _attempt_key(d, f"item-{s['key']}"))
        if ok_item:
            s["style_item"] = item_res
        else:
            err = item_res
            if "already exists" in err.lower():
                # a re-read of the same inquiry: the style Item exists from the earlier attempt, so use it
                s["style_item"] = (_first(be, "Item", [["item_code", "=", s["style_no"]]])
                                   or _first(be, "Item", [["name", "=", s["style_no"]]]) or "")
            if not s.get("style_item"):
                s.setdefault("warnings", []).append(f"Style item not made yet: {err}")
        _save_styles(d, styles)
        db.commit()
    if d.stage == "inquiry":
        d.stage = "costing"
    db.commit()
    return d


_UOM_CACHE: dict = {}


def _uom(be, u: str) -> Optional[str]:
    """The buyer's unit if the ERP has it (Yard, Nos …), else nothing — an unknown UOM link would refuse the save."""
    u = (u or "").strip()
    if not u:
        return None
    if u not in _UOM_CACHE:
        try:
            _UOM_CACHE[u] = be.exists("UOM", u) or (be.exists("UOM", u.title()) if u.title() != u else None)
        except Exception:
            _UOM_CACHE[u] = None
    return _UOM_CACHE[u] or None


# ───────────────────────── 2 · costing ─────────────────────────

_CS_TOTALS = ("fabric_cost", "trim_cost", "material_cost", "conversion_cost", "product_cost", "subtotal", "profit_amount",
              "computed_price", "quoted_price", "margin_amount", "margin_pct", "markup_pct", "margin_floor_pct", "below_floor",
              "order_value", "fabric_metres", "approval_status", "currency", "order_qty", "sam", "costing_parameter")
_MAT_FIELDS = ("material_type", "description", "item", "uom", "consumption", "wastage_pct", "wastage_reason", "rate", "amount",
               "option_group", "is_selected", "price_currency", "exchange_rate", "conversion_factor", "supplier", "remarks", "per_carton")
_CHG_FIELDS = ("cost_head", "calc_type", "rate", "not_applicable", "amount", "head_group", "sequence", "remarks", "source")


def cost_view(doc: dict) -> dict:
    return {"name": doc.get("name"), "docstatus": doc.get("docstatus", 0), "style_no": doc.get("style_no"),
            "url": _doc_url("Cost Sheet", doc["name"]) if doc.get("name") else "",
            "totals": {k: doc.get(k) for k in _CS_TOTALS},
            "materials": [{**{k: r.get(k) for k in _MAT_FIELDS}, "idx": r.get("idx") or i + 1} for i, r in enumerate(doc.get("materials") or [])],
            "charges": sorted([{**{k: r.get(k) for k in _CHG_FIELDS}, "idx": r.get("idx") or i + 1} for i, r in enumerate(doc.get("charges") or [])],
                              key=lambda r: (r.get("sequence") or 0, r["idx"]))}


def _cost_summary(doc: dict) -> dict:
    return {k: doc.get(k) for k in ("computed_price", "quoted_price", "margin_pct", "material_cost", "conversion_cost",
                                    "below_floor", "margin_floor_pct", "approval_status")}


def cost_open(db, me: dict, deal_id: int, style_key: str) -> dict:
    d = _get(db, deal_id)
    styles = d.styles_list()
    s = _style(styles, style_key)
    be = _be()
    if not s.get("tech_pack"):
        raise DealError("Send the inquiry to the ERP first (it makes the Tech Pack this costing starts from).")
    if not s.get("cost_sheet"):
        made = _must(_ex(db, me, {"op": "api", "method": "arinox_tech_pack_make_cost_sheet", "params": {"source_name": s["tech_pack"]}}),
                     f"Cost sheet for {s['style_no']} not started")
        cs = clean(made["result"])
        cs.update({"doctype": "Cost Sheet", "costing_date": _today(), "order_qty": int(s.get("qty") or 0) or cs.get("order_qty"),
                   "currency": cs.get("currency") or d.currency, "in_warehouse_date": d.in_warehouse or None})
        # rates the buyer's BOM carried (rare) fill the lines the ERP had no buying price for
        bom = [r for r in (s.get("bom") or []) if r.get("description") or r.get("item_code")]
        for i, m in enumerate(cs.get("materials") or []):
            if not m.get("rate") and i < len(bom) and bom[i].get("rate"):
                m["rate"] = bom[i]["rate"]
        ins = _must(_ex(db, me, {"op": "insert", "doctype": "Cost Sheet", "data": {k: v for k, v in cs.items() if v is not None},
                                 "idem_key": _attempt_key(d, f"cs-{s['key']}-r{int(s.get('cs_rev') or 1)}")}),
                    f"Cost sheet for {s['style_no']} not saved")
        cs_name = _written_name(ins, "Cost Sheet")
        if not cs_name:
            raise DealError(f"The ERP accepted the Cost Sheet for {s['style_no']} but did not say which document it is. "
                            f"Open the ERP and check before trying again.")
        s["cost_sheet"], s["cost_status"] = cs_name, "draft"
        s["cost"] = _cost_summary(ins.get("doc") or be.get_doc("Cost Sheet", cs_name) or {})
        _event(d, "erp", f"Cost Sheet {s['cost_sheet']} for {s['style_no']}.", me.get("email", ""), doc=["Cost Sheet", s["cost_sheet"]])
        _save_styles(d, styles)
        db.commit()
        doc = ins.get("doc") or be.get_doc("Cost Sheet", cs_name)
    else:
        doc = be.get_doc("Cost Sheet", s["cost_sheet"])
    heads = []
    try:
        heads = be.get_list("Cost Head", [["enabled", "=", 1]], ["name", "calc_type", "head_group", "is_mandatory", "sequence"], order_by="sequence asc")
    except Exception:
        pass
    return {"cost_sheet": cost_view(doc), "heads": heads, "style": s}


#: Row fields that must arrive as numbers; the browser can hand back a string ("0.06", "00.06", "") and Frappe then
#: refuses the row or stores text where it wants a Float.
_ROW_NUMBERS = ("consumption", "wastage_pct", "rate", "qty", "price", "exchange_rate", "conversion_factor", "per_carton",
                "sam", "ratio")


def _merge_rows(existing: list, edits: Optional[list], fields: tuple, be=None) -> list:
    """The child rows to send back, built from **our** whitelist - never from the ERP's own row.

    Copying the stored row as a base looked harmless and was not: the ERP's child rows carry ``docstatus``, ``doctype``,
    ``parent``, ``modified`` … and sending them back makes Frappe refuse the whole save with
    *"materials row 1: docstatus changes only through Submit / Cancel"* — one row per stored row, and the costing could
    not be saved, recalculated or submitted at all (2026-11-07). Only the fields the form owns are sent; ``amount`` is
    left out because the ERP computes it; numbers are coerced; a UOM that is not a real unit is dropped rather than sent
    as a broken link.
    """
    if edits is None:
        return existing
    out = []
    for e in edits:
        if not isinstance(e, dict):
            continue
        row: dict[str, Any] = {}
        try:
            if e.get("idx") not in (None, ""):
                row["idx"] = int(e["idx"])
        except Exception:
            pass
        for k in fields:
            if k not in e or k == "amount":
                continue
            v = e[k]
            if k in _ROW_NUMBERS:
                num = _ai_number(v)
                if num is None:
                    continue
                v = num
            elif isinstance(v, str):
                v = v.strip()
                if k == "uom" and v in ("—", "-", ""):
                    continue
                if be is not None and k == "uom":
                    v = _uom(be, v) or ""
                    if not v:
                        continue
            row[k] = v
        out.append(row)
    return out


def cost_save(db, me: dict, deal_id: int, style_key: str, materials: Optional[list] = None, charges: Optional[list] = None,
              quoted_price: Any = None, preview: bool = False, extra: Optional[dict] = None) -> dict:
    """Save the costing edits; the ERP's own Cost Sheet rules compute the price. ``preview`` computes without saving."""
    d = _get(db, deal_id)
    styles = d.styles_list()
    s = _style(styles, style_key)
    if not s.get("cost_sheet"):
        raise DealError("Open the costing first.")
    be = _be()
    cur = be.get_doc("Cost Sheet", s["cost_sheet"])
    if int(cur.get("docstatus") or 0) == 1:
        raise DealError("This costing is submitted. Amend it in the ERP to change it, or start a revision.")
    data: dict[str, Any] = {}
    if materials is not None:
        data["materials"] = _merge_rows(cur.get("materials") or [], materials, _MAT_FIELDS, be)
    if charges is not None:
        data["charges"] = _merge_rows(cur.get("charges") or [], charges, _CHG_FIELDS, be)
    if quoted_price not in (None, ""):
        data["quoted_price"] = float(quoted_price)
    for k in ("sam", "order_qty", "pcs_per_carton", "fob_port"):
        if extra and k in extra and extra[k] not in (None, ""):
            data[k] = extra[k]
    res = _ex(db, me, {"op": "save", "doctype": "Cost Sheet", "name": s["cost_sheet"], "data": data, "preview": bool(preview),
                       "modified": cur.get("modified")})
    if not res.get("ok"):
        raise DealError(res.get("error") or "The costing was refused.")
    doc = (res.get("preview") or {}).get("doc") if preview else res.get("doc")
    msgs = [m.get("message") for m in ((res.get("preview") or {}).get("messages") if preview else res.get("messages")) or [] if m.get("message")]
    if not preview and doc:
        s["cost"] = _cost_summary(doc)
        _save_styles(d, styles)
        _event(d, "costing", f"{s['style_no']} costed at {doc.get('quoted_price')} {doc.get('currency')} "
                             f"(margin {doc.get('margin_pct')}%).", me.get("email", ""))
        db.commit()
    return {"cost_sheet": cost_view(doc or cur), "messages": msgs, "saved": not preview}


def _cost_refusal(text: str) -> str:
    """The ERP's costing rules in words a merchandiser can act on."""
    t = _strip_html(text or "")
    m = re.match(r"\s*Zero rate without N/?A:?\s*(.+)$", t, re.I)
    if m:
        heads = ", ".join(h.strip() for h in m.group(1).split(",")[:24])
        return (f"The ERP needs a rate for every cost head, or N/A ticked: {heads}. Give them a rate, or tick N/A for the "
                f"ones this style does not use, then save.")
    return t


def cost_submit(db, me: dict, deal_id: int, style_key: str) -> dict:
    d = _get(db, deal_id)
    styles = d.styles_list()
    s = _style(styles, style_key)
    if not s.get("cost_sheet"):
        raise DealError("Open the costing first.")
    res = _ex(db, me, {"op": "submit", "doctype": "Cost Sheet", "name": s["cost_sheet"], "idem_key": f"deal{d.id}-cs-submit-{s['cost_sheet']}"})
    if not res.get("ok"):
        raise DealError(_cost_refusal(res.get("error") or "The ERP refused to submit the costing."))
    s["cost_status"] = "submitted"
    s["cost"] = _cost_summary(res.get("doc") or {}) or s.get("cost")
    _save_styles(d, styles)
    _event(d, "erp", f"Cost Sheet {s['cost_sheet']} submitted at {s['cost'].get('quoted_price')}.", me.get("email", ""))
    db.commit()
    return {"style": s}


def _strip_html(t: str) -> str:
    return re.sub(r"<br\s*/?>", "; ", re.sub(r"<(?!br)[^>]+>", "", t or ""))


# ───────────────────────── 3 · the quote ─────────────────────────

def _money(v, ccy) -> str:
    try:
        return f"{ccy} {float(v):,.2f}"
    except Exception:
        return "—"


def quote_draft(db, me: dict, deal_id: int) -> dict:
    d = _get(db, deal_id)
    styles = live(d.styles_list())
    not_ready = [s["style_no"] for s in styles if s.get("cost_status") != "submitted"]
    if not_ready:
        raise DealError("Finish and submit the costing for: " + ", ".join(not_ready) + ".")
    ccy = d.currency or "USD"
    terms = " ".join(x for x in (d.incoterm or "", d.destination or "") if x).strip()
    name = (d.contact_name or "").split()[0] if d.contact_name and d.contact_name.lower() not in ("temporary",) else ""
    lines = [f"Dear {name or (d.customer_name or d.customer or 'team')},", "",
             "Thank you for your inquiry. Please find our price for each style below.", ""]
    w = max(len(s["style_no"]) for s in styles)
    lines.append(f"{'Style'.ljust(w)} | Description | Colour | Qty | Price / pc{(' ' + terms) if terms else ''}")
    for s in styles:
        price = s.get("offer_price") or (s.get("cost") or {}).get("quoted_price")
        lines.append(f"{s['style_no'].ljust(w)} | {s.get('style_name') or '-'} | {s.get('colour') or '-'} | "
                     f"{int(s.get('qty') or 0):,} | {_money(price, ccy)}")
    lines += ["", "Prices are per piece" + (f", {terms}" if terms else "") + ", valid for 30 days, and based on the BOM you sent."]
    if d.ex_factory:
        lines.append(f"Ex-factory: {d.ex_factory}, subject to fabric and approval timelines.")
    lines += ["", "Please let us know if these work for you, and we will prepare the sales contract.", "", "Kind regards,",
              config.MAIL_FROM_NAME]
    subject = None
    return {"to": d.contact_email or "", "subject": subject, "body": "\n".join(lines),
            "styles": [{"key": s["key"], "style_no": s["style_no"], "price": s.get("offer_price") or (s.get("cost") or {}).get("quoted_price"),
                        "qty": s.get("qty")} for s in styles]}


def quote_send(db, me: dict, deal_id: int, body: str, to: str = "", cc: str = "", subject: str = "") -> dict:
    """Put each costing into the negotiation (our opening offer) and send the quote in the deal's mail thread."""
    import mailbox
    d = _get(db, deal_id)
    styles = d.styles_list()
    qd = quote_draft(db, me, deal_id)                       # raises if a costing is not submitted
    for s in live(styles):
        if s.get("in_negotiation"):
            continue
        res = _must(_ex(db, me, {"op": "api", "method": "arinox_cost_sheet_make_price_negotiation", "params": {"source_name": s["cost_sheet"]},
                                 "idem_key": f"deal{d.id}-pn-{s['cost_sheet']}"}), f"{s['style_no']} not added to the negotiation")
        pn = res.get("result") if isinstance(res.get("result"), str) else d.refs_dict().get("price_negotiation")
        _set_refs(d, price_negotiation=pn)
        s["in_negotiation"] = True
        s["offer_price"] = (s.get("cost") or {}).get("quoted_price")
    _save_styles(d, styles)
    db.commit()
    if d.thread_key:
        sent = mailbox.send_in_thread(db, me, d.thread_key, body or qd["body"], to=to or qd["to"], cc=cc, subject=subject,
                                      deal_id=d.id, intent="quote")
    else:
        sent = mailbox.send_new(db, me, to or qd["to"], subject or f"Quotation — {d.title}", body or qd["body"], cc=cc, deal_id=d.id, intent="quote")
        if sent.get("ok"):
            d.thread_key = sent["thread_key"]
    if not sent.get("ok"):
        db.commit()
        raise DealError(sent.get("error") or "The quote was not sent.")
    d.stage = "quoted" if d.stage in ("inquiry", "costing") else d.stage
    d.quote_sent_at = datetime.now()
    d.attention = None
    _event(d, "mail", f"Quote sent to {sent['to']} — " + ", ".join(f"{s['style_no']} {_money(s.get('offer_price'), d.currency)}" for s in live(styles)),
           me.get("email", ""))
    db.commit()
    return {"sent": sent}


# ───────────────────────── 4 · the buyer's answer ─────────────────────────

_DIR = {"counter": "Buyer Counter", "our_counter": "Our Counter", "accepted": "Agreed", "drop": "Dropped", "target": "Buyer Target"}


def record_reply(db, me: dict, deal_id: int, outcome: str, prices: Optional[dict] = None, note: str = "",
                 channel: str = "Email", lost_reason: str = "") -> DealModel:
    """Write the buyer's answer into the Price Negotiation: a counter, our counter, agreement, a dropped style, or lost."""
    d = _get(db, deal_id)
    styles = d.styles_list()
    pn = d.refs_dict().get("price_negotiation")
    if not pn:
        raise DealError("Send the quote first; the negotiation starts with it.")
    be = _be()
    cur = be.get_doc("Price Negotiation", pn)
    prices = {k: v for k, v in (prices or {}).items() if v not in (None, "")}
    if outcome == "lost":
        res = _must(_ex(db, me, {"op": "save", "doctype": "Price Negotiation", "name": pn,
                                 "data": {"status": "Lost", "lost_reason": (lost_reason or note or "Buyer declined")[:500]}}), "Not recorded")
        d.stage, d.attention = "lost", None
        _event(d, "lost", f"Marked lost: {lost_reason or note or 'buyer declined'}.", me.get("email", ""))
        db.commit()
        return d
    if outcome not in _DIR:
        raise DealError("Unknown answer.")
    rounds = list(cur.get("rounds") or [])
    touched = []
    for s in live(styles):
        if outcome in ("counter", "our_counter", "drop") and s["key"] not in prices and outcome != "drop":
            continue
        if outcome == "drop" and s["key"] not in prices:
            continue
        if outcome == "accepted":
            price = prices.get(s["key"]) or s.get("buyer_price") or s.get("offer_price") or (s.get("cost") or {}).get("quoted_price")
        else:
            price = prices.get(s["key"])
        if outcome != "drop" and not price:
            continue
        rounds.append({k: v for k, v in {"round_date": _today(), "cost_sheet": s["cost_sheet"], "direction": _DIR[outcome],
                                         "price": float(price) if outcome != "drop" else None, "qty": int(s.get("qty") or 0) or None,
                                         "channel": channel, "remarks": (note or "")[:500] or None}.items() if v is not None})
        if outcome == "counter":
            s["buyer_price"] = float(price)
        elif outcome == "our_counter":
            s["offer_price"] = float(price)
        elif outcome == "accepted":
            s["agreed_price"], s["status"] = float(price), "agreed"
        elif outcome == "drop":
            s["status"] = "dropped"
        touched.append(s["style_no"])
    if not touched:
        raise DealError("Enter a price for at least one style.")
    res = _must(_ex(db, me, {"op": "save", "doctype": "Price Negotiation", "name": pn, "data": {"rounds": rounds},
                             "modified": cur.get("modified")}), "Not recorded in the negotiation")
    doc = res.get("doc") or {}
    for row in doc.get("styles") or []:                 # the ERP's view of each style wins (agreed price, margin at it)
        s = next((x for x in styles if x.get("cost_sheet") == row.get("cost_sheet")), None)
        if s:
            s["margin_at_agreed"] = row.get("margin_at_agreed")
    _save_styles(d, styles)
    left = [s for s in live(styles) if s.get("status") != "agreed"]
    if outcome == "accepted" and not left:
        d.stage = "accepted"
    elif d.stage in ("quoted", "costing") and outcome in ("counter", "our_counter"):
        d.stage = "negotiating"
    if outcome in ("accepted", "counter"):
        d.attention = None
    label = {"counter": "Buyer countered", "our_counter": "We countered", "accepted": "Agreed", "drop": "Dropped"}[outcome]
    _event(d, "negotiation", f"{label}: " + ", ".join(touched) + (f" — {note}" if note else ""), me.get("email", ""))
    db.commit()
    return d


# ───────────────────────── 5 · contract ─────────────────────────

def _readiness(sc: dict) -> list[str]:
    """The checks the ERP runs when the contract is signed, so they can be fixed before pressing Sign."""
    out = []
    sized: dict[tuple, int] = {}
    for z in sc.get("sizes") or []:
        k = (z.get("style_item"), (z.get("colour") or "").upper())
        sized[k] = sized.get(k, 0) + int(z.get("qty") or 0)
    for it in sc.get("items") or []:
        label = f"{it.get('style_no') or it.get('style_item')} / {it.get('colour') or '-'}"
        if not it.get("colour"):
            out.append(f"{label}: colour")
        if int(it.get("qty") or 0) <= 0:
            out.append(f"{label}: quantity")
        if not float(it.get("rate") or 0):
            out.append(f"{label}: price")
        for f, n in (("ex_factory_date", "ex-factory date"), ("etd", "ETD"), ("in_warehouse_date", "in-warehouse date")):
            if not it.get(f):
                out.append(f"{label}: {n}")
        k = (it.get("style_item"), (it.get("colour") or "").upper())
        if sized.get(k, 0) != int(it.get("qty") or 0):
            out.append(f"{label}: sizes add up to {sized.get(k, 0)}, the line says {int(it.get('qty') or 0)}")
    if not sc.get("incoterm"):
        out.append("Incoterm")
    if not sc.get("port_of_loading"):
        out.append("Port of loading")
    if not ((sc.get("payment_basis") and int(sc.get("payment_days") or 0)) or sc.get("payment_basis") == "Advance" or sc.get("payment_terms_template")):
        out.append("Payment terms (basis and days)")
    return out


def contract_prepare(db, me: dict, deal_id: int) -> dict:
    """Quotation at the agreed prices (submitted), then the contract draft the ERP's script builds from it."""
    d = _get(db, deal_id)
    styles = d.styles_list()
    if [s for s in live(styles) if s.get("status") != "agreed"]:
        raise DealError("Record the agreed price for every style first (Buyer's answer → Agreed).")
    be = _be()
    live_contract(db, d, be)                 # a cancelled contract is replaced by its amendment, or dropped
    refs = d.refs_dict()
    # every style needs its own Item (colour × size variants) before the contract: the contract lines and the Sales
    # Order rows hang off it. Retry what registration could not make, and stop with the ERP's reason if it still fails.
    missing = []
    for s in live(styles):
        if s.get("style_item") or not s.get("tech_pack"):
            continue
        ok_item, item_res = _make_style_item(db, me, be, d, s, f"deal{d.id}-item2-{s['key']}")
        if ok_item:
            s["style_item"] = item_res
            s["warnings"] = [w for w in (s.get("warnings") or []) if not w.startswith("Style item not made")]
        else:
            missing.append(f"{s['style_no']}: {item_res}")
    _save_styles(d, styles)
    db.commit()
    if missing:
        raise DealError("Each style needs its Item in the ERP before the contract (" + "; ".join(missing[:3]) +
                        "). Fix it in ERP records → Product Type (set the Item Group), then press again.")
    if not refs.get("quotation"):
        made = _must(_ex(db, me, {"op": "api", "method": "arinox_price_negotiation_make_quotation", "params": {"source_name": refs["price_negotiation"]}}),
                     "Quotation not prepared")
        q = clean(made["result"])
        q["doctype"] = "Quotation"
        q.setdefault("transaction_date", _today())
        q.setdefault("order_type", "Sales")
        ins = _must(_ex(db, me, {"op": "insert", "doctype": "Quotation", "data": q, "idem_key": _attempt_key(d, "qtn")}), "Quotation not saved")
        qn = _written_name(ins, "Quotation")
        if not qn:
            raise DealError("The ERP accepted the Quotation but did not say which document it is. Open the ERP and check "
                            "before trying again.")
        _must(_ex(db, me, {"op": "submit", "doctype": "Quotation", "name": qn, "idem_key": _attempt_key(d, "qtn-submit")}),
              "Quotation not submitted")
        _set_refs(d, quotation=qn)
        _event(d, "erp", f"Quotation {qn} at the agreed prices (submitted).", me.get("email", ""), doc=["Quotation", qn])
        db.commit()
    if d.refs_dict().get("sales_contract"):
        return {"draft": json.loads(d.contract_draft or "{}"), "readiness": _readiness(json.loads(d.contract_draft or "{}"))}
    made = _must(_ex(db, me, {"op": "api", "method": "arinox_sales_contract_make_sales_contract", "params": {"source_name": d.refs_dict()["quotation"]}}),
                 "Contract not prepared")
    sc = clean(made["result"])
    sc["doctype"] = "Sales Contract"
    sc["contract_date"] = sc.get("contract_date") or _today()
    if d.incoterm and not sc.get("incoterm") and be.exists("Incoterm", d.incoterm):
        sc["incoterm"] = d.incoterm
    if d.destination and not sc.get("named_place"):
        sc["named_place"] = d.destination
    by_no = {s["style_no"]: s for s in live(styles)}
    etd_gap = int(sc.get("days_ex_factory_to_etd") or 0)
    for it in sc.get("items") or []:
        s = by_no.get(it.get("style_no"))
        if s and not int(it.get("qty") or 0) and len([x for x in sc["items"] if x.get("style_no") == it.get("style_no")]) == 1:
            it["qty"] = int(s.get("qty") or 0)
        if d.ex_factory and not it.get("ex_factory_date"):
            it["ex_factory_date"] = d.ex_factory
        if it.get("ex_factory_date") and not it.get("etd"):
            it["etd"] = (date.fromisoformat(str(it["ex_factory_date"])[:10]) + timedelta(days=etd_gap)).isoformat()
        if d.in_warehouse and not it.get("in_warehouse_date"):
            it["in_warehouse_date"] = d.in_warehouse
    _respread_sizes(sc)
    d.contract_draft = json.dumps(sc, default=str)
    if d.stage == "accepted":
        d.stage = "accepted"
    db.commit()
    return {"draft": sc, "readiness": _readiness(sc) + _check_links(db, sc)}


def _respread_sizes(sc: dict) -> None:
    """Size rows with no quantity get the line quantity spread evenly (the remainder on the base sizes); rows a person
    typed are left alone."""
    for it in sc.get("items") or []:
        rows = [z for z in sc.get("sizes") or [] if z.get("style_item") == it.get("style_item") and (z.get("colour") or "") == (it.get("colour") or "")]
        if not rows or sum(int(z.get("qty") or 0) for z in rows) or not int(it.get("qty") or 0):
            continue
        q, n = int(it["qty"]), len(rows)
        base, rem = divmod(q, n)
        mid = (n - 1) / 2
        extra = set(sorted(range(n), key=lambda i: (abs(i - mid), i))[:rem])     # the leftover pieces go to the middle sizes
        for i, z in enumerate(rows):
            z["qty"] = base + (1 if i in extra else 0)


#: every Sales Contract field the tower writes - the whole paper, not just the few that are needed to sign it, so what is
#: written into the ERP is also what the tower shows.
_SC_HEADER = ("buyer_po_no", "contract_date", "season", "brand", "division", "buyer_contact",
              "incoterm", "named_place", "port_of_loading", "port_of_discharge", "shipment_mode", "country_of_origin",
              "freight_by", "insurance_by",
              "days_ex_factory_to_etd", "transit_days", "delay_days_allowed", "late_shipment_terms",
              "quantity_claim_days", "quality_claim_days", "objection_days", "discrepancy_days",
              "aql_level", "inspection_terms", "packing_instructions", "shipping_marks", "documents_list",
              "payment_basis", "payment_days", "payment_terms_template", "arbitration", "terms",
              "production_lead_days",
              "signed_by_buyer", "buyer_signed_on", "company_signed_on")

#: the Sales Contract fields that are a link to another ERP record: a value that is not a record there is refused by the
#: ERP with "Could not find <doctype>: <value>", so it is checked here first and answered with the values that do exist.
_SC_LINKS = {"incoterm": ("Incoterm", "Incoterm"), "payment_terms_template": ("Payment Terms Template", "Payment terms"),
             "contract_template": ("Sales Contract Template", "Contract template"),
             "terms_and_conditions": ("Terms and Conditions", "Clauses")}

_SC_FIELDS_CACHE: Optional[list] = None


def contract_fields() -> list[dict]:
    """The contract's own fields, read from the ERP's Sales Contract doctype - type, label, section, requirement.

    The tower renders the contract from this, so a Select gets the ERP's own choices (Sea / Air / ...) and a Link gets a
    picker of the records that exist, instead of a free text box that the ERP then refuses.
    """
    global _SC_FIELDS_CACHE
    if _SC_FIELDS_CACHE is not None:
        return _SC_FIELDS_CACHE
    be = _be()
    try:
        meta = be.meta("Sales Contract") or {}
    except Exception:
        meta = {}
    fields: list[dict] = []
    section = ""
    for f in meta.get("fields") or []:
        ft = f.get("fieldtype")
        if ft in ("Section Break", "Tab Break"):
            section = f.get("label") or ""
            continue
        if ft in ("Column Break",):
            continue
        name = f.get("fieldname")
        if name not in _SC_HEADER:
            continue
        opts = str(f.get("options") or "").split(chr(10)) if ft == "Select" else []
        fields.append({"name": name, "label": f.get("label") or name, "type": ft or "Data",
                       "reqd": bool(f.get("reqd")), "section": section, "options": opts,
                       "link": (_SC_LINKS.get(name) or (None, None))[0]})
    if not fields:                                   # ERP not reachable: still show the fields, as plain inputs
        fields = [{"name": k, "label": k.replace("_", " ").title(), "type": "Data", "reqd": False, "section": "",
                   "options": [], "link": (_SC_LINKS.get(k) or (None, None))[0]} for k in _SC_HEADER]
    _SC_FIELDS_CACHE = fields
    return fields


def contract_options(db) -> dict:
    """The records a Link field may point at, from the ERP itself (Incoterm, Payment Terms Template, ...)."""
    be = _be()
    out: dict = {}
    for field, (dt, _label) in _SC_LINKS.items():
        try:
            rows = be.get_list(dt, None, ["name"], limit=300) or []
            out[field] = [r.get("name") for r in rows if r.get("name")]
        except Exception:
            out[field] = []
    return out


def _check_links(db, sc: dict) -> list[str]:
    """A value on a Link field that is not a record in the ERP, in words that say what to do."""
    be = _be()
    problems: list[str] = []
    options: Optional[dict] = None
    for field, (dt, label) in _SC_LINKS.items():
        value = sc.get(field)
        if not value or not isinstance(value, str):
            continue
        try:
            if be.exists(dt, value):
                continue
        except Exception:
            continue                                 # cannot ask: let the ERP answer
        if options is None:
            options = contract_options(db)
        choices = options.get(field) or []
        if not choices:
            continue                                 # the ERP has no records of that kind: it is the ERP's call, not ours
        problems.append(f'{label} "{value}" is not in the ERP. Choose one of: {", ".join(choices[:12])}.')
    return problems


_SC_ITEM = ("colour", "qty", "rate", "ex_factory_date", "etd", "in_warehouse_date", "buyer_po_code", "line_remarks", "tolerance_pct")


def contract_update(db, me: dict, deal_id: int, draft: dict) -> dict:
    d = _get(db, deal_id)
    sc = json.loads(d.contract_draft or "{}")
    if not sc:
        raise DealError("Prepare the contract first.")
    for k in _SC_HEADER:
        if k in draft:
            sc[k] = draft[k]
    if "items" in draft:
        for i, e in enumerate(draft["items"] or []):
            if i < len(sc.get("items") or []):
                for k in _SC_ITEM:
                    if k in e:
                        sc["items"][i][k] = e[k]
    if "sizes" in draft:
        for i, e in enumerate(draft["sizes"] or []):
            if i < len(sc.get("sizes") or []) and "qty" in e:
                sc["sizes"][i]["qty"] = int(e["qty"] or 0)
    for it in sc.get("items") or []:
        it["amount"] = round(int(it.get("qty") or 0) * float(it.get("rate") or 0), 2)
    problems = _check_links(db, sc)
    if problems:
        raise DealError(" ".join(problems))
    d.contract_draft = json.dumps(sc, default=str)
    db.commit()
    return {"draft": sc, "readiness": _readiness(sc), "fields": contract_fields(), "options": contract_options(db)}


def contract_create(db, me: dict, deal_id: int, sign: bool = False) -> DealModel:
    d = _get(db, deal_id)
    sc = json.loads(d.contract_draft or "{}")
    if not sc:
        raise DealError("Prepare the contract first.")
    problems = _check_links(db, sc)
    if problems:
        raise DealError(" ".join(problems))
    name = live_contract(db, d)
    if not name:
        # The idempotency key must belong to THIS attempt, not to the deal: a deal whose contract was cancelled needs a
        # NEW document, and reusing the previous key made the pipeline answer with the first attempt's finished run -
        # the name of the cancelled contract. The tower then pointed the deal back at the dead document, and the next
        # Sign answered "Cannot edit cancelled document" (live, deal 2, 2026-11-07 13:37).
        made_seq = int(d.refs_dict().get("contract_made") or 0) + 1
        ins = _must(_ex(db, me, {"op": "insert", "doctype": "Sales Contract", "data": sc,
                                 "idem_key": _attempt_key(d, f"sc{made_seq}")}), "Contract not saved")
        name = _written_name(ins, "Sales Contract")
        if not name:
            raise DealError("The ERP accepted the Sales Contract but did not say which document it is. Open the ERP and "
                            "check before trying again.")
        guard = _be().get_doc("Sales Contract", name)
        if int(guard.get("docstatus") or 0) == 2:
            # never bind the deal to a cancelled document - say so, and leave the reference alone
            d.refs = json.dumps({k: v for k, v in d.refs_dict().items() if k != "sales_contract"})
            db.commit()
            raise DealError(f"The ERP answered with contract {name}, which is cancelled, so it cannot be used. Nothing "
                            f"was bound to it — press “Save to the ERP (draft)” again to make a fresh contract.")
        _set_refs(d, sales_contract=name, contract_made=made_seq)
        d.stage = "contract"
        _event(d, "erp", f"Sales Contract {name} saved as a draft.", me.get("email", ""), doc=["Sales Contract", name])
        db.commit()
    else:
        cur = _be().get_doc("Sales Contract", name)
        if int(cur.get("docstatus") or 0) == 0:
            data = {k: v for k, v in sc.items() if k in _SC_HEADER or k in ("items", "sizes")}
            res = _ex(db, me, {"op": "save", "doctype": "Sales Contract", "name": name, "data": data,
                               "modified": cur.get("modified")})
            if not res.get("ok") and "cannot edit cancelled" in str(res.get("error") or "").lower():
                # cancelled under us: follow the amendment (or make a new one) rather than echoing the ERP's refusal
                fresh_name = live_contract(db, d)
                if fresh_name and fresh_name != name:
                    name = fresh_name
                    cur = _be().get_doc("Sales Contract", name)
                    _must(_ex(db, me, {"op": "save", "doctype": "Sales Contract", "name": name, "data": data,
                                       "modified": cur.get("modified")}), "Contract not saved")
                else:
                    raise DealError("This contract was cancelled in the ERP a moment ago, so it cannot be edited. Press "
                                    "“Save to the ERP (draft)” again: the tower will make a fresh contract from this draft.")
            elif not res.get("ok"):
                _must(res, "Contract not saved")
    warns: list[str] = []
    if sign:
        problems = _readiness(sc)                     # the draft as the person sees it, before anything is signed
        if problems:
            raise DealError("Not ready to sign: " + "; ".join(problems[:8]) + ".")
        res = _ex(db, me, {"op": "submit", "doctype": "Sales Contract", "name": name,
                           "idem_key": f"{_attempt_key(d, 'sc-submit')}-{name}"})
        if not res.get("ok"):
            raw = _strip_html(res.get("error") or "The ERP refused to sign the contract.")
            if "cannot edit cancelled" in raw.lower():
                raise DealError("This contract was cancelled in the ERP, so it cannot be signed. Press “Save to the ERP "
                                "(draft)” first: the tower will follow the ERP's amendment or make a fresh contract.")
            raise DealError(raw)
        # The contract IS signed. What the ERP's own after-submit scripts could not write (a field the site forbids
        # after submission) is reported, not hidden - and never turned into a cancel.
        warns = [m.get("message") or "" for m in (res.get("messages") or []) if m.get("alert")]
        _event(d, "erp", f"Sales Contract {name} signed (submitted).", me.get("email", ""))
        for w in warns:
            _event(d, "erp", f"Signed, with a warning: {w}", me.get("email", ""))
    # what the tower shows from now on is what the ERP holds - every field of the paper, not just the ones the form sent
    sc = _draft_from_erp(_be(), name, {**sc, "_signed": True} if sign else sc)
    if warns:
        sc["_sign_warning"] = " ".join(warns)[:600]
    else:
        sc.pop("_sign_warning", None)
    d.contract_draft = json.dumps(sc, default=str)
    db.commit()
    return d


def _draft_from_erp(be, name: str, sc: dict) -> dict:
    """Read the contract back out of the ERP into the tower's draft, so every entry written there shows up here."""
    try:
        doc = be.get_doc("Sales Contract", name)
    except Exception:
        return sc
    signed = sc.get("_signed") or int(doc.get("docstatus") or 0) == 1
    fresh = {k: doc.get(k) for k in _SC_HEADER if doc.get(k) is not None}
    fresh["customer"] = doc.get("customer")
    fresh["currency"] = doc.get("currency")
    fresh["status"] = doc.get("status")
    fresh["docstatus"] = doc.get("docstatus")
    fresh["total_qty"] = doc.get("total_qty")
    fresh["total_amount"] = doc.get("total_amount")
    fresh["items"] = [{k: r.get(k) for k in _SC_ITEM + ("style_item", "style_no", "item", "amount", "variant")}
                      for r in (doc.get("items") or [])]
    fresh["sizes"] = [{k: r.get(k) for k in ("style_item", "colour", "size", "qty")} for r in (doc.get("sizes") or [])]
    fresh["_signed"] = bool(signed)
    return fresh


def contract_form(db, deal_id: int, refresh: bool = False) -> dict:
    """The contract draft, the checks before signing, and the ERP's own field list for the form.

    When the contract already exists in the ERP the draft is re-read from it first, so anything entered or changed **in the
    ERP** (an Incoterm fixed there, a date, a term) shows up in the tower the next time the contract is opened.
    """
    d = _get(db, deal_id)
    sc = json.loads(d.contract_draft or "{}")
    before = d.refs_dict().get("sales_contract") or ""
    name = live_contract(db, d)
    if refresh and sc and name:
        # asked for: take the ERP's own version of the paper (after a change made there), never on its own - the tower's
        # draft can be newer than the ERP's and silently overwriting it loses work
        sc = _draft_from_erp(_be(), name, sc)
        d.contract_draft = json.dumps(sc, default=str)
        db.commit()
    readiness = (_readiness(sc) + _check_links(db, sc)) if sc else []
    out = {"draft": sc, "readiness": readiness, "fields": contract_fields(), "options": contract_options(db),
           "contract": name}
    if before and name and name != before:
        out["notice"] = (f"Contract {before} was cancelled in the ERP, so it cannot be edited or signed. The deal now "
                         f"works on its amendment {name} — everything below is saved onto that document.")
    elif before and not name:
        out["notice"] = (f"Contract {before} was cancelled in the ERP and no amendment exists. Press “Save to the ERP "
                         f"(draft)” to make a fresh contract from this draft — nothing here is lost.")
    return out


def make_order(db, me: dict, deal_id: int) -> DealModel:
    d = _get(db, deal_id)
    name = live_contract(db, d)
    if not name:
        raise DealError("Create and sign the contract first.")
    so_ref = d.refs_dict().get("sales_order")
    if so_ref:
        # a Sales Order cancelled in the ERP is not an order any more: let the deal make a live one instead of
        # showing a dead document for ever
        try:
            if int(_be().get_doc("Sales Order", so_ref).get("docstatus") or 0) == 2:
                r = d.refs_dict()
                r.pop("sales_order", None)
                d.refs = json.dumps(r)
                _event(d, "erp", f"Sales Order {so_ref} was cancelled in the ERP; it is no longer this deal's order.")
                db.commit()
            else:
                return d
        except Exception:
            return d
    made = _must(_ex(db, me, {"op": "api", "method": "arinox_sales_contract_make_sales_order", "params": {"source_name": name}}), "Sales Order not prepared")
    so = clean(made["result"])
    so["doctype"] = "Sales Order"
    # A SIZE WITH NO PIECES IS NOT AN ORDER LINE (2026-11-09). The contract keeps every size the buyer listed, and a
    # buyer legitimately orders none of some of them (XXS / XXL at zero), but the ERP refuses the whole document with
    # *"Row #1: Quantity for Item ... cannot be zero"* - which is what "I cannot create a Sales Order" was. The rows are
    # dropped here, whatever the ERP's own make-Sales-Order script does, and the timeline says which sizes went.
    rows = [r for r in (so.get("items") or []) if _qty(r.get("qty")) > 0]
    dropped = [r for r in (so.get("items") or []) if _qty(r.get("qty")) <= 0]
    if not rows:
        raise DealError("No size on this contract has a quantity, so there is nothing to order. Enter the pieces for at "
                        "least one size on the contract, then make the Sales Order.")
    so["items"] = rows
    ins = _must(_ex(db, me, {"op": "insert", "doctype": "Sales Order", "data": so,
                             "idem_key": _attempt_key(d, f"so-{name}")}), "Sales Order not saved")
    so_name = _written_name(ins, "Sales Order")
    if not so_name:
        raise DealError("The ERP accepted the Sales Order but did not say which document it is. Open the ERP and check "
                        "before trying again.")
    _set_refs(d, sales_order=so_name)
    d.stage = "order"
    _event(d, "erp", f"Sales Order {so_name} created as a draft — submit it in Records when production is ready to plan.",
           me.get("email", ""), doc=["Sales Order", so_name])
    if dropped:
        _event(d, "erp", "Sizes with no pieces are not on the Sales Order: "
               + ", ".join(f"{(r.get('apparel_size') or r.get('size') or '?')}"
                           f" ({r.get('apparel_colour') or r.get('colour') or '-'})" for r in dropped) + ".",
               me.get("email", ""), doc=["Sales Order", so_name])
    else:
        # the ERP's own script may already have dropped the empty sizes, so the payload cannot say which they were:
        # the contract can. One read; a failure simply means no note, never a failed order.
        _note_empty_sizes(db, d, name, me, so_name)
    db.commit()
    return d


def _note_empty_sizes(db, d: DealModel, contract: str, me: dict, so_name: str) -> None:
    """Put the sizes that were left off the Sales Order on the timeline, read from the contract."""
    rows: list = []
    try:
        rows = (_be().get_doc("Sales Contract", contract) or {}).get("sizes") or []
    except Exception:
        try:
            rows = (json.loads(d.contract_draft or "{}") or {}).get("sizes") or []
        except (ValueError, TypeError):
            rows = []
    empty = [(r.get("size"), r.get("colour")) for r in rows if _qty(r.get("qty")) <= 0]
    if not empty:
        return
    _event(d, "erp", "Sizes with no pieces are not on the Sales Order: "
           + ", ".join(f"{size or '?'} ({colour or '-'})" for size, colour in empty) + ".",
           me.get("email", ""), doc=["Sales Order", so_name])


def _qty(value) -> float:
    """A quantity as a number, whatever the ERP sent back (int, float, "12", "12.0", None)."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


# ───────────────────────── after the order: what the ERP says ─────────────────────────

_DOC_STATUS = {0: "draft", 1: "submitted", 2: "cancelled"}


#: The ERP record each step of the deal is *about*, in the order to look for it. The keys are the deal page's own step
#: keys (``STEPS`` in ``app/DealPage.tsx``), so a step button and its ERP page cannot drift apart.
_STEP_DOCS = {
    "inquiry":  (("opportunity", "Opportunity"), ("tech_pack", "Tech Pack")),
    "costing":  (("cost_sheet", "Cost Sheet"), ("tech_pack", "Tech Pack")),
    "quote":    (("quotation", "Quotation"), ("price_negotiation", "Price Negotiation")),
    "contract": (("sales_contract", "Sales Contract"),),
    "order":    (("sales_order", "Sales Order"),),
    "track":    (("sales_order", "Sales Order"),),
}
#: deal stage -> the step whose page it is. A deal that has been signed is about its contract; an order, its order.
_STAGE_STEP = {"inquiry": "inquiry", "costing": "costing", "quoted": "quote", "negotiating": "quote",
               "accepted": "contract", "contract": "contract", "order": "order", "lost": "quote"}


#: what the button says when the record does not exist yet and the link opens the DocType's list instead
_STEP_LIST_LABEL = {"Cost Sheet": "cost sheet", "Tech Pack": "tech pack", "Sales Contract": "sales contract",
                    "Sales Order": "sales order", "Quotation": "quotation", "Opportunity": "opportunity",
                    "Price Negotiation": "price negotiation"}


def _erp_page(have: dict, step: str) -> dict:
    """The ERP page a step is about: the record if the deal has one, else that DocType's list.

    ``have`` maps a refs key (``opportunity``, ``cost_sheet`` ...) to ``(doctype, name, url)`` as resolved by
    :func:`erp_status`. The list fallback is the point: before the Sales Order exists the button must still land on the
    Sales Orders, not on the ERP's front page (that was the 2026-11-09 report).
    """
    for key, dt in _STEP_DOCS.get(step, ()):
        doctype, name, url = have.get(key, (dt, "", ""))
        if url:
            return {"step": step, "doctype": doctype, "name": name, "url": url,
                    "label": f"Open {doctype} {name}" if name else f"Open the {_STEP_LIST_LABEL.get(doctype, doctype)} list"}
    for key, dt in _STEP_DOCS.get(step, ()):
        url = _list_url(dt)
        if url:
            return {"step": step, "doctype": dt, "name": "", "url": url,
                    "label": f"Open the {_STEP_LIST_LABEL.get(dt, dt)} list"}
    return {}


def _list_url(doctype: str) -> str:
    """The ERP's list page for a DocType (built by ``erp``, never here)."""
    import erp as _erp
    return _erp.list_url(doctype)


def _doc_url(doctype: str, name: str) -> str:
    """The ERP page for one document (a plain link - confirming a document is an ERP action, not a tower one)."""
    import erp as _erp
    return _erp.doc_url(doctype, name)


def erp_status(d: DealModel, db=None) -> dict:
    """Light, live read of every ERP document the deal made. A failure is reported per document, never raised.

    Each entry carries ``url`` - the ERP's own page for that document - because confirming a Tech Pack or a Cost Sheet
    is an ERP action: the tower links to it rather than pretending to be the ERP's approval screen.

    ``db`` is optional and only used to **bring the deal back in line with the ERP**: if the Tech Pack or the Cost Sheet
    was submitted (or cancelled) in the ERP, the style's status is updated here, so after a person confirms in the ERP
    and comes back, the next step is right.
    """
    be = _be()
    import erp as _erp
    out = {"base_url": _erp.desk_url()}
    #: refs key -> (doctype, name, url) of the record this deal actually has in the ERP. Filled as the documents are
    #: read, then handed to :func:`_erp_page` so each step can name its own page.
    have: dict = {}
    fields = {"Opportunity": ["status"], "Price Negotiation": ["status", "total_value"], "Quotation": ["status", "grand_total", "docstatus"],
              "Sales Contract": ["status", "docstatus", "total_qty", "total_amount"],
              "Sales Order": ["status", "docstatus", "per_delivered", "per_billed", "grand_total", "delivery_date"]}
    refs = d.refs_dict()
    for dt, key in (("Opportunity", "opportunity"), ("Price Negotiation", "price_negotiation"), ("Quotation", "quotation"),
                    ("Sales Contract", "sales_contract"), ("Sales Order", "sales_order")):
        if refs.get(key):
            try:
                rows = be.get_list(dt, [["name", "=", refs[key]]], ["name"] + fields[dt], limit=1)
                out[key] = rows[0] if rows else {"missing": True}
                out[key]["url"] = "" if out[key].get("missing") else _doc_url(dt, refs[key])
                if out[key]["url"]:
                    have[key] = (dt, refs[key], out[key]["url"])
            except Exception as e:
                out[key] = {"error": str(e)[:120]}
    changed = False
    styles = d.styles_list()
    for st in styles:
        for key, dt in (("tech_pack", "Tech Pack"), ("cost_sheet", "Cost Sheet")):
            if not st.get(key):
                continue
            try:
                rows = be.get_list(dt, [["name", "=", st[key]]],
                                   ["name", "docstatus"] + (["quoted_price", "margin_pct"] if dt == "Cost Sheet" else ["status"]), limit=1)
                row = rows[0] if rows else {"missing": True}
                row["url"] = "" if row.get("missing") else _doc_url(dt, st[key])
                out[f"{key}:{st[key]}"] = row
                if row["url"] and key not in have:      # the first style's document is the one to offer
                    have[key] = (dt, st[key], row["url"])
                if row.get("missing") or "docstatus" not in row:
                    continue
                now = _DOC_STATUS.get(int(row.get("docstatus") or 0), "draft")
                field = "cost_status" if dt == "Cost Sheet" else "tech_pack_status"
                if st.get(field) != now:
                    st[field] = now                       # the ERP is the truth about submitted/cancelled
                    changed = True
            except Exception as e:
                out[f"{key}:{st[key]}"] = {"error": str(e)[:120]}
    if changed and db is not None:
        try:
            _save_styles(d, styles)
            db.commit()
        except Exception:
            db.rollback()
    so = refs.get("sales_order")
    if so:
        follow = {}
        for dt, f in (("Production Card", "sales_order"), ("Order TNA", "sales_order"), ("Fabric Requisition", "sales_order"),
                      ("Packing List", "sales_order"), ("Sales Invoice", "apparel_sales_contract")):
            try:
                val = refs.get("sales_contract") if f == "apparel_sales_contract" else so
                follow[dt] = be.count(dt, [[f, "=", val]])
            except Exception:
                follow[dt] = None
        out["follow_on"] = follow
    # Every step's own ERP page, plus the one the deal is on now: the "open the ERP" buttons read these instead of
    # falling back to the ERP front page (2026-11-09). Resolved here, once, for the whole deal.
    out["by_step"] = {step: page for step in _STEP_DOCS if (page := _erp_page(have, step))}
    out["focus"] = out["by_step"].get(_STAGE_STEP.get(d.stage or "", ""), {})
    return out


def next_action(d: DealModel) -> dict:
    """The one thing to do next on this deal, in words."""
    styles = live(d.styles_list())
    refs = d.refs_dict()
    if d.stage == "lost":
        return {"step": "done", "text": "Lost. Nothing to do."}
    if not d.customer:
        return {"step": "inquiry", "text": "Pick or add the customer."}
    if not refs.get("opportunity"):
        return {"step": "inquiry", "text": "Check the styles and BOM, then send the inquiry to the ERP."}
    uncosted = [s["style_no"] for s in styles if s.get("cost_status") != "submitted"]
    if uncosted:
        return {"step": "costing", "text": "Cost and submit: " + ", ".join(uncosted) + "."}
    if not d.quote_sent_at:
        return {"step": "quote", "text": "Send the quote to the buyer."}
    att = json.loads(d.attention or "null")
    if att and att.get("kind") == "buyer_replied":
        return {"step": "reply", "text": "The buyer replied. Record their answer."}
    if [s for s in styles if s.get("status") != "agreed"]:
        return {"step": "reply", "text": "Waiting for the buyer. Record their answer when it comes."}
    if not refs.get("sales_contract"):
        return {"step": "contract", "text": "Prepare the sales contract from the agreed prices."}
    sc = json.loads(d.contract_draft or "{}")
    if not sc.get("_signed"):
        return {"step": "contract", "text": "Complete and sign the contract."}
    if not refs.get("sales_order"):
        return {"step": "order", "text": "Make the Sales Order."}
    return {"step": "after", "text": "In production planning. Follow it in Orders and the T&A calendar."}


# ───────────────────────── replies on a deal's thread ─────────────────────────

_ACCEPT = re.compile(r"\b(accept(ed)?|approved?|confirm(ed)?|go ahead|agreed?|ok(ay)? with|proceed|fine with|works for us|happy with)\b", re.I)
_PRICE = re.compile(r"(?:usd|us\$|\$)\s?(\d{1,4}(?:\.\d{1,3})?)|(\d{1,4}\.\d{2})\s?(?:usd|\$|/pc|per piece)", re.I)


def reply_intent(subject: str, body: str, attachments: list) -> dict:
    fresh = inbound.strip_quoted(body or "")
    names = [(a.get("filename") or "") for a in attachments or []]
    cls = inbound.classify(subject, body, attachments)
    prices = [float(a or b) for a, b in _PRICE.findall(fresh)][:10]
    if cls["classification"] == "new_order":
        return {"intent": "po", "text": "The buyer sent purchase orders" + (f" ({', '.join(n for n in names if 'po' in n.lower())[:120]})" if names else "") + ".", "prices": prices}
    accepts = _ACCEPT.search(fresh) and not re.search(r"\b(not|can't|cannot|don't)\s+(accept|agree|approve|proceed)", fresh, re.I)
    if accepts and prices:
        return {"intent": "counter", "text": "The buyer accepts in part and asks for " + ", ".join(f"{p:g}" for p in prices) + ". Read the mail for which style.", "prices": prices}
    if accepts:
        return {"intent": "accept", "text": "The buyer seems to accept.", "prices": prices}
    if prices:
        return {"intent": "counter", "text": "The buyer mentions a price: " + ", ".join(f"{p:g}" for p in prices) + ".", "prices": prices}
    return {"intent": "question", "text": "The buyer wrote back.", "prices": []}


def notice_replies(db, since_id: int) -> int:
    """New buyer mail in a deal's thread marks the deal: "the buyer replied", with what they seem to say."""
    n = 0
    rows = db.query(MailMessageModel).filter(MailMessageModel.id > int(since_id or 0), MailMessageModel.direction != "out",
                                             MailMessageModel.thread_key.isnot(None)).all()
    for m in rows:
        d = db.query(DealModel).filter(DealModel.thread_key == m.thread_key).first()
        if not d or d.stage in ("lost",):
            continue
        if d.contact_email and (m.from_addr or "").lower() != d.contact_email.lower() and m.status == "ignored":
            continue
        m.deal_id = d.id
        atts = json.loads(m.attachments or "[]")
        it = reply_intent(m.subject or "", m.body_text or "", atts)
        d.buyer_reply_at = datetime.now()
        d.attention = json.dumps({"kind": "buyer_replied", "mail_id": m.id, "at": m.received_at, **it})
        _event(d, "mail", f"Buyer replied: {it['text']}", m.from_addr or "", mail_id=m.id)
        n += 1
    db.commit()
    return n


# ───────────────────────── lists & dashboard ─────────────────────────

def summary(d: DealModel) -> dict:
    x = d.to_dict()
    x.pop("events", None)
    x.pop("contract_draft", None)
    x["next"] = next_action(d)
    x["styles"] = [{k: s.get(k) for k in ("key", "style_no", "style_name", "qty", "status", "cost_status", "offer_price", "agreed_price")}
                   for s in d.styles_list()]
    return x


def list_deals(db, stage: str = "", q: str = "") -> list[dict]:
    qs = db.query(DealModel)
    if stage == "open":
        qs = qs.filter(DealModel.stage.notin_(["lost", "order"]))
    elif stage:
        qs = qs.filter(DealModel.stage == stage)
    rows = qs.order_by(DealModel.updated_at.desc()).limit(300).all()
    out = [summary(d) for d in rows]
    if q:
        ql = q.lower()
        out = [x for x in out if ql in json.dumps([x["title"], x["customer_name"], [s["style_no"] for s in x["styles"]]]).lower()]
    return out


def dashboard(db) -> dict:
    deals = db.query(DealModel).all()
    by_stage = {s: {"count": 0, "value": 0.0, "qty": 0} for s in STAGES + ["lost"]}
    waiting, attention, aging = [], [], []
    now = datetime.now()
    for d in deals:
        x = d.to_dict()
        b = by_stage.setdefault(d.stage, {"count": 0, "value": 0.0, "qty": 0})
        b["count"] += 1
        b["value"] += x["total_value"]
        b["qty"] += x["total_qty"]
        att = json.loads(d.attention or "null")
        if att:
            attention.append({"id": d.id, "title": d.title, "customer": d.customer_name or d.customer, "text": att.get("text"), "kind": att.get("kind")})
        if d.stage in ("quoted", "negotiating") and d.quote_sent_at:
            days = (now - d.quote_sent_at).days
            waiting.append({"id": d.id, "title": d.title, "customer": d.customer_name or d.customer, "days": days, "value": x["total_value"]})
        if d.stage in ("inquiry", "costing") and d.created_at:
            aging.append({"id": d.id, "title": d.title, "customer": d.customer_name or d.customer, "days": (now - d.created_at).days, "stage": d.stage})
    won = by_stage["contract"]["count"] + by_stage["order"]["count"]
    decided = won + by_stage["lost"]["count"]
    by_customer: dict[str, dict] = {}
    for d in deals:
        if d.stage == "lost":
            continue
        k = d.customer_name or d.customer or "(no customer)"
        c = by_customer.setdefault(k, {"customer": k, "deals": 0, "value": 0.0})
        c["deals"] += 1
        c["value"] += d.to_dict()["total_value"]
    return {"stages": [{"stage": s, "label": STAGE_LABEL[s], **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in by_stage[s].items()}}
                       for s in STAGES + ["lost"]],
            "open": sum(by_stage[s]["count"] for s in ("inquiry", "costing", "quoted", "negotiating", "accepted")),
            "open_value": round(sum(by_stage[s]["value"] for s in ("quoted", "negotiating", "accepted")), 2),
            "win_rate": round(won / decided * 100) if decided else None,
            "waiting_on_buyer": sorted(waiting, key=lambda r: -r["days"])[:8],
            "needs_us": attention[:10], "aging": sorted(aging, key=lambda r: -r["days"])[:8],
            "top_customers": sorted(by_customer.values(), key=lambda r: -r["value"])[:6]}
