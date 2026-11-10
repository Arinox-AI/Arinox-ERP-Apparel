#!/usr/bin/env python3
"""The buyer's sheet is read by the model, and what it says lands on the style (2026-11-07).

Two defects this suite locks down, both seen in one session:

1. **The model was shown a cut-down sheet.** ``bom_reader.grid_text`` printed the first 16 columns only. This buyer's
   STY360 export puts the UOM in column 31 and "Quantity Required" in column 33, so the model was asked for the
   consumptions of a sheet in which every consumption had been cut off. It answered, honestly, ``null`` for all 11
   lines - and the merchandiser was then asked to type the quantities in himself.
2. **The style's own facts were never asked for.** The sheet prints the description ("1 POCKET CROPPED BUTTON DOWN"),
   the colour, the fabrication and the whole size range (XXS - XXL). The prompt only asked for materials, so those
   fields stayed blank and the inquiry page asked a person to type them again.

So: the grid keeps every column that holds anything, the prompt asks for the style fields as well as the lines, the
answer is validated (a product type is only accepted when the ERP has one by that name), and every value only fills a
field that is still **blank** - a person's edit always wins.

Run:  python3 tests/test_bom_read.py
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import ai_nextsteps                                                       # noqa: E402
import bom_reader                                                         # noqa: E402
import deals                                                              # noqa: E402

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


def t_grid_keeps_far_columns():
    print("\n1. The sheet the model is given keeps everything on it")
    grid = bom_reader.grid_text("C9043-U70-629.xls", open(FIXTURE, "rb").read())
    check("the grid is not empty", bool(grid.strip()))
    check("a quantity in column 33 survives", "0.03" in grid and "1.47" in grid, grid[:120])
    check("a UOM in column 31 survives", "YD" in grid)
    check("the size row survives", all(s in grid for s in ("XXS", "XS", "M", "XL", "XXL")), grid[:200])
    check("the style description survives", "1 POCKET CROPPED BUTTON DOWN" in grid)
    widest = max(len(l.split(" | ")) for l in grid.split("\n"))
    check("columns that hold nothing are dropped (41 -> under 25)", widest < 25, f"widest line has {widest} fields")
    # alignment still holds: a line with a consumption also has its description on the same line
    line = next((l for l in grid.split("\n") if "1.47" in l), "")
    check("the row keeps description and quantity on one line", "LYOCELL" in line, line[:160])


def t_answer_is_read():
    print("\n2. What the model says is validated, not trusted")
    reply = json.dumps({"style_no": "C9043-U70-629", "style_name": "1 POCKET CROPPED BUTTON DOWN",
                        "colour": "CLCPW", "fabric": "100% LYOCELL (F85 LIKE QUALITY)",
                        "sizes": ["XXS", "XS", "S", "M", "L", "XL", "XXL"], "qty": None,
                        "product_type": "Woven Top",
                        "rows": [{"item_code": "U70", "material_type": "Fabric", "description": "(Self) 100% LYOCELL",
                                  "colour": "002", "uom": "Yard", "consumption": 1.47}]})
    got = deals.bom_rows_from_ai(reply, "C9043-U70-629", ["Knit Top", "Woven Top", "Bottom", "Dress"])
    check("the description comes through", got["style_name"] == "1 POCKET CROPPED BUTTON DOWN", got["style_name"])
    check("the sizes come through in the sheet's order", got["sizes"] == ["XXS", "XS", "S", "M", "L", "XL", "XXL"], str(got["sizes"]))
    check("the fabric comes through", got["fabric"].startswith("100% LYOCELL"), got["fabric"])
    check("the product type is accepted when the ERP has it", got["product_type"] == "Woven Top", got["product_type"])
    check("the material line survives", len(got["rows"]) == 1 and got["rows"][0]["consumption"] == 1.47, str(got["rows"]))
    off = deals.bom_rows_from_ai(json.dumps({"product_type": "Hoodie",
                                             "rows": [{"description": "x", "consumption": 1}]}), "", ["Shirt"])
    check("an off-list product type is not stored", off["product_type"] == "", off["product_type"])
    check("sizes as a string still work", deals._sizes_from_ai("S, M, L") == ["S", "M", "L"], str(deals._sizes_from_ai("S, M, L")))
    check("sizes as a range string still work", deals._sizes_from_ai("S-M-L") == ["S", "M", "L"], str(deals._sizes_from_ai("S-M-L")))
    check("a ratio object still works", deals._sizes_from_ai({"S": 1, "M": 2}) == ["S", "M"], str(deals._sizes_from_ai({"S": 1})))
    check("nonsense is not made into a size", deals._sizes_from_ai("assorted") == [], str(deals._sizes_from_ai("assorted")))


def t_blank_only():
    print("\n3. The sheet fills blanks; it never overwrites a person")
    st = {"style_no": "X", "style_name": "", "colour": "What the buyer's mail said", "fabric": "", "sizes": [],
          "qty": None, "product_type": ""}
    got = {"style_name": "1 POCKET CROPPED BUTTON DOWN", "colour": "CLCPW", "fabric": "100% LYOCELL",
           "sizes": ["S", "M"], "qty": 1000, "product_type": "Woven Top"}
    filled = deals._fill_style_from_read(st, got)
    check("the blank description is filled", st["style_name"] == "1 POCKET CROPPED BUTTON DOWN", st["style_name"])
    check("the colour already on the deal is left alone", st["colour"] == "What the buyer's mail said", st["colour"])
    check("the blank fabric is filled", st["fabric"] == "100% LYOCELL", st["fabric"])
    check("the blank sizes are filled", st["sizes"] == ["S", "M"], str(st["sizes"]))
    check("the blank quantity is filled", st["qty"] == 1000, str(st["qty"]))
    check("the blank product type is filled", st["product_type"] == "Woven Top", st["product_type"])
    check("only the fields it actually filled are reported", sorted(filled) == ["description", "fabric", "product type",
                                                                               "quantity", "sizes"], str(filled))
    again = deals._fill_style_from_read(st, got)
    check("a second read changes nothing", again == [], str(again))


def t_stream_noise():
    print("\n4. A progress note in the stream cannot break the answer")
    broken = '{"style_no": "C9043-U70-629", "qty": null, "rows": [{"item_code": "ST022", "material_typeOn it…": "Label"}, ' \
             '{"item_code": "X",Hold tight… "description": "BUTTON"}]}'
    clean = ai_nextsteps._clean(broken)
    check("the note is removed from the text", "Hold tight" not in clean and "On it" not in clean, clean[:120])
    parsed = deals._json_block(clean)
    check("the answer still parses", isinstance(parsed, dict), str(parsed)[:120])
    check("the polluted key is repaired", parsed["rows"][0].get("material_type") == "Label", str(parsed["rows"][0]))
    check("null survives the cleanup", parsed.get("qty") is None, str(parsed.get("qty")))
    check("a bare note between tokens is dropped", deals._json_block('{"a": "x",Working on it… "b": 2}') == {"a": "x", "b": 2})
    check("prose before and after is ignored",
          deals._json_block('Here you go: [{"description": "BUTTON", "consumption": 1.0}] hope it helps') ==
          [{"description": "BUTTON", "consumption": 1.0}])
    check("a description containing the word 'reading' is untouched",
          deals._json_block('{"a": "reading the sheet" }') == {"a": "reading the sheet"})


def t_prompt_asks_everything():
    print("\n5. The prompt asks for the style, not only the materials")
    p = deals.bom_ai_prompt("C9043-U70-629", "C9043-U70-629.xls", "a | b", ["Knit Top", "Woven Top"])
    for key in ('"style_name"', '"sizes"', '"product_type"', '"fabric"', '"qty"', '"rows"'):
        check(f"the prompt asks for {key}", key in p)
    check("the ERP's own product types are in the prompt", "Knit Top, Woven Top" in p)
    check("no placeholder is left unfilled", "{types" not in p and "{', '" not in p)
    check("the sizes rule mentions the sheet's own layout", "Available Sizes" in p or "size" in p.lower())


def main():
    if not os.path.isfile(FIXTURE):
        print(f"SKIP — the fixture is missing ({FIXTURE})")
        return 0
    print("The sheet is read by the model, and what it says is put on the style")
    t_grid_keeps_far_columns()
    t_answer_is_read()
    t_blank_only()
    t_stream_noise()
    t_prompt_asks_everything()
    print("\n" + "=" * 70)
    if _FAIL:
        print(f"❌ {len(_FAIL)} failed: {_FAIL}")
        return 1
    print(f"✅ {_PASS} assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
