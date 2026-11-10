"""The functions the new workspace calls: inbox (threads), deals (inquiry → order), customers, dashboard.

Calling convention ``fn(db, **params) -> dict``. Every function resolves the signed-in caller first
(``cx_users.require`` through ``cortex_api.guarded``); a client-supplied actor is never trusted. ERP writes happen only
in ``deals.py`` through ``pipeline.execute``.
"""

from __future__ import annotations

import base64
from typing import Callable

import cortex_api
import deals
import guardrails
import mailbox
import ship_track
from deals import DealError
from models import MailAttachmentModel


def guarded(fn: Callable) -> Callable:
    inner = cortex_api.guarded(fn)

    def wrapper(db, **kwargs):
        try:
            return inner(db, **kwargs)
        except DealError as e:
            db.rollback()
            return {"ok": False, "error": str(e)}
        except (ValueError, TypeError) as e:
            db.rollback()
            return {"ok": False, "error": f"That value was not understood: {e}"}
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _writer(me: dict):
    if not set(me["roles"]) & set(guardrails.WRITE["enquire"] + guardrails.ALL_POWER + ["Costing"]):
        raise guardrails.Denied("Your role can read deals but not change them. Ask a merchandiser or a manager.")


# ───────────────────────── inbox ─────────────────────────

@guarded
def inbox_threads(db, me, folder: str = "all", q: str = "", limit: int = 60, offset: int = 0, **_):
    """Conversations, newest first, with a label (Inquiry, Order …), unread / needs-reply flags and the deal they hold."""
    return mailbox.list_threads(db, folder or "all", q or "", int(limit or 60), int(offset or 0))


@guarded
def inbox_thread(db, me, key: str = "", **_):
    """One conversation: every message in and out, attachments, the deal, and who the buyer is."""
    t = mailbox.get_thread(db, key)
    if t.get("ok") and not t.get("deal"):
        try:
            t["customer_match"] = deals.match_customer(db, t["party"]["email"], t["party"]["name"], t["subject"])
        except Exception:
            t["customer_match"] = {}
    return t


@guarded
def inbox_reply(db, me, key: str = "", body: str = "", to: str = "", cc: str = "", **_):
    """Send a reply in the conversation (same subject, In-Reply-To / References), so the buyer's answer comes back here."""
    _writer(me)
    deal = None
    from models_deal import DealModel
    d = db.query(DealModel).filter(DealModel.thread_key == key).first()
    if d:
        deal = d.id
    res = mailbox.send_in_thread(db, me, key, body, to=to, cc=cc, deal_id=deal)
    if res.get("ok") and d:
        deals._event(d, "mail", f"Reply sent to {res['to']}.", me.get("email", ""))
        db.commit()
    return res


@guarded
def inbox_sync(db, me, **_):
    """Read new mail now (inbox and Gmail's Sent folder), thread it, and flag deals the buyer answered."""
    return mailbox.sync(db, me)


@guarded
def inbox_label(db, me, key: str = "", label: str = "", **_):
    """Correct a conversation's label (e.g. mark it an Inquiry). The correction sticks."""
    return mailbox.set_label(db, key, label)


@guarded
def inbox_link_customer(db, me, key: str = "", customer: str = "", **_):
    """Remember that the buyer of this conversation is ``customer``: a deal started from it (and later mail from the same
    address) is linked to that customer without asking again."""
    _writer(me)
    t = mailbox.get_thread(db, key, mark_read=False)
    email = ((t.get("party") or {}).get("email") or "").lower() if t.get("ok") else ""
    if not email or not customer:
        return {"ok": False, "error": "This conversation has no buyer address to link."}
    deals._kv_set(db, f"email_customer:{email}", customer)
    return {"ok": True, "email": email, "customer": customer}


@guarded
def inbox_archive(db, me, key: str = "", archived: bool = True, **_):
    return mailbox.archive(db, key, bool(archived))


@guarded
def inbox_attachment(db, me, attachment_id: int = 0, **_):
    """One attachment's bytes (base64), to open or download in the browser."""
    a = db.query(MailAttachmentModel).get(int(attachment_id or 0))
    if not a:
        return {"ok": False, "error": "Attachment not found."}
    data = deals._load_bytes(a)
    if not data:
        return {"ok": False, "error": "The file is no longer stored. Re-sync the mail to fetch it again."}
    if len(data) > 12 * 1024 * 1024:
        return {"ok": False, "error": "The file is too large to open here."}
    return {"ok": True, "filename": a.filename, "mime": a.mime or "application/octet-stream", "data": base64.b64encode(data).decode()}


# ───────────────────────── customers ─────────────────────────

@guarded
def customer_list(db, me, q: str = "", limit: int = 50, **_):
    return {"ok": True, "customers": deals.list_customers(q or "", int(limit or 50))}


