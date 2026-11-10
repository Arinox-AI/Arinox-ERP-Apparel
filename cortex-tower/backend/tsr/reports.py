"""Script Reports through the TSR. The 17 reports are the same code the hosted site would run (vendored from the
bundle); they get the same ``frappe`` stand-in as the Server Scripts, so their SQL goes through ``tsr.sql``.

A report script sets ``data = [columns, rows]`` (Frappe's convention for Script Reports).
"""

from __future__ import annotations

import json
import os
import re
import time

from . import shim
from .errors import TSRError, TSRNotFound, TSRUnsupported, TSRValidationError
from .runner import HERE, Context, Engine, TSRScriptError, static_check

PATH = os.path.join(HERE, "vendor", "reports.json")


class ReportRegistry:
    def __init__(self, records=None):
        if records is None:
            with open(PATH) as f:
                records = json.load(f)["records"]
        self.by_name = {}
        self.code = {}
        for r in records:
            bad = static_check(r["name"], r["report_script"] or "")
            if bad:
                raise TSRUnsupported(f"report {r['name']}: {bad}")
            self.by_name[r["name"]] = r
            self.code[r["name"]] = compile(r["report_script"] or "", "report:" + r["name"], "exec")

    def names(self):
        return sorted(self.by_name)


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def _column(c):
    if isinstance(c, dict):
        out = dict(c)
        out.setdefault("fieldname", _slug(str(out.get("label", ""))))
        return out
    parts = str(c).split(":")
    label = parts[0]
    ftype, _, options = (parts[1] if len(parts) > 1 else "Data").partition("/")
    col = {"label": label, "fieldname": _slug(label), "fieldtype": ftype or "Data"}
    if options:
        col["options"] = options
    if len(parts) > 2 and parts[2].isdigit():
        col["width"] = int(parts[2])
    return col


def run(registry: ReportRegistry, engine: Engine, backend, name: str, filters: dict | None = None, user: str = "Administrator",
        limit: int = 2000) -> dict:
    rec = registry.by_name.get(name)
    if rec is None:
        raise TSRNotFound("Report", name)
    ctx = Context(backend, engine, user=user, mode="record")        # a report never writes
    fr = shim.Frappe(ctx)
    g = {"frappe": fr, "filters": shim.DotDict(filters or {}), "data": None, "result": None, "json": shim.safe_json,
         "__builtins__": shim.safe_builtins()}
    t0 = time.time()
    try:
        exec(registry.code[name], g)
    except TSRError:
        raise
    except Exception as e:                                                  # noqa: BLE001
        raise TSRScriptError("report:" + name, e)
    out = g.get("data")
    if not out:
        raise TSRUnsupported(f"report {name} returned nothing")
    cols_raw, rows_raw = out[0], out[1]
    cols = [_column(c) for c in cols_raw]
    rows = []
    for r in (rows_raw or [])[:limit]:
        if isinstance(r, dict):
            rows.append({k: v for k, v in r.items()})
        else:
            rows.append({cols[i]["fieldname"]: v for i, v in enumerate(r) if i < len(cols)})
    return {"name": name, "columns": cols, "rows": rows, "truncated": len(rows_raw or []) > limit,
            "ms": int((time.time() - t0) * 1000), "filters_def": rec.get("filters") or []}
