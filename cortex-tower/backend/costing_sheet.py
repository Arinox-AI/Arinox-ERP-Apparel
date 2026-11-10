"""Reading, saving, computing and transferring the costing sheet.

Five verbs, one document:

``open_sheet``   get this style's sheet — **seeding it from the standard template** the first time, so it is already there
                 with the buyer's BOM lines and the style's quantity, never an empty page.
``sync_template``put a sheet stored against an older template back in line with the current one, keeping every number
                 somebody typed and every line somebody added.
``save_sheet``   store what a person typed (lines edited, added, deleted, renamed). No ERP write.
``compute``      the sheet's own arithmetic, exactly the workbook's: usage × (1 + wastage) × rate, the fabric export /
                 import lines priced on the total fabric metres, the carton at one per pcs-per-carton, percentages on the
                 product cost, profit on the total cost, FOB per piece in USD and VND, order value. Pure function.
``transfer``     push the prices into the ERP Cost Sheet as a **draft** (materials matched by name, charges by the ERP's
                 own cost head, quoted price = FOB), then leave it to the ERP's rules and to a person.

The arithmetic lives here on purpose. The ERP's Cost Sheet is the system of record for the price, but a merchandiser needs
to *see* the sum, change a rate and watch the FOB move, before anything is written.
"""

from __future__ import annotations

import re
from typing import Optional

from models_costing import (SIGNOFF_ROLES, TEMPLATE, CostingLineModel, CostingSheetModel)

#: The template's material types that are fabric, and so feed the "fabric metres" of the export/import lines.
FABRIC_TYPES = ("fabric", "contrast fabric", "lining", "shell")

#: Lines the previous template had and this one does not. Removed on sync only when nothing was ever entered on them.
RETIRED = ("fusing / interlining", "depreciation", "freight / local charges to fob")

TEMPLATE_BY_TPL = {spec["tpl"]: spec for spec in TEMPLATE}


def _num(v, default=None) -> Optional[float]:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def _money(v: float) -> float:
    return round(float(v or 0), 6)


def _is_fabric(ln: CostingLineModel) -> bool:
    return str(ln.material_type or "").lower() in FABRIC_TYPES


def _usage(ln: CostingLineModel, pcs_per_carton: float, fabric_metres: float) -> float:
    """The usage the sheet uses for a line — typed, or worked out by the line's rule."""
    if ln.rule == "per_carton":
        return (1.0 / pcs_per_carton) if pcs_per_carton else 0.0
    if ln.rule == "fabric_metres":
        return fabric_metres
    return _num(ln.usage) or 0.0


def compute(sheet: CostingSheetModel, lines: list[CostingLineModel]) -> dict:
    """The sheet's own numbers. Deterministic: same lines, same totals, no database, no ERP.

    Read exactly like the workbook: raw materials (usage incl. wastage × rate), processing charges (apply 1/0), product
    cost = the two totals, other expenses (% of the product cost), total cost before profit, profit (% of that), FOB per
    piece in USD and in local currency, order value.
    """
    pcs_per_carton = _num(sheet.pcs_per_carton) or 0.0
    materials = [ln for ln in lines if ln.kind == "material"]
    processing = [ln for ln in lines if ln.kind == "processing"]
    expenses = [ln for ln in lines if ln.kind == "expense"]

    # the workbook's two fabric lines are priced on the total fabric metres including wastage
    fabric_metres = 0.0
    for ln in materials:
        if ln.rule == "fabric_metres" or not _is_fabric(ln) or not ln.apply:
            continue
        fabric_metres += (_num(ln.usage) or 0.0) * (1 + (_num(ln.wastage_pct) or 0.0))

    rows: list[dict] = []
    raw_material = 0.0
    for ln in materials:
        usage = _usage(ln, pcs_per_carton, fabric_metres)
        waste = _num(ln.wastage_pct) or 0.0
        rate = _num(ln.rate) or 0.0
        cost = usage * (1 + waste) * rate if ln.apply else 0.0
        raw_material += cost
        rows.append({**ln.to_dict(), "usage_effective": _money(usage), "cost_per_pc": _money(cost)})

    processing_cost = 0.0
    for ln in processing:
        rate = _num(ln.rate) or 0.0
        cost = rate if ln.apply else 0.0
        processing_cost += cost
        rows.append({**ln.to_dict(), "usage_effective": None, "cost_per_pc": _money(cost)})

    product_cost = raw_material + processing_cost
    other = 0.0
    profit = 0.0
    for ln in expenses:
        share = _num(ln.share) or 0.0
        is_profit = bool(ln.cost_head and ln.cost_head.lower() == "profit") or "profit" in (ln.label or "").lower()
        amount = 0.0
        if ln.apply:
            # profit is a share of the cost *before* profit, like the workbook's =G54*E55
            amount = (product_cost + other) * share if is_profit else product_cost * share
        if is_profit:
            profit += amount
        else:
            other += amount
        rows.append({**ln.to_dict(), "usage_effective": None, "cost_per_pc": _money(amount)})

    fob_before_profit = product_cost + other
    fob = fob_before_profit + profit
    qty = _num(sheet.order_qty) or 0
    vnd = _num(sheet.vnd_per_usd) or 0
    return {"rows": rows, "fabric_metres": _money(fabric_metres), "raw_material": _money(raw_material),
            "processing": _money(processing_cost), "product_cost": _money(product_cost),
            "other_expenses": _money(other), "profit": _money(profit),
            "fob_before_profit": _money(fob_before_profit), "fob_usd": _money(fob),
            "fob_vnd": _money(fob * vnd) if vnd else None, "vnd_per_usd": vnd or None,
            "order_qty": qty or None, "order_value": _money(fob * qty) if qty else None,
            "currency": sheet.currency or "USD", "profit_pct": _num(sheet.profit_pct) or 0.0}