@guarded
def customer_create(db, me, customer_name: str = "", email: str = "", currency: str = "", country: str = "",
                    customer_group: str = "", territory: str = "", contact_name: str = "", deal_id: int = 0, **_):
    """Add a customer to the ERP (and a contact with the buyer's e-mail), optionally linking it to a deal."""
    _writer(me)
    res = deals.create_customer(db, me, customer_name, email, currency, country, customer_group, territory, contact_name)
    if deal_id:
        d = deals.update(db, me, int(deal_id), {"customer": res["customer"], "customer_name": customer_name})
        deals._event(d, "customer", f"Customer {res['customer']} {'linked' if res.get('existing') else 'added to the ERP'}.", me.get("email", ""))
        db.commit()
    return {"ok": True, **res}


@guarded
def customer_overview(db, me, customer: str = "", **_):
    """A customer's deals in the tower and their orders in the ERP."""
    be = deals._be()
    out = {"ok": True, "customer": customer, "deals": [x for x in deals.list_deals(db) if x["customer"] == customer]}
    try:
        out["orders"] = be.get_list("Sales Order", [["customer", "=", customer]], ["name", "status", "grand_total", "currency", "delivery_date", "docstatus"],
                                    order_by="modified desc", limit=30)
    except Exception as e:
        out["orders"], out["orders_error"] = [], str(e)[:160]
    try:
        out["contracts"] = be.get_list("Sales Contract", [["customer", "=", customer]], ["name", "status", "total_amount", "contract_date", "docstatus"],
                                       order_by="modified desc", limit=30)
    except Exception:
        out["contracts"] = []
    return out


# ───────────────────────── deals ─────────────────────────

def _full(db, d) -> dict:
    x = d.to_dict()
    x["next"] = deals.next_action(d)
    x["stages"] = [{"key": s, "label": deals.STAGE_LABEL[s]} for s in deals.STAGES]
    return x


@guarded
def deal_list(db, me, stage: str = "", q: str = "", **_):
    return {"ok": True, "deals": deals.list_deals(db, stage or "", q or "")}


@guarded
def deal_get(db, me, deal_id: int = 0, erp: bool = False, **_):
    d = deals._get(db, deal_id)
    out = {"ok": True, "deal": _full(db, d), "product_types": deals.product_types()}
    if erp:
        out["erp"] = deals.erp_status(d, db)
    return out


@guarded
def deal_from_thread(db, me, key: str = "", **_):
    """Start a deal from an inquiry conversation: styles, quantities and each style's BOM are read from the mail."""
    _writer(me)
    d = deals.from_thread(db, me, key)
    return {"ok": True, "deal": _full(db, d)}


@guarded
def deal_create(db, me, customer: str = "", title: str = "", contact_email: str = "", **_):
    """A deal typed in by hand (an inquiry that came by phone or WhatsApp)."""
    _writer(me)
    return {"ok": True, "deal": _full(db, deals.create_manual(db, me, customer, title, contact_email))}


@guarded
def deal_update(db, me, deal_id: int = 0, patch: dict | None = None, **_):
    """Edit the deal's details and its styles (number, name, colour, qty, product type, BOM lines). No price is required."""
    _writer(me)
    return {"ok": True, "deal": _full(db, deals.update(db, me, deal_id, patch or {}))}


# ───────────────────────── BOM: three ways in ─────────────────────────
# An inquiry often arrives without a BOM a machine can read (a photo, a scan, a sheet sent later, or nothing at
# all). These let a person put lines on a style anyway: upload a sheet, take one of the mail's own attachments,
# or read the BOM the ERP already holds for the style's Item.

@guarded
def deal_documents(db, me, deal_id: int = 0, **_):
    """What the conversation carries, and what happened to each file. Params: `deal_id`.

    A mail is not "read" just because it has attachments: this says which file was opened, which could not be, and why
    (too large, a scan, no reader) - so a document is never lost without a trace.
    """
    d = deals._get(db, int(deal_id or 0))
    out = []
    for x in deals.thread_documents(db, d):
        out.append({"attachment_id": x["attachment_id"], "filename": x["filename"], "mime": x["mime"],
                    "size_mb": round((x["size"] or 0) / 1048576, 1), "readable": bool(x["data"]),
                    "parsed": x["ok"], "error": x["error"]})
    return {"ok": True, "documents": out}


@guarded
def deal_erp_setup(db, me, deal_id: int = 0, **_):
    """Check (and fix) the ERP master data the Arinox scripts need before a document can be made.

    On this site the **Apparel Settings** still pointed at the previous company's warehouses (`… - GGI`), so the first
    Quotation refused with *"Could not find Finished Goods Warehouse …"*, and every **Product Type** had no Item Group, so
    the style Item could not be made and the contract stopped. Both are defaults, not business decisions: this fills them
    from records that already exist (a warehouse is made under the company's own abbreviation; the style Item Group is
    taken from the ERP's Item Groups) and reports anything it will not invent.
    Returns `{ok, created, set, unresolved, item_groups}`.
    """
    _writer(me)
    rep = deals.erp_setup(db, me)
    groups = {}
    try:
        be = deals._be()
        for pt in (be.get_list("Product Type", None, ["name", "item_group"], limit=60) or []):
            if not pt.get("item_group"):
                got = deals._ensure_item_group(db, me, be, {}, pt.get("name"))
                if got:
                    groups[pt["name"]] = got
    except Exception as e:
        rep.setdefault("unresolved", []).append(str(e)[:120])
    return {"ok": True, "created": rep.get("created") or [], "set": rep.get("set") or {},
            "unresolved": rep.get("unresolved") or [], "item_groups": groups}


