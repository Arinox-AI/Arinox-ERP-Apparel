"""Document reader — turn an email attachment into text, with no third-party deps.

The runtime has no ``pypdf`` / ``openpyxl`` / ``xlrd`` / ``pandas`` (verified
2026-11-03), and installing them is not an option for a deployed app. It does
have ``zlib``, ``zipfile``, ``base64`` and ``re`` — which is enough to read the
documents a buyer actually sends:

    PDF (text layer)   FlateDecode + ASCII85 streams, text operators with positions
    XLSX               zip -> sharedStrings.xml + sheetN.xml  (sheet -> TSV)
    CSV / TSV          decoded, delimiter sniffed
    TXT / HTML body    tags stripped

Design rules
------------
* **Never guess.** A PDF that yields fewer than ``MIN_PDF_CHARS`` characters is a
  *scan*: ``needs_ocr`` is set, the text is empty, and the caller routes it to a
  human. Reading a scan by hoping is how a wrong quantity enters the ERP.
* **Nothing raises.** Every reader returns the same shape:

      {"ok": bool, "text": str, "parser": str, "pages": int,
       "chars": int, "needs_ocr": bool, "error": str}

* Layout matters. PDF text is emitted in drawing order, so the tokens are grouped
  by their y position and sorted by x — otherwise a PO's colour table interleaves
  into a single unreadable line.
"""

from __future__ import annotations

import base64
import csv
import io
import re
import zipfile
import zlib
from html import unescape

MIN_PDF_CHARS = 200          # below this a PDF is treated as a scan
MAX_TEXT_CHARS = 400_000     # a hard cap: no attachment may blow up the prompt

TEXT_EXTS = (".txt", ".text", ".md", ".eml")
CSV_EXTS = (".csv", ".tsv")
XLSX_EXTS = (".xlsx", ".xlsm")
PDF_EXTS = (".pdf",)


def _result(ok: bool, text: str = "", parser: str = "", pages: int = 0,
            needs_ocr: bool = False, error: str = "") -> dict:
    text = (text or "")[:MAX_TEXT_CHARS]
    return {"ok": bool(ok), "text": text, "parser": parser, "pages": int(pages),
            "chars": len(text), "needs_ocr": bool(needs_ocr), "error": error or "",
            "layout": []}


# ────────────────────────────────────────────────────────────────────────────
# PDF
# ────────────────────────────────────────────────────────────────────────────
_OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj(.*?)endobj", re.S)
# NB: the trailing newline before ``endstream`` is optional — ReportLab emits ``...~>endstream``.
_STREAM_RE = re.compile(rb"stream\r?\n(.*?)endstream", re.S)
_PDF_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
                b"(": b"(", b")": b")", b"\\": b"\\"}