# ───────────────────────── seed + template sync ─────────────────────────

def _words(text: str) -> set[str]:
    t = re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower())
    return {w for w in t.split() if len(w) > 1}


def _norm_label(text: str) -> str:
    t = str(text or "").lower().replace("meter", "metre").replace("&", "and")
    return " ".join(sorted(_words(t)))


def _from_bom(spec: dict, bom: list[dict], used: set, allow_type_only: bool = True,
              foreign_hints: tuple = ()) -> Optional[dict]:
    """The BOM line a template row means.

    The material **type** decides first (a "Fabric" line for MAIN FABRIC, a "Contrast Fabric" one for the contrast row),
    then the words in the template's ``from_bom`` hints. A BOM line is used once, so the contrast fabric cannot be
    counted as the main fabric and the main label cannot be taken twice.
    """
    want_type = (spec.get("material_type") or "").lower()
    hints = spec.get("from_bom") or ()
    rows = []
    for i, row in enumerate(bom or []):
        if i in used:
            continue
        rtype = (row.get("material_type") or "").lower()
        blob = f"{row.get('description') or ''} {rtype}".lower()
        type_ok = bool(want_type) and (rtype == want_type
                                       or (want_type == "contrast fabric" and "contrast" in rtype)
                                       or (want_type == "lining" and "lining" in rtype)
                                       or (want_type == "fusing" and "fus" in rtype))
        hint_ok = bool(hints) and any(h in blob for h in hints)
        rows.append(((i, row), type_ok, hint_ok))
    # both agree, then the template's own words, then the type alone: the type alone would let ZIPPER take the only
    # "Trim" line and leave BUTTON with nothing (it did, 2026-11-07)
    for cand, type_ok, hint_ok in rows:
        if type_ok and hint_ok:
            return cand
    for cand, type_ok, hint_ok in rows:
        if hint_ok:
            return cand
    if allow_type_only:
        for cand, type_ok, hint_ok in rows:
            if not type_ok:
                continue
            blob = f"{cand[1].get('description') or ''} {cand[1].get('material_type') or ''}".lower()
            # a row the template names for another line (a BUTTON is not a ZIPPER) is left for that line
            if any(any(h in blob for h in other) for other in foreign_hints if other):
                continue
            return cand
    return None


def _new_line(sheet_id: int, spec: dict, seq: int) -> CostingLineModel:
    return CostingLineModel(
        sheet_id=sheet_id, seq=seq, tpl=spec["tpl"], kind=spec["kind"], label=spec["label"],
        material_type=spec.get("material_type"), cost_head=spec.get("cost_head"),
        uom=spec.get("uom"), usage=None, wastage_pct=None, wastage_reason=None, rate=None,
        share=(spec.get("share_default") or 0.0) if spec.get("share") else None,
        apply=bool(spec.get("apply_default", True)), rule=spec.get("rule"), from_fabric=False, note=None)