@guarded
def deal_read_documents(db, me, deal_id: int = 0, **_):
    """Read every document on the conversation again (Tech Pack AND BOM). Params: `deal_id`."""
    _writer(me)
    res = deals.read_documents_again(db, me, int(deal_id or 0))
    return {"ok": True, "documents": res["documents"], "skipped": res["skipped"], "failed": res.get("failed") or [],
            "reads": res.get("reads") or [], "bom_lines": res["bom_lines"], "spec_styles": res["spec_styles"],
            "deal": _full(db, res["deal"])}


@guarded
def deal_bom_upload(db, me, deal_id: int = 0, style_key: str = "", filename: str = "bom.xlsx", data: str = "", **_):
    """Read an uploaded BOM sheet (xlsx / xls / csv, base64 in `data`) and put its lines on the style."""
    _writer(me)
    raw = base64.b64decode((data or "").split(",", 1)[-1] if data and data.startswith("data:") else (data or ""), validate=False)
    d, rep = deals.bom_from_bytes(db, me, deal_id, style_key, filename or "bom.xlsx", raw)
    return {"ok": True, "deal": _full(db, d), "bom": rep}


@guarded
def deal_bom_from_mail(db, me, deal_id: int = 0, style_key: str = "", attachment_id: int = 0, **_):
    """Read one of the deal's mail attachments (spreadsheet) and put its lines on the style."""
    _writer(me)
    d, rep = deals.bom_from_mail(db, me, deal_id, style_key, attachment_id)
    return {"ok": True, "deal": _full(db, d), "bom": rep}


@guarded
def deal_bom_ai(db, me, deal_id: int = 0, style_key: str = "", filename: str = "bom.xlsx", data: str = "", **_):
    """Read the uploaded sheet with the KOGO model instead of the fixed column map, and put the rows on the style.

    The sheet reaches the model as plain text (no interpretation), and its JSON answer is validated here: only the
    nine material types, numbers for the quantities, and nothing invented. Use this when a buyer's layout defeats the
    deterministic reader; the fixed reader stays the fast default.
    """
    _writer(me)
    raw = base64.b64decode((data or "").split(",", 1)[-1] if data and data.startswith("data:") else (data or ""), validate=False)
    d, rep = deals.bom_from_ai(db, me, deal_id, style_key, filename or "bom.xlsx", raw)
    return {"ok": True, "deal": _full(db, d), "bom": rep}


@guarded
def deal_bom_paste(db, me, deal_id: int = 0, style_key: str = "", rows=None, source: str = "", **_):
    """Rows typed in, or the model's JSON pasted from any chat window, onto the style.

    `rows` is either a list of line objects or a string holding JSON. Params: `deal_id`, `style_key`, `rows`,
    `source` (what to call it on the timeline). Returns `{ok, deal, bom}`.
    """
    _writer(me)
    d, rep = deals.bom_from_rows(db, me, deal_id, style_key, rows if rows is not None else [], source or "pasted lines")
    return {"ok": True, "deal": _full(db, d), "bom": rep}


@guarded
def deal_bom_apply(db, me, deal_id: int = 0, style_key: str = "", **_):
    """Send the style's BOM lines to the ERP: the Tech Pack's materials, then a rebuilt draft Cost Sheet.

    Use it after editing lines by hand on a style that is already registered. A submitted cost sheet is never
    touched; the answer says which document needs amending instead. Returns `{ok, deal, erp: [sentences]}`.
    """
    _writer(me)
    d = deals._get(db, deal_id)
    notes = deals.apply_bom_to_erp(db, me, d, style_key)
    return {"ok": True, "deal": _full(db, deals._get(db, deal_id)), "erp": notes}


@guarded
def deal_bom_from_erp(db, me, deal_id: int = 0, style_key: str = "", **_):
    """Read the ERP's own BOM for the style's Item (the default active one) and put its lines on the style."""
    _writer(me)
    d, rep = deals.bom_from_erp(db, me, deal_id, style_key)
    return {"ok": True, "deal": _full(db, d), "bom": rep}


@guarded
def deal_bom_sources(db, me, deal_id: int = 0, **_):
    """What could feed a BOM here: the spreadsheets attached to this deal's mail (id + filename)."""
    d = deals._get(db, deal_id)
    return {"ok": True, "attachments": deals.bom_attachments(db, d)}


@guarded
def deal_register(db, me, deal_id: int = 0, **_):
    """Send the inquiry to the ERP: an Opportunity and one Tech Pack (with the buyer's BOM) per style."""
    _writer(me)
    return {"ok": True, "deal": _full(db, deals.register(db, me, deal_id))}


