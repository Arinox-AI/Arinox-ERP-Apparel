"""Legacy Excel (``.xls``, BIFF8) reader with **no third-party dependency**.

Why this file exists (2026-11-07): ``bom_reader`` read ``.xls`` through ``xlrd``, and ``docread`` did the
same. On the machine where the Tower actually runs, ``import xlrd`` fails — so a real buyer sheet
(``C9043-U70-629.xls``, the STY360 export) came back as *"could not be opened"* even though the bytes were
on disk and perfectly readable, and the mail's attachment was filed as
*"this server has no .xls reader; ask the buyer for .xlsx"*. Asking the buyer is not an answer: the buyer
sends what their system prints.

So the reading is done here instead, in pure Python, with nothing to install:

* :class:`_Cfb` — the Compound File Binary container (an OLE2 "structured storage" file): header, FAT,
  DIFAT, directory, mini stream and mini FAT. Enough to hand back the ``Workbook`` stream as bytes.
* :func:`read_sheets` — the BIFF8 records that carry cells: ``LABELSST``, ``LABEL``, ``NUMBER``, ``RK``,
  ``MULRK``, ``FORMULA`` (+``STRING``), ``BOOLERR``, ``SST`` (+``CONTINUE``), ``BOUNDSHEET``.

What it deliberately does not do: number formats, dates, formulas (a formula comes back as its cached
result), colours, merged cells, encryption. A BOM sheet needs text and numbers, and that is what comes out.

``read_sheets`` returns the same shape ``xlrd`` gives us in ``bom_reader.sheet_rows``:
``[[ (col, value), ... ], ...]`` per sheet, non-empty cells only, in sheet order. Anything it cannot read
raises :class:`XlsError` — never a silent empty sheet, because an empty sheet reads as "no BOM here".
"""

from __future__ import annotations

import struct

# ─────────────────────────── Compound File Binary (OLE2) ───────────────────────────

_FREE = 0xFFFFFFFF
_END = 0xFFFFFFFE
_FATSECT = 0xFFFFFFFD
_DIFSECT = 0xFFFFFFFC


class XlsError(Exception):
    """The bytes are not a legacy Excel file we can read."""