def seed(db, deal, style: dict) -> tuple[CostingSheetModel, list[CostingLineModel]]:
    """Create this style's sheet from the standard template, filled with what the deal already knows."""
    sheet = CostingSheetModel(deal_id=deal.id, style_key=style["key"], style_no=style.get("style_no"),
                              style_name=style.get("style_name"), buyer=deal.customer_name or deal.customer,
                              season=style.get("season"), factory=None, costing_date=None,
                              currency=deal.currency or "USD", order_qty=_num(style.get("qty")),
                              pcs_per_carton=_num(style.get("pcs_per_carton")), fob_port=deal.destination,
                              vnd_per_usd=None, profit_pct=0.15, signoffs="{}", imported_from=None, totals="{}")
    db.add(sheet)
    db.commit()
    db.refresh(sheet)

    lines: list[CostingLineModel] = []
    for seq, spec in enumerate(TEMPLATE, start=1):
        ln = _new_line(sheet.id, spec, seq)
        db.add(ln)
        lines.append(ln)
    db.commit()
    for ln in lines:
        db.refresh(ln)
    # what the deal knows first (the buyer's BOM usage and price), then the workbook's own working figures for
    # whatever is still blank - so the sheet opens populated, and the BOM always wins over the template.
    link_items(lines, [r for r in (style.get("bom") or []) if isinstance(r, dict)])
    apply_defaults(lines)
    db.commit()
    return sheet, _sorted_lines(db, sheet)


def apply_defaults(lines: list[CostingLineModel]) -> bool:
    """Fill a template line's blank numbers with the workbook's own working figures.

    ``APPAREL_COSTING_DETAILED_REVISED`` carries a rate on every line (main fabric 3.000 a metre, main label 0.050,
    making 5.000 …) and a usage on the lines a buyer's BOM says nothing about (hang tag 2, tissue 6, thread 200 …).
    A sheet used to open with every rate at nothing and the whole page to type; it now opens the way the spreadsheet
    does. **Only blanks are filled**: a usage that came from the buyer's BOM, and anything a person typed - a
    deliberate 0 included - is never overwritten. Returns whether anything changed.

    A spare OTHERS row that took a real BOM item is that item, not the template's "OTHERS", so it takes no default.
    """
    changed = False
    for ln in lines:
        spec = TEMPLATE_BY_TPL.get(ln.tpl or "")
        if not spec:
            continue
        if spec.get("label") == "OTHERS" and ln.item_code:
            continue
        for field, key in (("usage", "usage_default"), ("wastage_pct", "wastage_default"), ("rate", "rate_default")):
            if key not in spec or getattr(ln, field) is not None:
                continue
            setattr(ln, field, float(spec[key]))
            changed = True
    return changed