@guarded
def deal_cost_open(db, me, deal_id: int = 0, style_key: str = "", **_):
    """Open (or start) the Cost Sheet of one style. Materials come from the Tech Pack with the ERP's buying rates."""
    _writer(me)
    return {"ok": True, **deals.cost_open(db, me, deal_id, style_key)}


@guarded
def deal_cost_save(db, me, deal_id: int = 0, style_key: str = "", materials: list | None = None, charges: list | None = None,
                   quoted_price=None, preview: bool = False, extra: dict | None = None, **_):
    """Save costing edits; ``preview`` runs the ERP's costing rules and returns the price without saving."""
    _writer(me)
    return {"ok": True, **deals.cost_save(db, me, deal_id, style_key, materials, charges, quoted_price, bool(preview), extra)}


@guarded
def deal_cost_sheet(db, me, deal_id: int = 0, style_key: str = "", **_):
    """The style's **costing sheet** - the app's own document, not a file.

    It is seeded from the standard template the first time it is opened (materials from the buyer's BOM, the processing
    charges, the percentage expenses, profit), so there is never an empty page. The totals are always freshly computed by
    the sheet's own rules. Params: `deal_id`, `style_key`.
    Returns `{ok, sheet, lines, totals, deal}`.
    """
    import costing_sheet as cs
    d = deals._get(db, int(deal_id or 0))
    s = deals._style(d.styles_list(), style_key)
    sheet, lines, totals = cs.open_sheet(db, d, s)
    return {"ok": True, "sheet": sheet.to_dict(), "lines": [ln.to_dict() for ln in lines], "totals": totals,
            "deal": _full(db, d)}


@guarded
def cost_sheet_list(db, me, **_):
    """Every style of every deal with its costing sheet - what the Costing page lists.

    One row per style (dropped styles left out): the deal and buyer, the style, the quantity, and if the style has a sheet
    already its FOB per piece, order value, when it was last touched and whether it has been transferred to the ERP.
    A style with no sheet yet is listed too, so it can be started from the page. Params: none.
    Returns `{ok, sheets}`.
    """
    import costing_sheet as cs
    return {"ok": True, "sheets": cs.list_sheets(db)}


@guarded
def deal_cost_sheet_save(db, me, deal_id: int = 0, style_key: str = "", header: dict | None = None,
                         lines: list | None = None, **_):
    """Save what a person typed into the costing sheet and return the recomputed totals.

    `lines` is the whole sheet as shown (a line the caller leaves out is deleted); each line carries `id` when it already
    exists. Nothing is written to the ERP by this call - `deal_cost_sheet_transfer` does that.
    Params: `deal_id`, `style_key`, `header` (`order_qty`, `pcs_per_carton`, `profit_pct`, `currency`, `fob_port`,
    `version`, `note`, `buyer`, `season`, `factory`, `costing_date`, `vnd_per_usd`, `signoffs`), `lines`.
    """
    _writer(me)
    import costing_sheet as cs
    d = deals._get(db, int(deal_id or 0))
    s = deals._style(d.styles_list(), style_key)
    sheet, lines_now, totals = cs.save_sheet(db, d, s, header or {}, lines if lines is not None else None)
    return {"ok": True, "sheet": sheet.to_dict(), "lines": [ln.to_dict() for ln in lines_now], "totals": totals,
            "deal": _full(db, d)}


@guarded
def deal_cost_sheet_calc(db, me, deal_id: int = 0, style_key: str = "", header: dict | None = None,
                         lines: list | None = None, **_):
    """Recalculate the costing sheet without saving anything: `{ok, totals, lines}`.

    Same rules as the save (`costing_sheet.compute`), so what this shows is exactly what a save would store. Pass `header`
    and `lines` to add up the sheet **as it is on screen** (a rate typed but not yet saved) - that is what the page calls
    while somebody is editing; nothing is written either way.
    """
    import costing_sheet as cs
    d = deals._get(db, int(deal_id or 0))
    s = deals._style(d.styles_list(), style_key)
    sheet, stored, totals = cs.open_sheet(db, d, s)
    if lines is None and not header:
        return {"ok": True, "totals": totals, "lines": [ln.to_dict() for ln in stored]}
    if lines is None:
        lines = [ln.to_dict() for ln in stored]
    totals = cs.simulate(sheet, header or {}, lines)
    return {"ok": True, "totals": totals, "lines": lines}


@guarded
def deal_cost_sheet_transfer(db, me, deal_id: int = 0, style_key: str = "", replace: bool = False, **_):
    """Transfer the costing sheet's prices into the ERP Cost Sheet (a draft).

    Materials are matched by name, charges by the ERP's own cost head, the sheet's FOB becomes the quoted price and the
    ERP's rules recompute the price. A submitted Cost Sheet is refused. Params: `deal_id`, `style_key`, `replace`.
    Returns `{ok, applied, cost_sheet, sheet, totals, messages, deal}`.
    """
    _writer(me)
    res = deals.cost_sheet_transfer(db, me, int(deal_id or 0), style_key, bool(replace))
    return {"ok": True, "applied": res.get("applied"), "cost_sheet": res.get("cost_sheet"), "sheet": res.get("sheet"),
            "totals": res.get("totals"), "messages": res.get("messages") or [], "deal": _full(db, res["deal"])}