class _Cfb:
    """Minimal reader for the OLE2 container. Only what a BIFF workbook needs."""

    def __init__(self, blob: bytes):
        if len(blob) < 512 or blob[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise XlsError("not a compound file")
        self.blob = blob
        hdr = blob[:512]
        self.ssz = 1 << struct.unpack_from("<H", hdr, 0x1E)[0]        # 512, or 4096 on newer writers
        self.mssz = 1 << struct.unpack_from("<H", hdr, 0x20)[0]       # usually 64
        n_fat = struct.unpack_from("<I", hdr, 0x2C)[0]
        self.dir_start = struct.unpack_from("<I", hdr, 0x30)[0]
        self.mini_cutoff = struct.unpack_from("<I", hdr, 0x38)[0]
        mini_fat_start = struct.unpack_from("<I", hdr, 0x3C)[0]
        n_difat = struct.unpack_from("<I", hdr, 0x48)[0]
        difat_start = struct.unpack_from("<I", hdr, 0x44)[0]

        per = self.ssz // 4
        difat = list(struct.unpack_from("<109I", hdr, 0x4C))
        s, guard = difat_start, 0
        while s not in (_END, _FREE) and guard <= n_difat + 8:
            vals = list(struct.unpack_from("<%dI" % per, self._sector(s), 0))
            difat.extend(vals[:-1])
            s = vals[-1]
            guard += 1

        fat: list[int] = []
        for fs in difat[:n_fat]:
            if fs in (_END, _FREE, _FATSECT, _DIFSECT):
                continue
            fat.extend(struct.unpack_from("<%dI" % per, self._sector(fs), 0))
        self.fat = fat

        # directory
        raw = self._chain(self.dir_start)
        self.entries = []
        for off in range(0, len(raw) - 127, 128):
            e = raw[off:off + 128]
            name_len = struct.unpack_from("<H", e, 0x40)[0]
            name = e[:max(0, name_len - 2)].decode("utf-16-le", "replace") if name_len >= 2 else ""
            self.entries.append({
                "name": name,
                "type": e[0x42],
                "start": struct.unpack_from("<I", e, 0x74)[0],
                "size": struct.unpack_from("<I", e, 0x78)[0],
            })
        root = self.entries[0] if self.entries else {"start": _END, "size": 0}
        self.ministream = self._chain(root["start"], root["size"]) if root["size"] else b""
        self.minifat: list[int] = []
        if mini_fat_start not in (_END, _FREE):
            mraw = self._chain(mini_fat_start)
            self.minifat = list(struct.unpack_from("<%dI" % (len(mraw) // 4), mraw, 0))

    def _sector(self, n: int) -> bytes:
        off = (n + 1) * self.ssz
        if off + self.ssz > len(self.blob) + self.ssz:
            raise XlsError("sector outside the file")
        return self.blob[off:off + self.ssz]

    def _chain(self, start: int, size: int | None = None) -> bytes:
        out, s, guard = [], start, 0
        while s not in (_END, _FREE) and guard <= len(self.fat) + 8:
            out.append(self._sector(s))
            s = self.fat[s] if s < len(self.fat) else _END
            guard += 1
        data = b"".join(out)
        return data[:size] if size is not None else data

    def _mini_chain(self, start: int, size: int) -> bytes:
        out, s, guard = [], start, 0
        while s not in (_END, _FREE) and guard <= len(self.minifat) + 8:
            off = s * self.mssz
            out.append(self.ministream[off:off + self.mssz])
            s = self.minifat[s] if s < len(self.minifat) else _END
            guard += 1
        return b"".join(out)[:size]

    def stream(self, *names: str) -> bytes:
        wanted = [n.lower() for n in names]
        for want in wanted:
            for e in self.entries:
                if e["type"] == 2 and e["name"].lower() == want:
                    if e["size"] < self.mini_cutoff:
                        return self._mini_chain(e["start"], e["size"])
                    return self._chain(e["start"], e["size"])
        raise XlsError("the workbook stream is missing")


# ─────────────────────────── BIFF8 records ───────────────────────────

def _records(buf: bytes, start: int = 0, stop_at_eof: bool = True):
    """Yield ``(offset, type, data)`` for the record stream beginning at ``start``."""
    p, n = start, len(buf)
    while p + 4 <= n:
        rt, rl = struct.unpack_from("<HH", buf, p)
        data = buf[p + 4:p + 4 + rl]
        yield p, rt, data
        p += 4 + rl
        if stop_at_eof and rt == 0x000A:      # EOF
            return


def _rk(v: int) -> float:
    """The RK number: 30 bits of number, flagged for "is integer" and "divide by 100"."""
    if v & 0x02:
        n = v & 0xFFFFFFFC
        if n & 0x80000000:
            n -= 0x100000000
        val = float(n >> 2)
    else:
        val = struct.unpack("<d", struct.pack("<Q", (v & 0xFFFFFFFC) << 32))[0]
    return val / 100.0 if v & 0x01 else val


class _SstReader:
    """Walks an ``SST`` record and its ``CONTINUE`` records.

    A string may be split across record boundaries; each ``CONTINUE`` then starts with one option byte that
    says whether the *rest* of that string is compressed (1 byte per character) or UTF-16 (2 bytes). Getting
    that rule wrong is how shared-string tables turn into mojibake, so it is handled here explicitly.
    """

    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.data = b"".join(chunks)
        self.bounds: list[int] = []
        off = 0
        for c in chunks[:-1]:
            off += len(c)
            self.bounds.append(off)          # data[off] is the option byte of the next CONTINUE
        self.p = 0

    def _next_bound(self) -> int | None:
        for b in self.bounds:
            if b >= self.p:
                return b
        return None

    def _cross(self) -> None:
        """Consume the option byte that opens the next CONTINUE record."""
        self.p += 1

    def rb(self, n: int) -> bytes:
        out = bytearray()
        while n > 0:
            nxt = self._next_bound()
            avail = (nxt - self.p) if nxt is not None else (len(self.data) - self.p)
            take = min(n, avail)
            out += self.data[self.p:self.p + take]
            self.p += take
            n -= take
            if n > 0:
                self._cross()
        return bytes(out)

    def skip(self, n: int) -> None:
        while n > 0:
            nxt = self._next_bound()
            avail = (nxt - self.p) if nxt is not None else (len(self.data) - self.p)
            take = min(n, avail)
            self.p += take
            n -= take
            if n > 0:
                self._cross()

    def chars(self, count: int, compressed: bool) -> str:
        parts: list[str] = []
        while count > 0:
            nxt = self._next_bound()
            avail = (nxt - self.p) if nxt is not None else (len(self.data) - self.p)
            if compressed:
                take = min(count, avail)
                parts.append(self.data[self.p:self.p + take].decode("latin-1"))
                self.p += take
                count -= take
            else:
                take = min(count, avail // 2)
                parts.append(self.data[self.p:self.p + 2 * take].decode("utf-16-le", "replace"))
                self.p += 2 * take
                count -= take
            if count > 0:
                flags = self.data[self.p] if self.p < len(self.data) else 0
                self._cross()
                compressed = bool(flags & 0x01)
        return "".join(parts)


def _parse_sst(chunks: list[bytes]) -> list[str]:
    r = _SstReader(chunks)
    try:
        _total, unique = struct.unpack("<II", r.rb(8))
    except Exception:
        return []
    out: list[str] = []
    for _ in range(unique):
        try:
            cch, grbit = struct.unpack("<HB", r.rb(3))
            rich = grbit & 0x08
            far = grbit & 0x04
            crun = struct.unpack("<H", r.rb(2))[0] if rich else 0
            ext = struct.unpack("<I", r.rb(4))[0] if far else 0
            out.append(r.chars(cch, not (grbit & 0x01)))
            if crun:
                r.skip(4 * crun)
            if ext:
                r.skip(ext)
        except Exception:
            break                              # a truncated table still leaves the strings read so far
    return out


def _biff8_string(data: bytes, off: int = 0) -> str:
    """An ``XLUnicodeString`` inside a record (cch u16, option byte, characters)."""
    if off + 3 > len(data):
        return ""
    cch = struct.unpack_from("<H", data, off)[0]
    grbit = data[off + 2]
    body = data[off + 3:]
    if grbit & 0x01:
        return body[:2 * cch].decode("utf-16-le", "replace")
    return body[:cch].decode("latin-1")


def _short_string(data: bytes, off: int = 0) -> str:
    """A ``ShortXLUnicodeString``: the length is ONE byte (a sheet name, a name record)."""
    if off + 2 > len(data):
        return ""
    cch = data[off]
    grbit = data[off + 1]
    body = data[off + 2:]
    if grbit & 0x01:
        return body[:2 * cch].decode("utf-16-le", "replace")
    return body[:cch].decode("latin-1")


def _globals(wb: bytes) -> tuple[list[tuple[str, int]], list[str]]:
    """Sheet names (with their substream offsets) and the shared-string table."""
    sheets: list[tuple[str, int]] = []
    sst: list[str] = []
    recs = list(_records(wb, 0))
    i = 0
    while i < len(recs):
        _off, rt, data = recs[i]
        if rt == 0x0085 and len(data) >= 8:                       # BOUNDSHEET
            pos = struct.unpack_from("<I", data, 0)[0]
            sheets.append((_short_string(data, 6), pos))
        elif rt == 0x00FC:                                        # SST (+ CONTINUEs)
            chunks = [data]
            j = i + 1
            while j < len(recs) and recs[j][1] == 0x003C:
                chunks.append(recs[j][2])
                j += 1
            sst = _parse_sst(chunks)
            i = j
            continue
        i += 1
    return sheets, sst


def _sheet_cells(wb: bytes, start: int, sst: list[str]) -> list[list[tuple[int, object]]]:
    """One sheet substream → rows of ``(column, value)`` for the non-empty cells."""
    rows: dict[int, list[tuple[int, object]]] = {}
    pending_formula: tuple[int, int] | None = None

    def put(row: int, col: int, val: object) -> None:
        if val is None or val == "":
            return
        rows.setdefault(row, []).append((col, val))

    for _off, rt, d in _records(wb, start):
        try:
            if rt == 0x00FD and len(d) >= 10:                     # LABELSST
                row, col, _xf, isst = struct.unpack_from("<HHHI", d, 0)
                put(row, col, sst[isst] if isst < len(sst) else "")
            elif rt == 0x0204 and len(d) >= 8:                    # LABEL
                row, col = struct.unpack_from("<HH", d, 0)
                put(row, col, _biff8_string(d, 6))
            elif rt == 0x0203 and len(d) >= 14:                   # NUMBER
                row, col = struct.unpack_from("<HH", d, 0)
                put(row, col, struct.unpack_from("<d", d, 6)[0])
            elif rt == 0x027E and len(d) >= 10:                   # RK
                row, col = struct.unpack_from("<HH", d, 0)
                put(row, col, _rk(struct.unpack_from("<I", d, 6)[0]))
            elif rt == 0x00BD and len(d) >= 6:                    # MULRK
                row, col_first = struct.unpack_from("<HH", d, 0)
                n = (len(d) - 6) // 6
                for k in range(n):
                    rk = struct.unpack_from("<I", d, 4 + k * 6 + 2)[0]
                    put(row, col_first + k, _rk(rk))
            elif rt == 0x0205 and len(d) >= 8:                    # BOOLERR
                row, col, _xf, val, is_err = struct.unpack_from("<HHHBB", d, 0)
                if not is_err:
                    put(row, col, float(val))
            elif rt == 0x0006 and len(d) >= 20:                   # FORMULA (cached result)
                row, col = struct.unpack_from("<HH", d, 0)
                res = d[6:14]
                if res[6:8] == b"\xff\xff":
                    kind = res[0]
                    if kind == 0:                                 # string: comes in the next STRING record
                        pending_formula = (row, col)
                    elif kind == 1:
                        put(row, col, float(res[2]))
                else:
                    put(row, col, struct.unpack("<d", res)[0])
            elif rt == 0x0207 and pending_formula:                # STRING
                put(pending_formula[0], pending_formula[1], _biff8_string(d, 0))
                pending_formula = None
        except Exception:
            continue                                              # one bad record must not lose the sheet
    if not rows:
        return []
    # keep the holes: the caller lines rows up by position, so row 16 of the sheet must be index 16
    return [sorted(rows[i], key=lambda c: c[0]) if i in rows else [] for i in range(max(rows) + 1)]


def read_named_sheets(data: bytes) -> list[tuple[str, list[list[tuple[int, object]]]]]:
    """Every sheet of a legacy ``.xls`` with its own name. Raises :class:`XlsError`."""
    wb = _Cfb(data).stream("Workbook", "Book")
    first = next(_records(wb, 0, stop_at_eof=False), None)
    if not first or first[1] != 0x0809:
        raise XlsError("the workbook stream does not start with a BOF record")
    version = struct.unpack_from("<H", first[2], 0)[0] if len(first[2]) >= 2 else 0
    if version != 0x0600:
        raise XlsError(f"BIFF 0x{version:04x} is older than Excel 97; this reader only claims BIFF8")
    sheets, sst = _globals(wb)
    out = [(name, _sheet_cells(wb, pos, sst)) for name, pos in sheets]
    if not out:
        raise XlsError("the workbook has no sheet")
    return out


def read_sheets(data: bytes) -> list[list[list[tuple[int, object]]]]:
    """Every sheet of a legacy ``.xls`` as ``[[(col, value), ...], ...]``. Raises :class:`XlsError`."""
    return [rows for _name, rows in read_named_sheets(data)]


def sheets_as_text(data: bytes) -> str:
    """The whole workbook as tab-separated text (what ``docread`` stores for an attachment)."""
    blocks: list[str] = []
    for name, rows in read_named_sheets(data):
        blocks.append(f"## {name or 'Sheet'}")
        for row in rows:
            cells: dict[int, str] = {}
            for col, val in row:
                cells[col] = _cell_text(val)
            if not any(cells.values()):
                continue
            width = max(cells) + 1
            blocks.append("\t".join(cells.get(i, "") for i in range(width)))
    return "\n".join(blocks)


def _cell_text(v: object) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()