def link_items(lines: list[CostingLineModel], bom: list[dict]) -> bool:
    """Tie each template material row to the BOM item it covers, and take that item's usage.

    This is what makes a price go to the right item: MAIN FABRIC is "(Self) 100% LYOCELL", so a price typed on that line
    belongs to that item and can be put on the BOM with one click. A row is filled only when it is still empty, so a usage
    somebody typed is never overwritten.
    """
    if not bom:
        return False
    mat_specs = [(ln, TEMPLATE_BY_TPL.get(ln.tpl or "")) for ln in lines if ln.kind == "material" and ln.tpl]
    taken: set = set()
    picked: dict = {}
    # first the rows the template names or types clearly (both signals, then the words alone), so a generic "Trim" row is
    # never grabbed by the first trim-like template line; then whatever is still empty may take a row by type alone
    for allow in (False, True):
        for ln, spec in mat_specs:
            if ln.id in picked or spec is None:
                continue
            foreign = tuple(o.get("from_bom") or () for ln2, o in mat_specs if ln2.id != ln.id and o and (o.get("from_bom") or ()))
            hit = _from_bom(spec, bom, taken, allow_type_only=allow, foreign_hints=foreign)
            if hit:
                taken.add(hit[0])
                picked[ln.id] = hit[1]
    # a BOM item the named rows have no place for goes into one of the template's spare OTHERS rows, so every item that
    # came in with the BOM has a line that can carry its price (no row is invented, nothing is dropped)
    leftovers = [r for i, r in enumerate(bom) if i not in taken]
    spare = [ln for ln, spec in mat_specs if spec and spec.get("tpl", "").startswith("M1") and spec["label"] == "OTHERS"
             and not ln.item_code and not _num(ln.usage) and not _num(ln.rate)]
    for ln, row in zip(spare, leftovers):
        picked[ln.id] = row

    changed = False
    for ln, _spec in mat_specs:
        row = picked.get(ln.id)
        if not row:
            continue
        if ln.item_code != (row.get("item_code") or None) or ln.item_desc != (row.get("description") or None):
            ln.item_code = (row.get("item_code") or None)
            ln.item_desc = (row.get("description") or None)
            changed = True
        if not _num(ln.usage) and _num(row.get("consumption")):
            ln.usage = _num(row.get("consumption"))
            changed = True
        if not _num(ln.rate) and _num(row.get("rate")):
            ln.rate = _num(row.get("rate"))
            changed = True
        if not ln.uom and row.get("uom"):
            ln.uom = str(row.get("uom"))[:12]
            changed = True
    return changed


def _sorted_lines(db, sheet: CostingSheetModel) -> list[CostingLineModel]:
    return (db.query(CostingLineModel).filter(CostingLineModel.sheet_id == sheet.id)
            .order_by(CostingLineModel.seq, CostingLineModel.id).all())


def _blank(ln: CostingLineModel) -> bool:
    return (not _num(ln.usage) and not _num(ln.rate) and not _num(ln.share)
            and not (ln.wastage_pct or 0) and not (ln.wastage_reason or "").strip())


def sync_template(db, sheet: CostingSheetModel) -> bool:
    """Bring a stored sheet in line with the current template. Idempotent; never loses a number.

    A sheet opened before the template changed (or seeded by an older template) keeps its typed values: each stored line
    is matched to its template slot — by slot first, then by name — and only the *shape* is refreshed (kind, type, cost
    head, rule, the apply flag when it has never been touched). Missing template rows are added, lines somebody added by
    hand stay at the end, and a retired template row that nothing was ever entered on is dropped.
    """
    lines = _sorted_lines(db, sheet)
    by_tpl = {ln.tpl: ln for ln in lines if ln.tpl}
    loose = [ln for ln in lines if not ln.tpl]
    known_slots = {ln.tpl for ln in lines if ln.tpl}      # slots this sheet already had, before any matching
    changed = False

    # match old rows (stored before slots existed) to slots by name, one row per slot
    for spec in TEMPLATE:
        if spec["tpl"] in by_tpl:
            continue
        want = _norm_label(spec["label"])
        hit = next((ln for ln in loose if _norm_label(ln.label) == want and not ln.tpl), None)
        if hit is not None:
            hit.tpl = spec["tpl"]
            by_tpl[spec["tpl"]] = hit
            changed = True

    for seq, spec in enumerate(TEMPLATE, start=1):
        ln = by_tpl.get(spec["tpl"])
        if ln is None:
            ln = _new_line(sheet.id, spec, seq)
            db.add(ln)
            changed = True
            continue
        adopted = ln.tpl not in known_slots
        # refresh the shape, keep every value
        for field, value in (("kind", spec["kind"]), ("material_type", spec.get("material_type")),
                             ("cost_head", spec.get("cost_head")), ("rule", spec.get("rule"))):
            if getattr(ln, field) != value:
                setattr(ln, field, value)
                changed = True
        if ln.rule and ln.rule != "per_carton" and ln.uom == "PCS":
            ln.uom = "MTR"
            changed = True
        if not ln.uom and spec.get("uom"):
            ln.uom = spec["uom"]
            changed = True
        if ln.seq != seq:
            ln.seq = seq
            changed = True
        ln.from_fabric = False
        # a row that has only just joined the template takes the template's own policy (a % somebody typed is kept)
        if adopted:
            if spec.get("share") and not _num(ln.share):
                ln.share = spec.get("share_default") or 0.0
                changed = True
            if "apply_default" in spec and ln.apply != bool(spec["apply_default"]) and not _num(ln.rate):
                ln.apply = bool(spec["apply_default"])
                changed = True

    # the two fabrics of a style are one line each: a BOM row that repeats a filled MAIN / CONTRAST row is the same fabric
    filled = [_num(ln.usage) for ln in _sorted_lines(db, sheet) if ln.tpl in ("M01", "M02") and _num(ln.usage)]
    for ln in _sorted_lines(db, sheet):
        if ln.tpl is not None or ln.kind != "material" or not _is_fabric(ln) or not _num(ln.usage):
            continue
        if _num(ln.rate):
            continue
        if any(abs(u - _num(ln.usage)) <= 0.005 for u in filled):
            db.delete(ln)
            changed = True

    # a retired template row nothing was entered on is noise; anything with a number in it stays
    retired_names = {_norm_label(x) for x in RETIRED}
    for ln in _sorted_lines(db, sheet):
        if ln.tpl is not None or _norm_label(ln.label) not in retired_names:
            continue
        others = [o for o in _sorted_lines(db, sheet) if o is not ln and o.tpl is None
                  and _norm_label(o.label) not in retired_names]
        same = any(o.material_type == ln.material_type and _num(o.usage) and _num(ln.usage)
                   and abs(_num(o.usage) - _num(ln.usage)) <= 0.005 for o in others)
        if _blank(ln) or same:
            db.delete(ln)
            changed = True

    if changed:
        db.commit()
        _resequence(db, sheet)
    return changed