@guarded
def deal_cost_read(db, me, deal_id: int = 0, style_key: str = "", filename: str = "costing.xlsx", data: str = "",
                   attachment_id: int = 0, **_):
    """Read a pre-made costing sheet into the style. Params: `deal_id`, `style_key`, and either `filename` + `data`
    (base64 or a data: URL, from an upload) or `attachment_id` (one of the mail's own files).

    The sheet is read by the model (every factory lays it out differently) and *recorded* on the style, so it can be
    looked at, applied, or applied again after a change. Nothing is written to the ERP by this call.
    Returns `{ok, cost_doc, deal}`.
    """
    _writer(me)
    if attachment_id:
        att = db.query(MailAttachmentModel).get(int(attachment_id))
        if not att:
            raise DealError("That attachment is not on this conversation any more.")
        raw = deals._load_bytes(att)
        if not raw:
            raise DealError(f"{att.filename} is no longer on disk. Upload the sheet again.")
        filename = att.filename or filename
    else:
        raw = base64.b64decode((data or "").split(",", 1)[-1] if (data or "").startswith("data:") else (data or ""),
                               validate=False)
    d, doc = deals.cost_document_read(db, me, int(deal_id or 0), style_key, filename or "costing.xlsx", raw)
    # the read sheet is a *source*: its numbers go into the app's own costing sheet, which keeps its own rules
    import costing_sheet as cs
    style = deals._style(deals._get(db, int(deal_id or 0)).styles_list(), style_key)
    sheet, lines_now, totals = cs.apply_import(db, deals._get(db, int(deal_id or 0)), style, doc)
    return {"ok": True, "cost_doc": doc, "sheet": sheet.to_dict(), "lines": [ln.to_dict() for ln in lines_now],
            "totals": totals, "deal": _full(db, deals._get(db, int(deal_id or 0)))}


@guarded
def deal_cost_apply_prices(db, me, deal_id: int = 0, style_key: str = "", **_):
    """One click: put the price kept for each item onto the BOM item it belongs to.

    The prices come from the app's price book (`item_price`), which the costing sheet fills as prices are typed (and which
    an imported sheet fills too). This walks the style's Cost Sheet - its material rows are the BOM items that came in with
    the inquiry - and writes each item's price on it. Consumption, charges and the quoted price are left alone, and the
    Cost Sheet stays a **draft** for a person to change in the ERP. Params: `deal_id`, `style_key`.
    Returns `{ok, items, priced, updated, missing, written, cost_sheet, messages}`.
    """
    _writer(me)
    return {"ok": True, **deals.apply_prices_to_bom(db, me, int(deal_id or 0), style_key)}


@guarded
def deal_cost_autofill(db, me, deal_id: int = 0, style_key: str = "", **_):
    """Fill the ERP Cost Sheet from the standard costing sheet, then open it.

    Nothing is filled on its own: the Cost sheet tab has one button ("Fill from the costing sheet") and this is it. Every
    material line with no price takes the price of the sheet line
    that carries the same item (then the app's own price book, `item_price`); every cost head at 0 takes the sheet's
    figure for that head and the sheet's APPLY column becomes the ERP's N/A tick - which is what the ERP demands before
    it will submit a costing. Consumption and the quoted price are never touched, an N/A a person ticked is never
    cleared, and the Cost Sheet stays a **draft**. Params: `deal_id`, `style_key`.
    Returns `{ok, materials, heads, priced, na, missing, written, cost_sheet, heads_list, messages}`.
    """
    _writer(me)
    res = deals.cost_autofill(db, me, int(deal_id or 0), style_key)
    opened = deals.cost_open(db, me, int(deal_id or 0), style_key)
    return {"ok": True, **res, "cost_sheet": opened.get("cost_sheet"), "heads_list": opened.get("heads") or [],
            "style": opened.get("style")}


@guarded
def cost_prices(db, me, q: str = "", limit: int = 500, **_):
    """The app's price book: what each item costs, newest first. Params: `q` (a word to search), `limit`.

    Filled from the costing sheet (and from a costing sheet somebody sent), so the same item's price is there next time it
    appears on a BOM. Returns `{ok, prices}`.
    """
    import costing_sheet as cs
    rows = cs.prices(db)
    if q:
        needle = q.strip().lower()
        rows = [r for r in rows if needle in f"{r.get('description') or ''} {r.get('item_code') or ''}".lower()]
    return {"ok": True, "prices": rows[:int(limit or 500)]}


