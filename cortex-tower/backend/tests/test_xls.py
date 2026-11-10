#!/usr/bin/env python3
"""A buyer's legacy .xls BOM is read with nothing installed (2026-11-07).

The defect this suite locks down, seen by the user twice in one morning:

    C9043-U70-629.xls could not be opened. Excel (.xlsx, .xls) and CSV/TSV are read; a PDF, a photo
    or an old .xlsb has to be uploaded as a sheet or typed in.

and, on the same sheet at mail-ingest time, the attachment was filed as
*"legacy_xls_not_readable — this server has no .xls reader; ask the buyer for .xlsx"*.

The sheet was fine. The bytes were on disk (41,984 of them, a real OLE2 / BIFF8 workbook printed by the
buyer's own system, "Report Id: STY360"). What was missing was ``xlrd``: ``bom_reader`` and ``docread``
both imported it, and the machine that serves the app does not have it — while a developer shell does,
which is why the bug read as "works here".

``xlsread.py`` reads the container (FAT, DIFAT, directory, mini stream) and the BIFF8 cell records in pure
Python. This suite proves the three things that matter:

  · the cells come out the same as ``xlrd`` gives (compared here when ``xlrd`` happens to be installed);
  · the BOM reader still finds the 11 material lines — with ``xlrd`` blocked, i.e. on the runtime;
  · ``docread`` turns the same file into text instead of the "no .xls reader" refusal.

Run:  python3 tests/test_xls.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import bom_reader                                                          # noqa: E402
import docread                                                             # noqa: E402
import xlsread                                                             # noqa: E402

FIXTURE = os.path.join(HERE, "fixtures", "BOM_C9043-U70-629.xls")

_PASS = 0
_FAIL = []


def check(name, cond, detail=""):
    global _PASS
    if cond:
        _PASS += 1
        print(f"  PASS  {name}")
    else:
        _FAIL.append(name)
        print(f"  FAIL  {name}   {detail}")


def _bytes() -> bytes:
    with open(FIXTURE, "rb") as f:
        return f.read()


def _cell(rows, r, c):
    for col, val in rows[r]:
        if col == c:
            return val
    return None


class _NoXlrd:
    """``sys.modules['xlrd'] = None`` makes ``import xlrd`` raise — the runtime's actual condition."""

    def __enter__(self):
        self.saved = sys.modules.get("xlrd", "absent")
        sys.modules["xlrd"] = None
        return self

    def __exit__(self, *exc):
        if self.saved == "absent":
            sys.modules.pop("xlrd", None)
        else:
            sys.modules["xlrd"] = self.saved
        return False


def t_container():
    print("\n1. The OLE2 container and the BIFF8 records")
    data = _bytes()
    cfb = xlsread._Cfb(data)
    names = [e["name"] for e in cfb.entries if e["type"] == 2]
    check("the file is read as a compound file", cfb.ssz in (512, 4096), f"sector size {cfb.ssz}")
    check("it holds a Workbook stream", "Workbook" in names, str(names))
    wb = cfb.stream("Workbook", "Book")
    check("the stream comes back whole", len(wb) > 4000, f"{len(wb)} bytes")
    sheets, sst = xlsread._globals(wb)
    check("one sheet, named Sheet1", [n for n, _ in sheets] == ["Sheet1"], str(sheets))
    check("a multi-sheet workbook keeps its own names", [n for n, _ in xlsread.read_named_sheets(_bytes())] == ["Sheet1"])
    check("the shared strings were unpacked", len(sst) > 20, f"{len(sst)} strings")
    check("a shared string reads as text", any("LYOCELL" in s for s in sst),
          str([s for s in sst if "LYO" in s][:2]))


def t_cells():
    print("\n2. The cells (what bom_reader lines up by position)")
    rows = xlsread.read_sheets(_bytes())[0]
    check("54 rows, the holes kept so row numbers still line up", len(rows) == 54, f"{len(rows)} rows")
    check("the report header is there", _cell(rows, 1, 1) == "Report Id: STY360", repr(_cell(rows, 1, 1)))
    check("the buyer's company is there", _cell(rows, 1, 13) == "EMJ APPAREL GROUP", repr(_cell(rows, 1, 13)))
    check("Style: holds the style", _cell(rows, 3, 5) == "C9043-U70-629", repr(_cell(rows, 3, 5)))
    check("Color: holds the colour code", _cell(rows, 4, 5) == "CLCPW", repr(_cell(rows, 4, 5)))
    check("the heading row keeps its words", _cell(rows, 13, 13) == "\nDescription", repr(_cell(rows, 13, 13)))
    check("an item code survived", _cell(rows, 16, 1) == "U70", repr(_cell(rows, 16, 1)))
    check("a consumption number is a number", _cell(rows, 16, 33) == 0.03, repr(_cell(rows, 16, 33)))
    check("a description with brackets survived", str(_cell(rows, 20, 13)).startswith("(Self) 100% LYOCELL"),
          repr(_cell(rows, 20, 13)))