def _resequence(db, sheet: CostingSheetModel) -> None:
    """Template rows in template order, then whatever was added by hand in the order it was added."""
    lines = _sorted_lines(db, sheet)
    order = {spec["tpl"]: i for i, spec in enumerate(TEMPLATE, start=1)}
    template_rows = sorted([ln for ln in lines if ln.tpl in order], key=lambda ln: order[ln.tpl])
    custom_rows = [ln for ln in lines if ln.tpl not in order]
    for i, ln in enumerate(template_rows + custom_rows, start=1):
        if ln.seq != i:
            ln.seq = i
    db.commit()


def open_sheet(db, deal, style: dict) -> tuple[CostingSheetModel, list[CostingLineModel], dict]:
    """This style's sheet, created from the template the first time. Totals are always freshly computed."""
    sheet = (db.query(CostingSheetModel)
             .filter(CostingSheetModel.deal_id == deal.id, CostingSheetModel.style_key == style["key"]).first())
    if sheet is None:
        sheet, _ = seed(db, deal, style)
    else:
        sync_template(db, sheet)
    if not sheet.order_qty:
        sheet.order_qty = _num(style.get("qty"))
    if not sheet.buyer:
        sheet.buyer = deal.customer_name or deal.customer
    loose = [ln for ln in _sorted_lines(db, sheet) if ln.kind == "material" and ln.tpl and not ln.item_code]
    if loose:
        link_items(_sorted_lines(db, sheet), [r for r in (style.get("bom") or []) if isinstance(r, dict)])
        db.commit()
    # a sheet stored before the workbook's figures existed gets them now (blanks only, so nothing typed is lost)
    if apply_defaults(_sorted_lines(db, sheet)):
        db.commit()
    lines = _sorted_lines(db, sheet)
    totals = compute(sheet, lines)
    sheet.totals = __import__("json").dumps(totals)
    db.commit()
    return sheet, lines, totals


# ───────────────────────── list (the Costing page) ─────────────────────────