@guarded
def deal_cost_apply(db, me, deal_id: int = 0, style_key: str = "", replace: bool = False, **_):
    """Put the recorded costing sheet's numbers into the ERP Cost Sheet (draft - never submitted).

    Params: `deal_id`, `style_key`, `replace` (start the material lines from the sheet instead of matching them).
    Returns `{ok, applied, cost_sheet, messages, deal}`.
    """
    _writer(me)
    res = deals.cost_document_apply(db, me, int(deal_id or 0), style_key, bool(replace))
    out = {"ok": True, "applied": res.get("applied"), "cost_sheet": res.get("cost_sheet"),
           "messages": res.get("messages") or [], "deal": _full(db, res["deal"])}
    return out


@guarded
def deal_cost_submit(db, me, deal_id: int = 0, style_key: str = "", **_):
    _writer(me)
    return {"ok": True, **deals.cost_submit(db, me, deal_id, style_key), "deal": _full(db, deals._get(db, deal_id))}


@guarded
def deal_quote_draft(db, me, deal_id: int = 0, **_):
    return {"ok": True, **deals.quote_draft(db, me, deal_id)}


@guarded
def deal_quote_send(db, me, deal_id: int = 0, body: str = "", to: str = "", cc: str = "", subject: str = "", **_):
    """Open the negotiation with our prices and send the quote in the deal's mail thread."""
    _writer(me)
    res = deals.quote_send(db, me, deal_id, body, to, cc, subject)
    return {"ok": True, **res, "deal": _full(db, deals._get(db, deal_id))}


@guarded
def deal_record_reply(db, me, deal_id: int = 0, outcome: str = "", prices: dict | None = None, note: str = "",
                      channel: str = "Email", lost_reason: str = "", **_):
    """The buyer's answer → negotiation rounds: ``counter`` | ``our_counter`` | ``accepted`` | ``drop`` | ``lost``."""
    _writer(me)
    return {"ok": True, "deal": _full(db, deals.record_reply(db, me, deal_id, outcome, prices, note, channel, lost_reason))}


@guarded
def deal_contract_prepare(db, me, deal_id: int = 0, **_):
    _writer(me)
    res = deals.contract_prepare(db, me, deal_id)
    return {"ok": True, **res, "deal": _full(db, deals._get(db, deal_id))}


@guarded
def deal_contract_form(db, me, deal_id: int = 0, refresh: bool = False, **_):
    """The contract draft, the checks before signing, and the ERP's **own** field list for the contract form.

    Every field the tower writes to the Sales Contract comes back with its type, label, section and - for a Select field -
    the ERP's own choices, plus the records that exist for a Link field (Incoterm, Payment terms template, ...). The form is
    rendered from this, so it cannot send a value the ERP does not know. Params: `deal_id`.
    `refresh` re-reads the Sales Contract from the ERP first, so a change made **there** shows up here - it is never done
    on its own, because the tower's draft can be newer than the ERP's. Params: `deal_id`, `refresh`.

    It also answers **which trade term to pick**: the eleven Incoterms in plain words (who pays freight, insurance and
    duty, where risk passes) and, for the term on this contract, whether it agrees with the shipment mode, the freight
    and insurance lines already filled in. A merchandiser should never have to guess what "DAP" obliges us to do.
    Returns `{ok, draft, readiness, fields, options, incoterm_help, trade_notes}`.
    """
    out = deals.contract_form(db, int(deal_id or 0), bool(refresh))
    sc = out.get("draft") or {}
    try:
        clocks = ship_track._contract_clocks(sc)
        notes = ship_track.trade_term_notes(sc, clocks)
        dates = ship_track.date_notes(sc, clocks)
    except Exception:                                  # the notes are advice: never break the form for them
        notes, dates = [], []
    return {"ok": True, **out, "incoterm_help": ship_track.INCOTERMS, "trade_notes": notes, "date_notes": dates}


@guarded
def deal_contract_update(db, me, deal_id: int = 0, draft: dict | None = None, **_):
    _writer(me)
    return {"ok": True, **deals.contract_update(db, me, deal_id, draft or {})}


@guarded
def deal_contract_create(db, me, deal_id: int = 0, sign: bool = False, **_):
    """Save the contract in the ERP; ``sign`` also submits it (the ERP checks dates, sizes and terms first)."""
    _writer(me)
    return {"ok": True, "deal": _full(db, deals.contract_create(db, me, deal_id, bool(sign)))}


@guarded
def deal_make_order(db, me, deal_id: int = 0, **_):
    """The Sales Order from the signed contract (a draft, one row per colour and size)."""
    _writer(me)
    return {"ok": True, "deal": _full(db, deals.make_order(db, me, deal_id))}


# ───────────────────────── ship & track: what we owe, and where the goods are ─────────────────────────
# The contract is the promise; these three functions track what the promise costs us afterwards. Nothing here writes
# a document: a document is written in the ERP (Delivery Note, Shipment). The tower keeps the two things the ERP has
# no field for - the day a paper was actually handed to the buyer, and the plain-language meaning of the trade term.