def t_same_as_xlrd():
    print("\n3. Same cells as xlrd (the reference, when this machine has it)")
    try:
        import xlrd
    except Exception:
        print("  SKIP  xlrd is not installed here — the comparison runs on a developer shell only")
        return
    book = xlrd.open_workbook(file_contents=_bytes())
    mine = xlsread.read_sheets(_bytes())
    same = len(book.sheets()) == len(mine)
    for sh, rows in zip(book.sheets(), mine):
        if sh.nrows != len(rows):
            same = False
            break
        for i in range(sh.nrows):
            ref = [(j, v) for j, v in enumerate(sh.row_values(i)) if str(v or "").strip() != ""]
            if ref != rows[i]:
                same = False
                print(f"        row {i}: {rows[i][:3]} vs {ref[:3]}")
                break
    check("every cell of every row matches xlrd", same)


def t_bom_without_xlrd():
    print("\n4. The BOM reader on a runtime with no xlrd (the actual defect)")
    with _NoXlrd():
        try:
            import xlrd                                        # noqa: F401
            blocked = False
        except Exception:
            blocked = True
        check("xlrd really is unavailable in this block", blocked)
        rows = bom_reader.sheet_rows("C9043-U70-629.xls", _bytes())
        check("the sheet still opens", bool(rows) and len(rows[0]) == 54, f"{len(rows)} sheets")
        r = bom_reader.read_bom("C9043-U70-629.xls", _bytes())
        check("11 material lines are read", len(r.get("rows") or []) == 11, f"{len(r.get('rows') or [])} rows")
        check("the style comes off the sheet", r.get("style") == "C9043-U70-629", repr(r.get("style")))
        first = (r.get("rows") or [{}])[0]
        check("line 1 is the contrast fabric", first.get("material_type") == "Contrast Fabric"
              and "LYOCELL" in first.get("description", ""), str(first)[:120])
        check("its consumption is 0.03 per garment", first.get("consumption") == 0.03, str(first.get("consumption")))
        check("the double button line is flagged, not silently merged",
              any("BT234" in w for w in (r.get("warnings") or [])), str(r.get("warnings")))
        d = docread.read_xls(_bytes())
        check("docread reads it as text, not as a refusal", d.get("ok") is True, str(d.get("error"))[:120])
        check("the text holds the sheet's rows", "C9043-U70-629" in (d.get("text") or ""),
              (d.get("text") or "")[:80])
        check("no 'ask the buyer for .xlsx' message is produced", "no .xls reader" not in (d.get("error") or ""))


def t_bad_input():
    print("\n5. What it refuses (and says so)")
    for name, blob in (("an empty file", b""), ("a photo", b"\xff\xd8\xff\xe0" + b"0" * 600),
                       ("an xlsx handed over as .xls", b"PK\x03\x04" + b"0" * 600)):
        try:
            xlsread.read_sheets(blob)
            ok = False
        except xlsread.XlsError:
            ok = True
        except Exception as e:                                 # noqa: BLE001
            ok = False
            print(f"        {name}: raised {type(e).__name__}")
        check(f"{name} raises XlsError, not an empty sheet", ok)
    check("the BOM reader reports it as unreadable",
          bom_reader.read_bom("x.xls", b"not a workbook").get("error") == "unreadable")
    d = docread.read_xls(b"\xff\xd8\xff\xe0" + b"0" * 600)
    check("docread says xls_unreadable rather than pretending", d.get("ok") is False and "unreadable" in (d.get("error") or ""),
          str(d.get("error")))


def main():
    if not os.path.isfile(FIXTURE):
        print(f"SKIP — the fixture is missing ({FIXTURE})")
        return 0
    print("Legacy .xls with no third-party reader")
    t_container()
    t_cells()
    t_same_as_xlrd()
    t_bom_without_xlrd()
    t_bad_input()
    print("\n" + "=" * 70)
    if _FAIL:
        print(f"❌ {len(_FAIL)} failed: {_FAIL}")
        return 1
    print(f"✅ {_PASS} assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