def list_sheets(db) -> list[dict]:
    """Every style of every deal, with its costing sheet if one exists — what the Costing page lists."""
    from models_deal import DealModel
    sheets = {(s.deal_id, s.style_key): s for s in db.query(CostingSheetModel).all()}
    out: list[dict] = []
    for d in db.query(DealModel).order_by(DealModel.id.desc()).all():
        styles = d.styles_list()
        for s in styles:
            if s.get("status") == "dropped":
                continue
            sh = sheets.get((d.id, s.get("key")))
            totals = sh.totals_dict() if sh else {}
            out.append({
                "deal_id": d.id, "deal_title": d.title or d.customer_name or f"Deal #{d.id}",
                "customer_name": d.customer_name or d.customer, "stage": d.stage, "currency": (sh.currency if sh else d.currency),
                "style_key": s.get("key"), "style_no": s.get("style_no") or "(no style number)",
                "style_name": s.get("style_name"), "qty": s.get("qty"),
                "sheet_id": sh.id if sh else None, "order_qty": sh.order_qty if sh else _num(s.get("qty")),
                "order_value": totals.get("order_value"), "fob_usd": totals.get("fob_usd"),
                "material_cost": totals.get("raw_material"), "profit_pct": sh.profit_pct if sh else None,
                "transferred_at": sh.transferred_at.isoformat() if sh and sh.transferred_at else None,
                "updated_at": sh.updated_at.isoformat() if sh and sh.updated_at else None,
                "erp_cost_sheet": s.get("cost_sheet") or "", "erp_cost_status": s.get("cost_status") or "",
                "quoted_price": (s.get("cost") or {}).get("quoted_price"),
            })
    return out


# ───────────────────────── save ─────────────────────────

_LINE_FIELDS = ("kind", "label", "material_type", "cost_head", "usage", "uom", "wastage_pct", "wastage_reason", "rate",
                "share", "apply", "rule", "from_fabric", "note", "tpl")
_NUMBERS = ("usage", "wastage_pct", "rate", "share")
_HEADER_TEXT = ("currency", "fob_port", "version", "note", "imported_from", "style_name", "buyer", "season", "factory",
                "costing_date")
_HEADER_NUMBERS = ("order_qty", "pcs_per_carton", "profit_pct", "vnd_per_usd")


def save_sheet(db, deal, style: dict, header: Optional[dict] = None, lines: Optional[list] = None) -> tuple:
    """Store what a person changed. Nothing is written to the ERP here."""
    sheet, current, _ = open_sheet(db, deal, style)
    header = header or {}
    for k in _HEADER_TEXT:
        if k in header and header[k] is not None:
            setattr(sheet, k, (str(header[k])[:200] if k == "note" else str(header[k])[:120]) or None)
    for k in _HEADER_NUMBERS:
        if k in header:
            v = _num(header[k])
            if v is not None or header[k] in (None, ""):
                setattr(sheet, k, v)
    if isinstance(header.get("signoffs"), dict):
        keep = {r: {kk: str((header["signoffs"].get(r) or {}).get(kk) or "")[:80]
                    for kk in ("name", "date")} for r in SIGNOFF_ROLES}
        import json as _json
        sheet.signoffs = _json.dumps(keep)

    if lines is not None:
        by_id = {ln.id: ln for ln in current}
        kept = []
        for i, row in enumerate(lines):
            ln = by_id.get(int(row.get("id"))) if row.get("id") else None
            if ln is None:
                ln = CostingLineModel(sheet_id=sheet.id, seq=i + 1)
                db.add(ln)
            ln.seq = i + 1
            for f in _LINE_FIELDS:
                if f not in row:
                    continue
                v = row[f]
                if f == "tpl":
                    v = v if v in TEMPLATE_BY_TPL else ln.tpl
                elif f in _NUMBERS:
                    v = _num(v)
                elif f in ("apply", "from_fabric"):
                    v = bool(v)
                elif f == "rule":
                    v = v if v in ("per_carton", "fabric_metres") else None
                elif isinstance(v, str):
                    v = v[:140] if f != "note" else v[:200]
                setattr(ln, f, v)
            if ln.rule and ln.kind != "material":
                ln.rule = None
            kept.append(ln)
        for ln in current:                       # a line the person deleted
            if ln not in kept:
                db.delete(ln)
        db.commit()

    # the profit % on the header and the PROFIT line are the same number
    lines_now = _sorted_lines(db, sheet)
    profit_line = next((ln for ln in lines_now if ln.kind == "expense" and str(ln.cost_head or "").lower() == "profit"),
                       None)
    if profit_line is not None:
        if "profit_pct" in header and _num(header.get("profit_pct")) is not None:
            profit_line.share = _num(header.get("profit_pct"))
        elif _num(profit_line.share) is not None:
            sheet.profit_pct = _num(profit_line.share)
    db.commit()
    _resequence(db, sheet)
    sheet, lines_now, totals = open_sheet(db, deal, style)
    _relink_if_needed(db, sheet, style)
    store_prices(db, sheet, lines_now, source=f"costing sheet {sheet.style_no or style.get('style_no') or ''}".strip())
    return sheet, lines_now, totals