def _track(db, deal_id: int = 0) -> dict:
    """The whole shipping picture for a deal: schedule, papers owed, shipments, alerts and the trade term explained.

    Built **only** from what is on file: the contract's own day counts (ex-factory → ETD → ETA → in-warehouse), its
    payment basis (so the invoice date is a date, not a guess), the documents its ``documents_list`` names, and the
    ERP's Shipment rows that name this contract (booking, cut-off, vessel/flight, HBL/MBL/AWB, tracking link and
    status). A row with no date says so instead of inventing one. Params: `deal_id`.
    Returns `{ok, schedule, documents, shipments, shipment, alerts, incoterm, incoterm_help, trade_notes}`.
    """
    d = deals._get(db, deal_id)
    import json as _json
    try:
        contract = _json.loads(d.contract_draft or "{}")
    except (ValueError, TypeError):
        contract = {}
    be = None
    try:
        be = deals._be()
        deals.live_contract(db, d, be)          # a cancelled contract is replaced by its amendment, or dropped
    except Exception:
        be = None
    ticks = ship_track.load_ticks(db, d.id)
    out = ship_track.plan(d, contract, be=be, ticks=ticks)
    out["deal_id"] = d.id
    out["refs"] = d.refs_dict()
    if be is None:
        out["erp_error"] = out.get("erp_error") or "the ERP did not answer - the ERP's own shipment facts are not shown"
    return out


@guarded
def deal_track(db, me, deal_id: int = 0, **_):
    """The whole shipping picture for a deal — see :func:`_track`. Params: `deal_id`."""
    return _track(db, deal_id)


@guarded
def deal_track_doc(db, me, deal_id: int = 0, doc: str = "", given: int = 1, on: str = "", note: str = "", **_):
    """Mark a paper the contract obliges as handed over (or un-mark it) - the one fact the ERP does not store.

    The paper must be one this contract actually names; a typo cannot invent one. The date defaults to today and is
    kept as given, and the person who ticked it is recorded, so "did we send it?" is answerable a month later.
    Params: `deal_id`, `doc` (the row's key), `given` (1/0), `on` (YYYY-MM-DD), `note`.
    """
    _writer(me)
    import datetime as _dt
    d = deals._get(db, deal_id)
    import json as _json
    try:
        contract = _json.loads(d.contract_draft or "{}")
    except (ValueError, TypeError):
        contract = {}
    clocks = ship_track._contract_clocks(contract)
    ticks = ship_track.load_ticks(db, d.id)
    known = {x["id"]: x for x in ship_track.documents(contract, clocks, ticks)}
    key = (doc or "").strip()
    if key not in known:
        raise DealError("This contract does not name that paper. Open the Shipping tab and pick one of the rows shown.")
    if given:
        day = (on or "").strip() or _dt.date.today().isoformat()
        try:
            _dt.date.fromisoformat(day[:10])
        except ValueError:
            raise DealError("The date must be written as YYYY-MM-DD.")
        ticks[key] = {"on": day[:10], "by": me.get("email", ""), "note": (note or "").strip()[:200]}
        deals._event(d, "ship", f'{known[key]["label"]} given to the buyer on {day[:10]}', me.get("email", ""))
    else:
        ticks.pop(key, None)
        deals._event(d, "ship", f'{known[key]["label"]} marked as not yet given', me.get("email", ""))
    ship_track.save_ticks(db, d.id, ticks)
    db.commit()
    return _track(db, d.id)


@guarded
def deal_track_shipment(db, me, deal_id: int = 0, values: dict | None = None, **_):
    """Record the tracking facts on the ERP's own Shipment: carrier, AWB/BL, tracking link and status, booking and dates.

    Only fields the Shipment really has are written, and only a Shipment that exists is written to - the tower never
    invents a shipment, because a Shipment in this ERP hangs off a Delivery Note (stock has to leave the warehouse
    first). When there is none, the answer says which ERP document comes first. Params: `deal_id`, `values`.
    """
    _writer(me)
    d = deals._get(db, deal_id)
    be = deals._be()
    deals.live_contract(db, d, be)
    refs = d.refs_dict()
    rows = ship_track.shipments_for(be, refs.get("sales_contract") or "", refs.get("sales_order") or "")
    if not rows:
        raise DealError("The ERP has no Shipment for this contract yet. In this ERP a Shipment hangs off a Delivery "
                        "Note, so the order has to be submitted, packed and shipped first - then the tracking fields "
                        "can be filled here. The schedule and the papers are tracked either way.")
    ship = rows[0]["name"]
    clean_vals = {k: v for k, v in (values or {}).items() if k in ship_track.WRITABLE_SHIPMENT and v not in (None, "")}
    if not clean_vals:
        raise DealError("Nothing to save: fill the carrier, AWB/BL number, tracking link or a date first.")
    cur = be.get_doc("Shipment", ship)
    res = deals._ex(db, me, {"op": "save", "doctype": "Shipment", "name": ship, "data": clean_vals,
                             "modified": cur.get("modified")})
    if not res.get("ok"):
        raise DealError(deals._strip_html(res.get("error") or "The ERP refused the change to the shipment."))
    what = ", ".join(sorted(clean_vals.keys()))
    deals._event(d, "ship", f"Shipment {ship}: {what} recorded from the tower", me.get("email", ""),
                 doc=["Shipment", ship])
    db.commit()
    return _track(db, d.id)


