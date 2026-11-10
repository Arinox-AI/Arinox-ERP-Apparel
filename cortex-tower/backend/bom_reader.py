"""Read what a buyer sends with an inquiry: the styles in the mail and one BOM sheet per style.

Built on the two layouts seen in the real mailbox (2026-11-07):

* a clean sheet: header block (``Style:`` / ``Color:`` / ``Season:`` …) then a table ``Item | Category | Description |
  Color | UOM | Qty / garment | Remarks``;
* the buyer-system export (STY360): the same header block with values far to the right, and a table whose cells do not
  sit exactly under their headings (``Item`` at column 2, item codes at column 1).

Each data cell is given to the heading nearest to it, which reads both. Nothing is guessed: a row with no usable
quantity is kept with ``consumption: None`` so a person sees it, and a value that is not on the sheet is not made up.

Pure functions: bytes in, dicts out. No database, no ERP, no network.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Optional

# ───────────────────────── reading cells ─────────────────────────


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).replace("\r", " ").strip()


def _xls_sheets(data: bytes) -> list:
    """A legacy .xls as sheets of rows. Read by ``xlsread`` first (pure Python, so every machine reads the same
    file the same way); ``xlrd`` only for the formats that reader refuses, such as a pre-97 BIFF."""
    try:
        import xlsread
        return xlsread.read_sheets(data)
    except Exception:
        pass
    import xlrd                                        # optional; absent on the runtime that serves the app
    book = xlrd.open_workbook(file_contents=data)
    out = []
    for sh in book.sheets():
        rows = []
        for i in range(sh.nrows):
            rows.append([(j, v) for j, v in enumerate(sh.row_values(i)) if _cell(v) != ""])
        out.append(rows)
    return out


def sheet_rows(filename: str, data: bytes) -> list[list[list[tuple[int, object]]]]:
    """Every sheet as rows of ``(column, value)`` for the non-empty cells. ``[]`` when the file cannot be read."""
    name = (filename or "").lower()
    sheets: list = []
    try:
        if name.endswith((".xlsx", ".xlsm")):
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
            for ws in wb.worksheets:
                rows = []
                for r in ws.iter_rows(values_only=True):
                    rows.append([(j, v) for j, v in enumerate(r) if v is not None and _cell(v) != ""])
                sheets.append(rows)
        elif name.endswith(".xls"):
            sheets = _xls_sheets(data)
        elif name.endswith((".csv", ".tsv")):
            text = data.decode("utf-8-sig", "replace")
            dialect = csv.excel_tab if name.endswith(".tsv") else csv.excel
            rows = [[(j, v) for j, v in enumerate(r) if v.strip()] for r in csv.reader(io.StringIO(text), dialect)]
            sheets.append(rows)
    except Exception:
        return []
    return sheets


def grid_text(filename: str, data: bytes, max_rows: int = 200, max_cols: int = 48, max_chars: int = 24000) -> str:
    """The sheet as plain text for a model to read: one line per row, cells separated by `` | ``.

    Nothing is interpreted here - no header guessing, no column mapping. That is the point: a layout the
    deterministic reader does not know (a buyer's own system, a merged header, two blocks in one sheet) still
    reaches the model intact, and the model is asked for the rows.

    Columns that hold nothing on any row of the sheet are dropped **before** the text is built, so a workbook that
    prints its quantities in column 33 does not lose them to a column cap (that is exactly how the first version of
    this function hid every UOM and every quantity from the model). Positions stay consistent between rows.
    """
    sheets = sheet_rows(filename, data)
    if not sheets:
        return ""
    out: list[str] = []
    for n, rows in enumerate(sheets, 1):
        if not rows:
            continue
        if len(sheets) > 1:
            out.append(f"--- sheet {n} ---")
        used = sorted({j for row in rows for j, v in row if _cell(v) != ""})
        if len(used) > max_cols:
            used = used[:max_cols]
        pos = {j: i for i, j in enumerate(used)}
        for row in rows[:max_rows]:
            cells: dict[int, str] = {}
            width = 0
            for j, v in row:
                i = pos.get(j)
                if i is None:
                    continue
                text = _cell(v)[:120]
                if text:
                    cells[i] = text
                    width = max(width, i + 1)
            line = " | ".join(cells.get(i, "") for i in range(width))
            if line.strip(" |"):
                out.append(line)
        if len(rows) > max_rows:
            out.append(f"... {len(rows) - max_rows} more row(s) not shown")
        text = "\n".join(out)
        if len(text) > max_chars:
            return text[:max_chars] + "\n... truncated"
    return "\n".join(out)


# ───────────────────────── the BOM table ─────────────────────────

_HEAD = {
    "item_code": (r"^item( ?(code|no|#))?$", r"^code$", r"^article$", r"^material( code)?$"),
    "category": (r"^categor(y|ies)$", r"^type$", r"^material type$", r"^component$"),
    "description": (r"^desc(ription)?$", r"^item description$", r"^material description$"),
    "colour": (r"^colou?r$", r"^colou?r code$"),
    "colour_desc": (r"^colou?r desc(ription)?$",),
    "size": (r"^size$",),
    "uom": (r"^uom$", r"^unit$", r"^units?$", r"^u/m$"),
    "consumption": (r"qty ?/ ?(garment|pc|piece|gmt)", r"^quantity required$", r"^consumption$", r"^cons\.?$", r"^qty$",
                    r"^yield$", r"^usage$", r"^qty per (garment|pc|piece)$", r"^quantity$"),
    "rate": (r"^unit cost$", r"^rate$", r"^price$", r"^unit price$", r"^cost$"),
    "job_code": (r"^job code$",),
    "remarks": (r"^remarks?$", r"^notes?$", r"^comments?$"),
    "placement": (r"^placement$", r"^position$", r"^location$"),
    "supplier": (r"^supplier$", r"^vendor$", r"^mill$"),
}


def _head_key(text: str) -> Optional[str]:
    t = re.sub(r"\s+", " ", text.replace("\n", " ")).strip().lower().rstrip(":")
    for key, pats in _HEAD.items():
        if any(re.search(p, t) for p in pats):
            return key
    return None


def _find_header(rows) -> tuple[int, dict[int, str]]:
    best = (-1, {})
    for i, row in enumerate(rows[:80]):
        cols = {}
        for j, v in row:
            k = _head_key(_cell(v))
            if k and k not in cols.values():
                cols[j] = k
        if len(cols) >= 3 and ("description" in cols.values() or "item_code" in cols.values()) and len(cols) > len(best[1]):
            best = (i, cols)
    return best


def _nearest(col: int, heads: dict[int, str]) -> Optional[str]:
    if not heads:
        return None
    if col in heads:
        return heads[col]
    j = min(heads, key=lambda h: (abs(h - col), h > col))    # nearest heading; on a tie, the one to the left
    return heads[j] if abs(j - col) <= 3 else None


_TYPE_WORDS = [
    ("Fusing", r"\bfus(e|ing)\b|^fus\d"), ("Thread", r"\bthread\b|^th\d"), ("Label", r"\blabel\b|\bsize tab\b|\bhang ?tag\b|^(lb|st|cl)\d"),
    ("Packaging", r"\bpoly ?bag\b|\bcarton\b|\bpacking\b|\bprice ticket\b|\bhanger\b|\btissue\b|^(pb|pt|ct)\d"),
    ("Lining", r"\blining\b"), ("Contrast Fabric", r"\bcontrast\b|\(content-?\d\)"),
    ("Fabric", r"\bfabric\b|\(self\)|\bshell\b|\blyocell\b|\bcotton\b|\blinen\b|\bpolyester\b|\bdenim\b|\btwill\b|\bpoplin\b|\bjersey\b"),
    ("Trim", r"\bbutton\b|\bzip(per)?\b|\bsnap\b|\brivet\b|\belastic\b|\bdrawcord\b|\btape\b|\bhook\b|\beyelet\b|\bbt\d"),
]
_CATEGORY = {"fabric": "Fabric", "fusing": "Fusing", "interlining": "Fusing", "thread": "Thread", "threads": "Thread", "label": "Label",
             "labels": "Label", "packing": "Packaging", "packaging": "Packaging", "lining": "Lining", "buttons": "Trim", "button": "Trim",
             "trim": "Trim", "trims": "Trim", "zipper": "Trim", "accessories": "Trim"}


def material_type(category: str, code: str, desc: str) -> str:
    c = (category or "").strip().lower()
    if c in _CATEGORY:
        return _CATEGORY[c]
    text = f"{(code or '').lower()} {(desc or '').lower()}"
    for kind, pat in _TYPE_WORDS:
        if re.search(pat, text):
            return kind
    return "Other"


_UOM = {"yd": "Yard", "yds": "Yard", "yard": "Yard", "yards": "Yard", "m": "Meter", "mtr": "Meter", "meter": "Meter", "metre": "Meter",
        "ea": "Nos", "pc": "Nos", "pcs": "Nos", "pi": "Nos", "nos": "Nos", "each": "Nos", "set": "Set", "sets": "Set", "cone": "Nos",
        "kg": "Kg", "gm": "Gram", "g": "Gram", "doz": "Dozen", "dz": "Dozen", "cm": "Cm", "inch": "Inch", "in": "Inch"}


def norm_uom(u: str) -> str:
    u = (u or "").strip().strip("()").lower()
    return _UOM.get(u, "")


def _num(v) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"^\s*(\d+(?:[.,]\d+)?)\s*$", _cell(v))
    return float(m.group(1).replace(",", ".")) if m else None


_KV = re.compile(r"^(style( no| #| number| code)?|description|style name|colou?r|season|fabric( content)?|content|enquiry ref|inquiry ref|"
                 r"ref(erence)?|date|status|buyer|customer|size( range)?|brand|division|gsm|width)\s*:?\s*$", re.I)


def _header_block(rows, stop: int) -> dict:
    """``Style: C9112-U71-701`` style pairs above the table (the value may sit many columns to the right)."""
    out: dict[str, str] = {}
    for row in rows[: max(stop, 0) if stop >= 0 else 30]:
        cells = [(j, _cell(v)) for j, v in row]
        for i, (j, t) in enumerate(cells):
            if _KV.match(t) and i + 1 < len(cells):
                key = re.sub(r"[^a-z]+", "_", t.lower().rstrip(":").strip()).strip("_")
                vals = [x for _, x in cells[i + 1:] if not _KV.match(x)][:2]
                if vals and key not in out:
                    out[key] = " - ".join(vals) if key.startswith("colo") and len(vals) == 2 else vals[0]
    return out


def read_bom(filename: str, data: bytes) -> dict:
    """One BOM sheet → ``{ok, style, header, rows, warnings}``. ``rows`` carry the buyer's item code, a material type, the
    description, colour, UOM and the consumption per garment."""
    sheets = sheet_rows(filename, data)
    if not sheets:
        return {"ok": False, "error": "unreadable", "rows": [], "header": {}, "style": "", "warnings": []}
    best = None
    for rows in sheets:
        hi, heads = _find_header(rows)
        if hi >= 0 and (best is None or len(heads) > len(best[2])):
            best = (rows, hi, heads)
    if best is None:
        return {"ok": False, "error": "no_table", "rows": [], "header": _header_block(sheets[0], 30), "style": "", "warnings": []}
    rows, hi, heads = best
    header = _header_block(rows, hi)
    out, warnings = [], []
    for row in rows[hi + 1:]:
        rec: dict[str, object] = {}
        for j, v in row:
            k = _nearest(j, heads)
            if k and k not in rec:
                rec[k] = v
        text = " ".join(_cell(v) for _, v in row).lower()
        if not rec.get("description") and not rec.get("item_code"):
            continue
        if re.match(r"^(total|fabric\s+trim|pricing|dummy|note)", text) or ("fabric" in text and "trim" in text and "total" in text):
            continue
        desc = _cell(rec.get("description"))
        code = _cell(rec.get("item_code"))
        if code and not desc:
            desc, code = code, ""
        cons = _num(rec.get("consumption"))
        uom_raw = _cell(rec.get("uom"))
        if not norm_uom(uom_raw):                      # the export sometimes drops the UOM into the job-code column
            alt = _cell(rec.get("job_code"))
            if norm_uom(alt):
                uom_raw = alt
        r = {"item_code": code, "material_type": material_type(_cell(rec.get("category")), code, desc), "description": desc[:140],
             "colour": _cell(rec.get("colour_desc")) or _cell(rec.get("colour")), "uom": norm_uom(uom_raw) or uom_raw[:12],
             "consumption": cons, "rate": _num(rec.get("rate")), "remarks": _cell(rec.get("remarks"))[:200],
             "placement": _cell(rec.get("placement"))[:80], "supplier": _cell(rec.get("supplier"))[:80]}
        if cons is None:
            warnings.append(f"No quantity per garment for {desc or code}")
        out.append(r)
    # the same item twice (BT088 on two lines: 1 + 7) is kept as two lines, as the buyer wrote it, but flagged
    seen: dict[str, int] = {}
    for r in out:
        k = f"{r['item_code']}|{r['description']}".lower()
        seen[k] = seen.get(k, 0) + 1
    for k, n in seen.items():
        if n > 1 and k.split("|")[0]:
            warnings.append(f"{k.split('|')[0].upper()} appears on {n} lines; the requisition adds them together")
    company = ""
    for row in rows[:4]:                               # a title row holding only the buyer's company name
        if len(row) == 1:
            t = _cell(row[0][1])
            if re.search(r"\b(co\.?|llc|inc\.?|ltd\.?|limited|group|apparel|fashion|clothing|garments?)\s*$", t, re.I) and len(t) < 80:
                company = t.title() if t.isupper() else t
                break
    style = header.get("style") or header.get("style_no") or header.get("style_code") or header.get("style_number") or ""
    if not style:
        m = STYLE_RE.search(filename or "")
        style = m.group(0) if m else ""
    return {"ok": bool(out), "style": style.strip(), "header": header, "rows": out, "warnings": warnings, "company": company}


# ───────────────────────── styles in the mail ─────────────────────────

#: a garment style code: letters and digits in 2–4 hyphenated groups, at least one letter-digit group (C9112-U71-701,
#: AO-5644, 4602757726 is NOT one). Codes that sit inside a BOM description (button #J5031-FL) are not styles.
STYLE_RE = re.compile(r"\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z]{1,4}\d{2,6}(?:-[A-Z0-9]{2,6}){1,3}\b")


def style_codes(text: str) -> list[str]:
    seen, out = set(), []
    for m in STYLE_RE.finditer((text or "").upper()):
        c = m.group(0)
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _qty(s: str) -> Optional[int]:
    m = re.search(r"(\d{1,3}(?:,\d{3})+|\d+)\s*(k\b|pcs|pieces|units|pc\b|nos)?", s or "", re.I)
    if not m:
        return None
    n = int(m.group(1).replace(",", ""))
    return n * 1000 if (m.group(2) or "").lower() == "k" else n


def _join_wrapped(lines: list[str]) -> list[str]:
    """Mail clients wrap long table rows. A line belongs to the row above when it starts with ``|``, or when it names no
    style while the row above still has fewer cells than the table's header."""
    out: list[str] = []
    width = 0
    for ln in lines:
        s = ln.rstrip()
        cells = s.count("|") + 1 if "|" in s else 0
        if "|" in s and re.search(r"(^|\|)\s*style\b", s, re.I):
            width = max(width, cells)
        prev = out[-1] if out else ""
        prev_cells = prev.count("|") + 1 if "|" in prev else 0
        cont = bool(out) and s.strip() and not STYLE_RE.search(s.upper()) and (
            s.lstrip().startswith("|") or (prev_cells and width and prev_cells < width))
        if cont:
            out[-1] = prev.rstrip() + " " + s.strip()
        else:
            out.append(s)
        if re.search(r"(^|\|)\s*style\b", out[-1], re.I):       # the header itself can wrap ("| Est. qty")
            width = max(width, out[-1].count("|") + 1)
    return out


def styles_from_body(body: str) -> list[dict]:
    """``Style | Description | Color | Fabric | Est. qty`` tables in the mail text, or one style + "for N pieces"."""
    lines = _join_wrapped((body or "").splitlines())
    header, out = None, []
    for ln in lines:
        if "|" not in ln:
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        low = [c.lower() for c in cells]
        if any(c.startswith("style") for c in low) and len(cells) >= 2:
            header = low
            continue
        codes = style_codes(cells[0]) if cells else []
        if not codes:
            continue
        rec = {"style_no": codes[0]}
        for i, c in enumerate(cells[1:], start=1):
            h = header[i] if header and i < len(header) else ""
            if "desc" in h or "name" in h:
                rec["style_name"] = c
            elif "col" in h:
                rec["colour"] = c
            elif "fab" in h or "content" in h:
                rec["fabric"] = c
            elif "qty" in h or "quantity" in h or "pcs" in h:
                q = _qty(c)
                if q:
                    rec["qty"] = q
            elif not header:
                if _qty(c) and re.fullmatch(r"[\d,\s]+(pcs|pieces)?", c, re.I):
                    rec["qty"] = _qty(c)
                elif "%" in c:
                    rec["fabric"] = c
        out.append(rec)
    if out:
        return out
    # no table: styles named in the text, and "for 1000 pieces" when there is exactly one
    codes = style_codes(body)
    qty = None
    m = re.search(r"(\d{1,3}(?:,\d{3})+|\d{2,7})\s*(pcs|pieces|units|garments)\b", body or "", re.I)
    if m:
        qty = int(m.group(1).replace(",", ""))
    return [{"style_no": c, **({"qty": qty} if qty and len(codes) == 1 else {})} for c in codes]


_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"


_DATE = r"(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+(?:" + _MONTHS + r")[a-z]*\s+\d{4})"


def dates_from_body(body: str) -> dict:
    """X-factory / in-warehouse dates exactly as written (``02/11/2027``); never resolved when ambiguous.

    A date is given to the keyword closest to it, written before ("02/11/2027 X-factory") or after ("ex-factory: 02/11")."""
    out = {}
    text = body or ""
    for key, kw in (("ex_factory", r"(?:x|ex)[- ]?factory"), ("in_warehouse", r"in[- ]?(?:warehouse|dc|store)")):
        cands = []
        for m in re.finditer(_DATE + r"[\s,]{0,3}" + kw, text, re.I):
            cands.append((len(m.group(0)) - len(m.group(1)), m.group(1)))
        for m in re.finditer(kw + r"(?:\s*date)?\s*[:=-]?\s{0,3}(?:on|by|of)?\s{0,2}" + _DATE, text, re.I):
            cands.append((len(m.group(0)) - len(m.group(1)), m.group(1)))
        if cands:
            out[key] = min(cands)[1]
    return out


def iso_date(raw: str) -> tuple[str, bool]:
    """``(YYYY-MM-DD, ambiguous)``. US order (month first) is assumed for ``nn/nn/yyyy`` only when the first number
    cannot be a month; otherwise the reading is flagged ambiguous so a person confirms it."""
    raw = (raw or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", raw)
    if m:
        return raw, False
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$", raw)
    if not m:
        return "", True
    a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y = y + 2000 if y < 100 else y
    if a > 12:                      # day first
        d, mo, amb = a, b, False
    elif b > 12:                    # month first
        mo, d, amb = a, b, False
    else:
        mo, d, amb = a, b, a != b   # read month first (the buyers in the mailbox are US), but say it is a guess
    try:
        from datetime import date
        return date(y, mo, d).isoformat(), amb
    except ValueError:
        return "", True


def terms_from_body(body: str) -> dict:
    """Incoterm and destination as the buyer wrote them (``DDP Los Angeles``)."""
    m = re.search(r"\b(FOB|DDP|CIF|CFR|EXW|FCA|DAP|CIP|DDU|LDP)\b\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2})?", body or "")
    if not m:
        return {}
    out = {"incoterm": m.group(1).upper()}
    if m.group(2) and m.group(2).lower() not in ("by", "price", "prices", "port"):
        out["destination"] = m.group(2).strip()
    return out


def season_from(text: str) -> str:
    m = re.search(r"\b(spring|summer|fall|autumn|winter|holiday|resort|ss|fw|aw|sp|su|fa|ho)\s*[-/ ]?\s*'?(20\d{2}|\d{2})\b", text or "", re.I)
    if not m:
        return ""
    word, yr = m.group(1), m.group(2)
    yr = yr if len(yr) == 4 else "20" + yr
    return f"{word.upper()} {yr}"


_SIZE_RANGE = re.compile(r"\b(XXS|XS|S|M|L|XL|XXL|2XL|3XL)\s*(?:-|to|–)\s*(XXS|XS|S|M|L|XL|XXL|2XL|3XL)\b", re.I)
_SIZE_ORDER = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "2XL", "3XL"]


def sizes_from(text: str) -> list[str]:
    m = _SIZE_RANGE.search(text or "")
    if not m:
        return []
    a, b = m.group(1).upper(), m.group(2).upper()
    if a in _SIZE_ORDER and b in _SIZE_ORDER and _SIZE_ORDER.index(a) <= _SIZE_ORDER.index(b):
        return _SIZE_ORDER[_SIZE_ORDER.index(a): _SIZE_ORDER.index(b) + 1]
    return []