def _relink_if_needed(db, sheet: CostingSheetModel, style: dict) -> None:
    """A sheet whose material rows are not tied to BOM items yet (or a new BOM line) gets tied before prices are kept."""
    lines = _sorted_lines(db, sheet)
    if any(ln.kind == "material" and ln.tpl and not ln.item_code for ln in lines):
        if link_items(lines, [r for r in (style.get("bom") or []) if isinstance(r, dict)]):
            db.commit()


# ───────────────────────── import a sheet somebody sent ─────────────────────────

def apply_import(db, deal, style: dict, doc: dict) -> tuple:
    """Put a **read** costing sheet (from a file or a mail attachment) into this module's own sheet.

    The sheet keeps its own rows and rules; what the imported document gives is the numbers: a line with the same label
    (or the same cost head) takes its usage, wastage and rate, a line the template does not have is appended in the right
    group, and the sheet's own totals are then computed by :func:`compute` - not copied from the document, so the
    arithmetic is always the one this app can show and defend.
    """
    sheet, current, _ = open_sheet(db, deal, style)
    by_label = {_norm_label(ln.label): ln for ln in current}
    by_head = {str(ln.cost_head or "").lower(): ln for ln in current}
    used: set = set()
    for m in doc.get("materials") or []:
        ln = by_label.get(_norm_label(m.get("label"))) or _match(m.get("label"), current, used)
        if ln is None:
            ln = CostingLineModel(sheet_id=sheet.id, kind="material", label=str(m.get("label") or "")[:140],
                                  material_type=m.get("material_type") or "Other", apply=True, note="imported")
            db.add(ln)
        else:
            used.add(ln.id)
        ln.usage = _num(m.get("usage"), ln.usage)
        ln.wastage_pct = _num(m.get("wastage_pct"), ln.wastage_pct)
        ln.wastage_reason = m.get("wastage_reason") or ln.wastage_reason
        ln.rate = _num(m.get("rate"), ln.rate)
        ln.uom = (m.get("uom") or ln.uom or "")[:12] or None
        ln.material_type = ln.material_type or m.get("material_type")
    for c in doc.get("charges") or []:
        head = str(c.get("cost_head") or "")
        value = _num(c.get("value"))
        ln = by_head.get(head.lower()) if head else None
        if ln is None and c.get("label"):
            ln = by_label.get(_norm_label(c.get("label")))
        if ln is None:
            # a value of 1 or less is a share of the product cost, anything else is money per piece
            share_ish = value is not None and value <= 1
            ln = CostingLineModel(sheet_id=sheet.id, kind="expense" if share_ish else "processing",
                                  label=str(c.get("label") or head or "")[:140], cost_head=head or None,
                                  share=value if share_ish else 0.0, note="imported")
            if not share_ish:
                ln.rate = value
            db.add(ln)
        else:
            if ln.kind == "expense":
                ln.share = value
            else:
                ln.rate = value
        ln.apply = bool(c.get("apply", True))
        if not ln.label:
            ln.label = head
    sheet.imported_from = (doc.get("source") or "")[:200] or sheet.imported_from
    sheet.profit_pct = _num((doc.get("totals") or {}).get("profit_pct"), sheet.profit_pct)
    db.commit()
    _resequence(db, sheet)
    out = open_sheet(db, deal, style)
    store_prices(db, out[0], out[1], source=f"imported {doc.get('source') or 'costing sheet'}")
    return out


def _match(label: str, lines: list, used: set):
    """The sheet line an imported label means, by word overlap. A line already claimed is skipped."""
    want = _words(label)
    if not want:
        return None
    best, score = None, 0.0
    for ln in lines:
        if ln.id in used:
            continue
        have = _words(f"{ln.label or ''} {ln.material_type or ''} {ln.cost_head or ''}")
        if not have:
            continue
        overlap = len(want & have) / max(1, len(want | have))
        if overlap > score:
            best, score = ln, overlap
    return best if score >= 0.5 else None