@guarded
def deal_dashboard(db, me, **_):
    """Pipeline by stage, quotes waiting on the buyer, deals waiting on us, top customers; plus live ERP order figures."""
    out = {"ok": True, **deals.dashboard(db)}
    t = mailbox.list_threads(db, "all", "", 1, 0)
    out["inbox"] = t.get("counts", {})
    be = None
    try:
        be = deals._be()
    except Exception as e:
        out["erp_error"] = str(e)[:200]
    if be is not None:
        erp: dict = {}
        try:
            sos = be.get_list("Sales Order", [["docstatus", "<", 2]], ["name", "customer", "status", "grand_total", "currency", "delivery_date",
                                                                     "per_delivered", "per_billed", "docstatus", "transaction_date"],
                              order_by="delivery_date asc", limit=500)
            open_sos = [s for s in sos if s.get("status") not in ("Completed", "Closed", "Cancelled")]
            erp["open_orders"] = len(open_sos)
            by_ccy: dict = {}
            for s in open_sos:
                by_ccy[s.get("currency") or ""] = round(by_ccy.get(s.get("currency") or "", 0) + float(s.get("grand_total") or 0), 2)
            erp["open_value"] = by_ccy
            import datetime as _dt
            today = _dt.date.today()
            soon = []
            for s in open_sos:
                try:
                    dd = _dt.date.fromisoformat(str(s.get("delivery_date"))[:10])
                except Exception:
                    continue
                if dd <= today + _dt.timedelta(days=30):
                    soon.append({**s, "days": (dd - today).days})
            erp["due_30"] = soon[:12]
            months: dict = {}
            for s in sos:
                m = str(s.get("transaction_date") or "")[:7]
                if m:
                    months[m] = months.get(m, 0) + 1
            erp["orders_by_month"] = [{"month": k, "count": months[k]} for k in sorted(months)[-12:]]
        except Exception as e:
            erp["orders_error"] = str(e)[:200]
        try:
            inv = be.get_list("Sales Invoice", [["docstatus", "=", 1], ["outstanding_amount", ">", 0]],
                              ["name", "customer", "outstanding_amount", "currency", "due_date"], limit=500)
            rec: dict = {}
            for i in inv:
                rec[i.get("currency") or ""] = round(rec.get(i.get("currency") or "", 0) + float(i.get("outstanding_amount") or 0), 2)
            erp["receivables"] = rec
            erp["receivable_count"] = len(inv)
        except Exception as e:
            erp["receivables_error"] = str(e)[:200]
        out["erp"] = erp
    return out


FUNCTIONS: dict[str, Callable] = {
    "inbox_threads": inbox_threads, "inbox_thread": inbox_thread, "inbox_reply": inbox_reply, "inbox_sync": inbox_sync,
    "inbox_label": inbox_label, "inbox_archive": inbox_archive, "inbox_link_customer": inbox_link_customer, "inbox_attachment": inbox_attachment,
    "customer_list": customer_list, "customer_create": customer_create, "customer_overview": customer_overview,
    "deal_list": deal_list, "deal_get": deal_get, "deal_from_thread": deal_from_thread, "deal_create": deal_create,
    "deal_update": deal_update, "deal_register": deal_register, "deal_cost_open": deal_cost_open, "deal_cost_save": deal_cost_save,
    "deal_erp_setup": deal_erp_setup, "deal_documents": deal_documents, "deal_read_documents": deal_read_documents,
    "deal_bom_upload": deal_bom_upload, "deal_bom_from_mail": deal_bom_from_mail, "deal_bom_from_erp": deal_bom_from_erp,
    "deal_bom_ai": deal_bom_ai, "deal_bom_paste": deal_bom_paste, "deal_bom_apply": deal_bom_apply,
    "deal_bom_sources": deal_bom_sources,
    "deal_cost_sheet": deal_cost_sheet, "deal_cost_sheet_save": deal_cost_sheet_save,
    "cost_sheet_list": cost_sheet_list, "cost_prices": cost_prices,
    "deal_cost_apply_prices": deal_cost_apply_prices, "deal_cost_autofill": deal_cost_autofill,
    "deal_cost_sheet_calc": deal_cost_sheet_calc, "deal_cost_sheet_transfer": deal_cost_sheet_transfer,
    "deal_cost_read": deal_cost_read, "deal_cost_apply": deal_cost_apply, "deal_cost_submit": deal_cost_submit, "deal_quote_draft": deal_quote_draft, "deal_quote_send": deal_quote_send,
    "deal_record_reply": deal_record_reply, "deal_contract_prepare": deal_contract_prepare,
    "deal_contract_form": deal_contract_form, "deal_contract_update": deal_contract_update, "deal_contract_create": deal_contract_create, "deal_make_order": deal_make_order,
    "deal_track": deal_track, "deal_track_doc": deal_track_doc, "deal_track_shipment": deal_track_shipment,
    "deal_dashboard": deal_dashboard,
}