def _pdf_unescape(raw: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(raw):
        c = raw[i:i + 1]
        if c != b"\\":
            out += c
            i += 1
            continue
        nxt = raw[i + 1:i + 2]
        if not nxt:
            break
        if nxt in _PDF_ESCAPES:
            out += _PDF_ESCAPES[nxt]
            i += 2
            continue
        if nxt.isdigit():                      # octal \ddd
            oct_digits = raw[i + 1:i + 4]
            m = re.match(rb"[0-7]{1,3}", oct_digits)
            if m:
                out.append(int(m.group(0), 8) & 0xFF)
                i += 1 + len(m.group(0))
                continue
        if nxt in (b"\n", b"\r"):              # line continuation
            i += 2
            continue
        out += nxt
        i += 2
    return bytes(out)


def _decode_stream(raw: bytes, header: bytes) -> bytes:
    """Undo the stream filters PDF writers use for text pages."""
    data = raw
    filters = header or b""
    # ASCII85 first (it wraps the flate payload in ReportLab output)
    if b"ASCII85" in filters or (data[:2] not in (b"x\x9c", b"\x78\xda") and b"~>" in data[-8:]):
        try:
            data = base64.a85decode(data.strip(), adobe=not data.strip().startswith(b"<~"), ignorechars=b" \n\r\t")
        except Exception:
            try:
                data = base64.a85decode(data.strip(), adobe=True)
            except Exception:
                pass
    if b"FlateDecode" in filters or data[:1] == b"x":
        try:
            data = zlib.decompress(data)
        except Exception:
            try:
                data = zlib.decompressobj().decompress(data)
            except Exception:
                pass
    return data


def _content_text(content: bytes, tokens_out: list | None = None) -> tuple[str, int]:
    """Extract positioned text from one content stream.

    Returns ``(text, page_count_hint)``. Positions come from ``Tm`` / ``Td`` /
    ``TD`` / ``T*``; tokens are then grouped by line and ordered left to right.
    """
    # (y, x, text)
    tokens: list[tuple[float, float, str]] = []
    x = y = 0.0
    for m in re.finditer(rb"(BT|ET|Tm|Td|TD|T\*|Tj|TJ|'|\")", content):
        op = m.group(1)
        if op in (b"BT", b"ET"):
            continue
        chunk = content[max(0, m.start() - 400):m.start()]
        if op in (b"Tm",):
            nums = re.findall(rb"(-?\d*\.?\d+)", chunk)[-6:]
            if len(nums) == 6:
                try:
                    x, y = float(nums[4]), float(nums[5])
                except Exception:
                    pass
        elif op in (b"Td", b"TD"):
            nums = re.findall(rb"(-?\d*\.?\d+)", chunk)[-2:]
            if len(nums) == 2:
                try:
                    x += float(nums[0])
                    y += float(nums[1])
                except Exception:
                    pass
        elif op == b"T*":
            y -= 12
        if op in (b"Tj", b"'", b'"'):
            s = _last_pdf_string(m, content)
            if s:
                tokens.append((y, x, s))
        elif op == b"TJ":
            arr = _last_pdf_array(m, content)
            if arr:
                tokens.append((y, x, arr))
    if tokens_out is not None:
        # a compact, page-1-sized trace of where every string sits — this is what
        # lets a size grid be read by COLUMN position instead of by guessing
        for ty, tx, text in tokens:
            if text.strip():
                tokens_out.append([round(ty, 1), round(tx, 1), text.strip()[:80]])
    if not tokens:
        return "", 0

    lines: dict[float, list[tuple[float, str]]] = {}
    for ty, tx, text in tokens:
        key = round(ty / 3) * 3          # tolerate tiny baseline drift
        lines.setdefault(key, []).append((tx, text))
    out = []
    for key in sorted(lines, reverse=True):
        parts = sorted(lines[key], key=lambda p: p[0])
        joined = ""
        prev_x, prev_text = None, ""
        for tx, text in parts:
            if joined:
                gap = tx - (prev_x or 0) - len(prev_text) * 4.6      # ~Helvetica 9pt advance
                if gap > 30:
                    joined += " | "                                  # keep table columns apart
                elif not joined.endswith((" ", "-", "/")) and not text.startswith((" ", ",", ".")):
                    joined += " "
            joined += text
            prev_x, prev_text = tx, text
        joined = re.sub(r"[ \t]{2,}", " ", joined).strip()
        if joined:
            out.append(joined)
    return "\n".join(out), 1


def _last_pdf_string(m, content: bytes) -> str:
    """The literal string that belongs to the operator at ``m``."""
    head = content[:m.start()]
    # walk backwards to the nearest unescaped '(' and match forward
    idx = head.rfind(b"(")
    if idx < 0:
        return ""
    depth, i, buf = 1, idx + 1, bytearray()
    while i < len(content):
        c = content[i:i + 1]
        if c == b"\\":
            buf += content[i:i + 2]
            i += 2
            continue
        if c == b"(":
            depth += 1
        elif c == b")":
            depth -= 1
            if depth == 0:
                break
        buf += c
        i += 1
    return _pdf_unescape(bytes(buf)).decode("latin-1")


def _last_pdf_array(m, content: bytes) -> str:
    head = content[:m.start()]
    idx = head.rfind(b"[")
    if idx < 0:
        return ""
    end = head.rfind(b"]")
    if end <= idx:
        return ""
    blob = head[idx:end + 1]
    pieces = re.findall(rb"\(((?:[^()\\]|\\.)*)\)", blob)
    return "".join(_pdf_unescape(p).decode("latin-1") for p in pieces)


def read_pdf(data: bytes, with_layout: bool = True) -> dict:
    """Text layer of a PDF. A scan returns ``needs_ocr`` instead of nothing."""
    if not data[:5] == b"%PDF-":
        return _result(False, error="not a pdf")
    pages, chunks, saw_stream = 0, [], False
    layout: list = []
    for m in _OBJ_RE.finditer(data):
        header = m.group(3)
        if b"/Image" in header or b"/XObject" in header and b"/Subtype /Form" not in header:
            continue
        sm = _STREAM_RE.search(header)
        if not sm:
            continue
        saw_stream = True
        decoded = _decode_stream(sm.group(1), header)
        if b"BT" not in decoded:
            continue
        page_tokens: list = []
        text, n = _content_text(decoded, page_tokens if with_layout and len(layout) < 4000 else None)
        for ty, tx, t in page_tokens:
            layout.append([pages, ty, tx, t])
        if text:
            chunk = "\n".join(l for l in text.splitlines() if l.strip())
            if chunk.strip():
                chunks.append(chunk)
                pages += n
    text = "\n".join(chunks).strip()
    # de-duplicate: some writers repeat a page in a form XObject
    if text.count("\n") > 40:
        seen, uniq = set(), []
        for line in text.splitlines():
            k = line.strip().lower()
            if k and k in seen:
                continue
            seen.add(k)
            uniq.append(line)
        text = "\n".join(uniq)
    text = re.sub(r"[ \t]{2,}", " ", text)
    if len(text) < MIN_PDF_CHARS:
        out = _result(False, text=text, parser="pdf", pages=pages, needs_ocr=saw_stream,
                      error="scan_or_image_only" if saw_stream else "no_text_layer")
        out["layout"] = layout[:4000]
        return out
    out = _result(True, text=text, parser="pdf", pages=max(pages, 1))
    out["layout"] = layout[:4000]
    return out


# ────────────────────────────────────────────────────────────────────────────
# XLSX (zip + XML, no openpyxl)
# ────────────────────────────────────────────────────────────────────────────
_TAG_RE = re.compile(r"<[^>]+>")


def _xml_text(xml: str) -> str:
    return unescape(_TAG_RE.sub("", xml))


def _col_index(ref: str) -> int:
    letters = re.match(r"([A-Z]+)", ref or "")
    if not letters:
        return 0
    n = 0
    for ch in letters.group(1):
        n = n * 26 + (ord(ch) - 64)
    return max(n - 1, 0)


def read_xlsx(data: bytes) -> dict:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception as e:
        return _result(False, error=f"not a zip: {e}")
    shared: list[str] = []
    try:
        if "xl/sharedStrings.xml" in zf.namelist():
            raw = zf.read("xl/sharedStrings.xml").decode("utf-8", "replace")
            for si in re.findall(r"<si>(.*?)</si>", raw, re.S):
                shared.append(_xml_text("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S))))
    except Exception:
        shared = []
    sheets = sorted(n for n in zf.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
    if not sheets:
        return _result(False, error="no worksheets")
    blocks = []
    for sheet in sheets[:6]:
        try:
            raw = zf.read(sheet).decode("utf-8", "replace")
        except Exception:
            continue
        rows_out = []
        for row in re.findall(r"<row[^>]*>(.*?)</row>", raw, re.S):
            cells: dict[int, str] = {}
            for cm in re.finditer(r"<c\b([^>]*)>(.*?)</c>", row, re.S):
                attrs, body = cm.group(1), cm.group(2)
                ref = re.search(r'r="([A-Z]+\d+)"', attrs)
                col = _col_index(ref.group(1)) if ref else len(cells)
                is_str = 't="s"' in attrs
                is_inline = 't="inlineStr"' in attrs
                v = re.search(r"<v[^>]*>(.*?)</v>", body, re.S)
                val = ""
                if v:
                    val = v.group(1)
                    if is_str:
                        try:
                            val = shared[int(val)]
                        except Exception:
                            val = ""
                    else:
                        val = _xml_text(val)
                elif is_inline:
                    val = _xml_text("".join(re.findall(r"<t[^>]*>(.*?)</t>", body, re.S)))
                if val not in ("", None):
                    cells[col] = val.strip()
            if cells:
                width = max(cells) + 1
                rows_out.append("\t".join(cells.get(i, "") for i in range(width)))
        if rows_out:
            blocks.append(f"## {sheet.split('/')[-1]}\n" + "\n".join(rows_out))
    text = "\n".join(blocks).strip()
    if not text:
        return _result(False, parser="xlsx", error="empty workbook")
    return _result(True, text=text, parser="xlsx", pages=len(blocks))


# ────────────────────────────────────────────────────────────────────────────
# CSV / plain / html
# ────────────────────────────────────────────────────────────────────────────
def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode("utf-8", "replace")


def read_csv(data: bytes, name: str = "") -> dict:
    raw = _decode(data)
    delim = ","
    try:
        sample = raw[:4000]
        counts = {d: sample.count(d) for d in (",", ";", "\t", "|")}
        delim = max(counts, key=counts.get) if counts else ","
        if counts.get(delim, 0) == 0:
            delim = ","
    except Exception:
        delim = ","
    try:
        rows = list(csv.reader(io.StringIO(raw), delimiter=delim))
        text = "\n".join("\t".join(c.strip() for c in row) for row in rows if any(x.strip() for x in row))
    except Exception:
        text = raw
    if not text.strip():
        return _result(False, parser="csv", error="empty")
    return _result(True, text=text, parser="csv", pages=1)


def read_text(data: bytes) -> dict:
    text = _decode(data)
    if not text.strip():
        return _result(False, parser="text", error="empty")
    return _result(True, text=text, parser="text", pages=1)


def html_to_text(html: str) -> str:
    """Body of an HTML mail -> readable lines (tables become TSV-ish rows)."""
    if not html:
        return ""
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    h = re.sub(r"(?i)</(p|div|tr|li|h[1-6]|br)\s*>", "\n", h)
    h = re.sub(r"(?i)</t[dh]\s*>", "\t", h)
    h = re.sub(r"(?i)<br\s*/?>", "\n", h)
    text = unescape(_TAG_RE.sub("", h))
    text = re.sub(r"[ \t\u00a0]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(l.strip() for l in text.splitlines() if l.strip())


# ────────────────────────────────────────────────────────────────────────────
# Legacy .xls, and containers (.docx / .zip / .eml) — added 2026-11-07
# ────────────────────────────────────────────────────────────────────────────
def read_xls(data: bytes) -> dict:
    """Legacy Excel (BIFF8). Read by ``xlsread`` (pure Python, always present); ``xlrd`` only when the file is
    older than Excel 97. Nothing to install, so the box that serves the app reads the buyer's sheet."""
    try:
        import xlsread
        text = xlsread.sheets_as_text(data)
        if not text.strip():
            return _result(False, parser="xls", error="empty")
        return _result(True, text=text, parser="xls", pages=text.count("## Sheet"))
    except Exception as e:                                                  # noqa: BLE001
        old_biff = "older than Excel 97" in str(e)
        if not old_biff:
            return _result(False, parser="xls", error=f"xls_unreadable: {type(e).__name__}")
    try:
        import xlrd                                   # only for a BIFF5/7 file, which is rare now
    except Exception:
        return _result(False, parser="xls",
                       error="legacy_xls_not_readable — the sheet is older than Excel 97 and no reader for that format is installed; ask the buyer for .xlsx or .csv")
    try:
        book = xlrd.open_workbook(file_contents=data)
        out = []
        for sheet in book.sheets():
            out.append(f"## {sheet.name}")
            for r in range(sheet.nrows):
                cells = [str(c.value).strip() for c in sheet.row(r)]
                if any(cells):
                    out.append("\t".join(cells))
        text = "\n".join(out)
        if not text.strip():
            return _result(False, parser="xls", error="empty")
        return _result(True, text=text, parser="xls", pages=book.nsheets)
    except Exception as e:                                                  # noqa: BLE001
        return _result(False, parser="xls", error=f"xls_unreadable: {type(e).__name__}")


def _read_container(filename: str, mime: str, data: bytes, kind: str) -> dict:
    """A .docx, a .zip of documents, or a forwarded .eml → one text result.

    The readers live in ``inquiry_v2`` (zip-bomb limits, nested-depth limit, skips __MACOSX); they
    are reused here so the order intake and the inquiry reader understand the same formats.
    """
    import inquiry_v2                                 # lazy: inquiry_v2 imports this module
    parts = inquiry_v2.read_any(filename, mime, data)
    good = [p for p in parts if p.get("ok") and (p.get("text") or "").strip()]
    if kind == "docx" and len(parts) == 1:
        p = parts[0]
        return _result(bool(good), text=p.get("text") or "", parser="docx", pages=1, error=p.get("error") or "")
    blocks = []
    for p in good:
        blocks.append(f"=== {p.get('filename') or kind} ===\n{p['text']}")
    unread = [f"{p.get('filename') or '?'} ({p.get('error') or 'unreadable'})" for p in parts if p not in good]
    text = "\n\n".join(blocks)
    out = _result(bool(good), text=text, parser=kind, pages=len(good),
                  needs_ocr=any(p.get("needs_reading") for p in parts),
                  error="" if good else ("nothing readable inside: " + "; ".join(unread[:5]))[:200])
    if unread and good:
        out["error"] = ("not read: " + "; ".join(unread[:5]))[:200]
    return out


# ────────────────────────────────────────────────────────────────────────────
# Dispatcher
# ────────────────────────────────────────────────────────────────────────────
def read_attachment(filename: str, mime: str, data: bytes) -> dict:
    """Read one attachment. Shape is identical for every type."""
    name = (filename or "").lower()
    mime = (mime or "").lower()
    if not data:
        return _result(False, parser="", error="empty_attachment")
    try:
        if name.endswith(PDF_EXTS) or "pdf" in mime:
            return read_pdf(data)
        if name.endswith(XLSX_EXTS) or "spreadsheetml" in mime:
            return read_xlsx(data)
        if name.endswith((".xls",)) or mime == "application/vnd.ms-excel":
            return read_xls(data)
        if name.endswith(CSV_EXTS) or "csv" in mime:
            return read_csv(data, name)
        # .eml BEFORE the generic text branch: a forwarded mail carries its own attachments
        if name.endswith(".eml") or mime == "message/rfc822":
            return _read_container(filename, mime, data, "eml")
        if name.endswith(TEXT_EXTS) or mime.startswith("text/"):
            return read_text(data)
        if name.endswith(".docx") or "wordprocessingml" in mime:
            return _read_container(filename, mime, data, "docx")
        if name.endswith(".doc") or mime == "application/msword":
            return _result(False, parser="doc",
                           error="legacy_doc_not_readable — ask the buyer for .docx or .pdf")
        if name.endswith(".zip") or mime in ("application/zip", "application/x-zip-compressed"):
            return _read_container(filename, mime, data, "zip")
        if mime.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp")):
            return _result(False, parser="image", needs_ocr=True,
                           error="image_attachment — a scan; a person must read it (no OCR tool is connected)")
    except Exception as e:                     # never raise into the caller
        return _result(False, parser="", error=f"{type(e).__name__}: {e}"[:200])
    return _result(False, parser="", error=f"unsupported_type {mime or name}")