# ───────────────────────── what-if (no writes) ─────────────────────────

_HEADER_FIELDS = ("currency", "order_qty", "pcs_per_carton", "vnd_per_usd", "profit_pct", "fob_port", "version",
                  "buyer", "season", "factory", "costing_date")

_SIM_FIELDS = ("kind", "label", "material_type", "cost_head", "usage", "uom", "wastage_pct", "rate", "share", "rule",
               "tpl", "id", "seq")


def simulate(sheet: CostingSheetModel, header: Optional[dict], rows: list) -> dict:
    """Add up a sheet as it is on screen, without saving it.

    Same :func:`compute`, on transient copies of the lines, so a rate typed on the page shows the new FOB immediately and
    the number on screen is always the number the sheet's own rules give - never a second implementation in the browser.
    """
    header = header or {}
    tmp = CostingSheetModel()
    for f in _HEADER_FIELDS:
        setattr(tmp, f, header.get(f, getattr(sheet, f, None)))
    tmp.profit_pct = _num(tmp.profit_pct) or 0.0
    lines: list[CostingLineModel] = []
    for r in rows or []:
        ln = CostingLineModel()
        for f in _SIM_FIELDS:
            setattr(ln, f, r.get(f))
        ln.apply = bool(r.get("apply", True))
        ln.from_fabric = False
        ln.note = r.get("note")
        lines.append(ln)
    return compute(tmp, lines)


# ───────────────────────── the price book (item -> price) ─────────────────────────

def price_key(item_code: Optional[str], text: Optional[str]) -> str:
    """How an item is looked up: its own code when the sheet has one, otherwise its description in a stable order."""
    code = str(item_code or "").strip()
    if code:
        return f"code:{code.lower()}"
    return _norm_label(text or "")


def store_prices(db, sheet: CostingSheetModel, lines: list[CostingLineModel], source: str = "") -> int:
    """Keep the price of every priced material line, against its item. This is the sheet's price book.

    Nothing is stored for a line with no price, so a blank never wipes a price somebody had entered before.
    """
    from models_costing import ItemPriceModel
    stored = 0
    for ln in lines:
        if ln.kind != "material" or _num(ln.rate) is None:
            continue
        code = (ln.item_code or "").strip() or None
        desc = (ln.item_desc or ln.label or "").strip() or None
        key = price_key(code, desc)
        desc_key = _norm_label(desc or "")
        if not key:
            continue
        row = None
        if code:
            row = db.query(ItemPriceModel).filter(ItemPriceModel.item_code == code).first()
        if row is None and desc_key:
            row = db.query(ItemPriceModel).filter(ItemPriceModel.desc_key == desc_key).first()
        if row is None:
            row = ItemPriceModel(key=key, desc_key=desc_key or None, item_code=code, description=desc, uom=ln.uom,
                                 rate=_num(ln.rate), currency=sheet.currency or "USD", source=source or None)
            db.add(row)
        else:
            row.key = key
            row.desc_key = desc_key or row.desc_key
            row.item_code = code or row.item_code
            row.description = desc or row.description
            row.uom = ln.uom or row.uom
            row.rate = _num(ln.rate)
            row.currency = sheet.currency or row.currency
            row.source = source or row.source
        stored += 1
    db.commit()
    return stored


def lookup_price(db, item_code: Optional[str], description: Optional[str]) -> Optional[dict]:
    """The stored price of one item: by its code first, then by its description."""
    from models_costing import ItemPriceModel
    code = str(item_code or "").strip()
    if code:
        row = db.query(ItemPriceModel).filter(ItemPriceModel.item_code == code).first()
        if row is not None:
            return row.to_dict()
    key = _norm_label(description or "")
    if key:
        row = db.query(ItemPriceModel).filter(ItemPriceModel.desc_key == key).first()
        if row is not None:
            return row.to_dict()
    return None


def prices(db) -> list[dict]:
    """The whole price book, newest first - what the screen shows when somebody asks what an item costs."""
    from models_costing import ItemPriceModel
    rows = db.query(ItemPriceModel).order_by(ItemPriceModel.updated_at.desc()).all()
    return [r.to_dict() for r in rows]
