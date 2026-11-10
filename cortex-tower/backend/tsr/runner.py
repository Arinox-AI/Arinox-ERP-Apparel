"""Registry + event engine: run the hosted Server Scripts in the order Frappe would, around REST writes.

Event order (Frappe ``Document.run_before_save_methods`` / ``run_post_save_methods``; Server Script names in brackets):

========  =====================================================================================================
insert    Before Insert → Before Validate → Before Save → **REST insert** → After Save
save      Before Validate → Before Save → **REST save** → After Save              (submitted: …(Submitted Document))
submit    Before Validate → Before Save → Before Submit → **REST submit** → After Save → After Submit
cancel    Before Cancel → **REST cancel** → After Cancel
delete    Before Delete → **REST delete**
========  =====================================================================================================

A ``frappe.throw`` in any *Before* script stops the operation with nothing written. A failure *after* the REST
call propagates to the caller, which is expected to ``compensate()`` the journal (the pipeline does).
"""

from __future__ import annotations

import ast
import copy
import json
import os
from typing import Any, Optional

from . import shim
from .backend import Backend
from .errors import TSRError, TSRNeedsSchemaFix, TSRNotFound, TSRUnsupported, TSRValidationError
from .journal import LiveSink, RecordingSink

HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR = os.path.join(HERE, "vendor", "server_scripts.json")

MAX_DEPTH = 8
FORBIDDEN_NAMES = {"eval", "exec", "open", "compile", "globals", "locals", "getattr", "setattr", "delattr", "__import__",
                   "input", "vars", "dir", "type", "breakpoint", "memoryview"}

ALLOWED_CALLS = {
    "erpnext.accounts.doctype.sales_invoice.sales_invoice.make_sales_return",
    "erpnext.controllers.item_variant.create_variant",
    "erpnext.controllers.item_variant.get_variant",
    "erpnext.selling.doctype.sales_order.sales_order.make_delivery_note",
    "erpnext.selling.doctype.sales_order.sales_order.update_status",
    "erpnext.stock.doctype.batch.batch.get_batch_qty",
    "erpnext.stock.doctype.delivery_note.delivery_note.make_sales_invoice",
    "erpnext.stock.doctype.purchase_receipt.purchase_receipt.make_purchase_return",
}

#: scripts that must keep running when "rules" are switched off (same list as the ERP kill switch).
ALWAYS_ON_PREFIXES = ("arinox_naming_", "arinox_engine", "arinox_scripts_switch")

EVENT_BY_OP = {
    "insert": ("Before Insert", "Before Validate", "Before Save"),
    "save": ("Before Validate", "Before Save"),
    "save_submitted": ("Before Validate", "Before Save (Submitted Document)"),
    "submit": ("Before Validate", "Before Save", "Before Submit"),
    "cancel": ("Before Cancel",),
    "delete": ("Before Delete",),
}


class TSRScriptError(TSRError):
    """A script crashed with a Python error (not a ``throw``). Names the script so it can be fixed."""

    def __init__(self, script: str, original: BaseException):
        super().__init__(f"Script {script} failed: {type(original).__name__}: {original}")
        self.script, self.original = script, original


# ───────────────────────── registry ─────────────────────────

def static_check(name: str, src: str) -> Optional[str]:
    """None when the script is acceptable, else why not. Defence in depth: the scripts are ours."""
    try:
        tree = ast.parse(src, filename=name)
    except SyntaxError as e:
        return f"SyntaxError: {e}"
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            return "import is not allowed"
        if isinstance(n, ast.Attribute) and n.attr.startswith("__"):
            return f"dunder attribute {n.attr}"
        if isinstance(n, ast.Name) and n.id in FORBIDDEN_NAMES:
            return f"name {n.id} is not allowed"
        if isinstance(n, (ast.ClassDef,)):
            return "class definitions are not allowed (not allowed on the hosted site either)"
    return None


class Registry:
    def __init__(self, records: list[dict]):
        self.by_name: dict[str, dict] = {}
        self.events: dict[tuple[str, str], list[dict]] = {}
        self.api: dict[str, dict] = {}
        self.scheduler: dict[str, dict] = {}
        self.code: dict[str, Any] = {}
        for r in records:
            if r.get("disabled"):
                continue
            bad = static_check(r["name"], r["script"])
            if bad:
                raise TSRUnsupported(f"{r['name']}: {bad}")
            self.by_name[r["name"]] = r
            self.code[r["name"]] = compile(r["script"], r["name"], "exec")
            t = r["script_type"]
            if t == "DocType Event":
                self.events.setdefault((r["reference_doctype"], r["doctype_event"]), []).append(r)
            elif t == "API":
                self.api[r["name"]] = r
                if r.get("api_method"):
                    self.api[r["api_method"]] = r
            elif t == "Scheduler Event":
                self.scheduler[r["name"]] = r

    @classmethod
    def load(cls, path: str = VENDOR) -> "Registry":
        with open(path) as f:
            return cls(json.load(f)["records"])

    def api_methods(self) -> list[str]:
        return sorted({r["api_method"] for r in self.by_name.values() if r["script_type"] == "API" and r.get("api_method")})


# ───────────────────────── context ─────────────────────────

class Context:
    """Everything one tower request shares: the ERP backend, the sink, the user, the caches and the output."""

    def __init__(self, backend: Backend, engine: "Engine", user: str = "Administrator", roles: Optional[list[str]] = None,
                 mode: str = "live", sink=None, persist=None, perm_checker=None, script_enabled=None, form=None):
        self.backend = backend
        self.engine = engine
        self.user = user
        self.roles = roles or []
        self.mode = mode
        self.sink = sink or (LiveSink(backend, persist) if mode == "live" else RecordingSink(backend))
        self.messages: list[dict] = []
        self.errors: list[dict] = []
        self.rcache: dict = {}
        self.sqlcache: dict = {}
        self.live: list = []
        self.depth = 0
        self.ran: list[str] = []
        self.perm_checker = perm_checker
        self.script_enabled = script_enabled or (lambda name: True)
        self.request_form = form or {}

    def invalidate(self):
        self.rcache.clear()
        self.sqlcache.clear()

    def check_permission(self, doctype, perm, name=None):
        if self.perm_checker:
            self.perm_checker(self.user, doctype, perm, name)

    def result(self) -> dict:
        return {"messages": self.messages, "errors": self.errors, "scripts_run": self.ran}


# ───────────────────────── engine ─────────────────────────

class Engine:
    def __init__(self, registry: Registry):
        self.registry = registry

    # ---- script execution ----
    def _run(self, ctx: Context, rec: dict, doc=None, form: Optional[dict] = None) -> dict:
        name = rec["name"]
        if not ctx.script_enabled(name):
            return {}
        ctx.depth += 1
        if ctx.depth > MAX_DEPTH:
            ctx.depth -= 1
            raise TSRError(f"script nesting deeper than {MAX_DEPTH} at {name}")
        fr = shim.Frappe(ctx)
        fr.form_dict = shim.DotDict(form if form is not None else ctx.request_form)

        def run_script(script_name, **kw):
            target = self.registry.api.get(script_name)
            if target is None:
                raise TSRNotFound("Server Script", script_name)
            return shim.dotify(dict(self._run(ctx, target, form=kw)))

        g = {"frappe": fr, "doc": doc, "run_script": run_script, "json": shim.safe_json, "__builtins__": shim.safe_builtins()}
        ctx.ran.append(name)
        try:
            exec(self.registry.code[name], g)
        except (TSRError,):
            raise
        except Exception as e:
            raise TSRScriptError(name, e)
        finally:
            ctx.depth -= 1
        return fr.flags

    def run_event(self, ctx: Context, doc: shim.Doc, event: str):
        for rec in self.registry.events.get((doc.doctype, event), ()):
            self._run(ctx, rec, doc=doc)

    def run_api(self, ctx: Context, method: str, form: Optional[dict] = None) -> dict:
        rec = self.registry.api.get(method)
        if rec is None:
            raise TSRNotFound("API Server Script", method)
        return dict(self._run(ctx, rec, form=form or {}))

    def run_scheduler(self, ctx: Context, name: str) -> dict:
        rec = self.registry.scheduler.get(name)
        if rec is None:
            raise TSRNotFound("Scheduler Server Script", name)
        return dict(self._run(ctx, rec, form={}))

    # ---- document operations (called by Doc and by the pipeline) ----
    def absorb(self, doc: shim.Doc, data: dict):
        ctx = doc.__dict__["_ctx"]
        keep = doc.__dict__["flags"]
        for k in [k for k in doc.__dict__ if not k.startswith("_") and k != "flags"]:
            del doc.__dict__[k]
        fresh = shim.Doc(ctx, data, row=True)
        for k, v in fresh.__dict__.items():
            if k.startswith("_") or k == "flags":
                continue
            doc.__dict__[k] = v
        doc.__dict__["_islocal"] = False
        doc.__dict__["_before"] = copy.deepcopy(doc.as_dict())
        doc.__dict__["flags"] = keep

    def _payload(self, doc: shim.Doc) -> dict:
        d = copy.deepcopy(dict(doc.as_dict()))
        for k in ("__islocal", "__unsaved"):
            d.pop(k, None)
        return d

    def _events(self, ctx, doc, names):
        for ev in names:
            if ctx.mode == "record" and ev.startswith("After"):
                self._simulate_after(ctx, doc, ev)
                continue
            self.run_event(ctx, doc, ev)

    def _simulate_after(self, ctx, doc, ev):
        """A dry run cannot know the state the After-scripts would see (the write did not happen), so a problem they
        hit is reported as a WARNING in the preview, not a block — except a deliberate ``throw`` on a cancel, where the
        state is the real, stored one."""
        try:
            self.run_event(ctx, doc, ev)
        except TSRValidationError:
            if doc.docstatus == 2:
                raise
            ctx.messages.append({"message": f"After {ev[6:]} step may refuse this (could not be fully simulated)", "title": "", "indicator": "orange", "alert": False})
        except (TSRNotFound, TSRUnsupported, TSRScriptError, TSRError) as e:
            ctx.messages.append({"message": f"{ev} could not be simulated: {str(e)[:160]}", "title": "", "indicator": "orange", "alert": False})

    def insert(self, ctx: Context, doc: shim.Doc):
        ctx.check_permission(doc.doctype, "create")
        self._events(ctx, doc, EVENT_BY_OP["insert"])
        res = ctx.sink.insert(self._payload(doc))
        ctx.invalidate()
        self.absorb(doc, res)
        self._events(ctx, doc, ("After Save",))
        return doc

    def save(self, ctx: Context, doc: shim.Doc):
        if doc.is_new():
            return self.insert(ctx, doc)
        ctx.check_permission(doc.doctype, "write", doc.name)
        before = doc.__dict__["_before"] or {}
        submitted = before.get("docstatus", doc.docstatus) == 1
        self._events(ctx, doc, EVENT_BY_OP["save_submitted" if submitted else "save"])
        res = ctx.sink.save(self._payload(doc))
        ctx.invalidate()
        self.absorb(doc, res)
        self._events(ctx, doc, ("After Save (Submitted Document)",) if submitted else ("After Save",))
        return doc

    def submit(self, ctx: Context, doc: shim.Doc):
        if doc.is_new():
            self.insert(ctx, doc)
        ctx.check_permission(doc.doctype, "submit", doc.name)
        doc.docstatus = 1
        self._events(ctx, doc, EVENT_BY_OP["submit"])
        res = ctx.sink.submit(self._payload(doc))
        ctx.invalidate()
        self.absorb(doc, res)
        # The document is submitted: the ERP owns that fact now. An After Save / After Submit script that trips over
        # the ERP's own schema (a field the site will not let anyone change after submission) must NOT travel back up
        # as a failure — a failure is compensated by *cancelling* the document, which turns "the contract is signed,
        # one field could not be updated" into "the contract is cancelled". That is exactly what happened to
        # CTXGVN26.11.006 and CTXGVN26.11.006-1 on 2026-11-07. It is reported as a warning instead, with what to fix.
        try:
            self._events(ctx, doc, ("After Save", "After Submit"))
        except TSRNeedsSchemaFix as e:
            ctx.messages.append({"message": f"Submitted. The ERP's own after-submit script could not write "
                                            f"{', '.join(e.fields)} on {doc.doctype} (the site forbids it after "
                                            f"submission); fix with erp_setup/allow_on_submit.json.",
                                 "title": "Submitted, with a warning", "indicator": "orange", "alert": True})
            self._record_schema_gap(ctx, doc, e)
        return doc

    def _record_schema_gap(self, ctx, doc, e) -> None:
        """Keep the fields the site would not accept, so the same warning is not rediscovered by hand next time."""
        try:
            if hasattr(ctx.sink, "skipped"):
                ctx.sink.skipped.append({"doctype": doc.doctype, "name": doc.name or "",
                                         "values": {f: None for f in e.fields},
                                         "why": "after-submit script: the ERP forbids changing this field after submission"})
        except Exception:
            pass

    def cancel(self, ctx: Context, doc: shim.Doc):
        ctx.check_permission(doc.doctype, "cancel", doc.name)
        doc.docstatus = 2
        self._events(ctx, doc, EVENT_BY_OP["cancel"])
        res = ctx.sink.cancel(doc.doctype, doc.name)
        ctx.invalidate()
        self.absorb(doc, {**self._payload(doc), **(res or {}), "docstatus": 2})
        self._events(ctx, doc, ("After Cancel",))
        return doc

    def delete(self, ctx: Context, doctype: str, name: str):
        ctx.check_permission(doctype, "delete", name)
        if self.registry.events.get((doctype, "Before Delete")):
            try:
                data = ctx.backend.get_doc(doctype, name)
            except TSRNotFound:
                return
            data.setdefault("doctype", doctype)
            self.run_event(ctx, shim.Doc(ctx, data), "Before Delete")
        ctx.sink.delete(doctype, name)
        ctx.invalidate()

    def db_set(self, ctx: Context, doc: shim.Doc, values: dict):
        if doc.is_new():
            for k, v in values.items():
                doc.__dict__[k] = v
            return
        self.set_values(ctx, doc.doctype, doc.name, values, doc)

    def set_values(self, ctx: Context, doctype: str, name: str, values: dict, doc: Optional[shim.Doc] = None):
        res = ctx.sink.set_value(doctype, name, values)
        ctx.invalidate()
        mod = (res or {}).get("modified")
        for d in ctx.live:
            if d.__dict__.get("doctype") == doctype and d.__dict__.get("name") == name:
                for k, v in values.items():
                    d.__dict__[k] = v
                if mod:
                    d.__dict__["modified"] = mod
                b = d.__dict__.get("_before")
                if b is not None:
                    b.update(values)
                    if mod:
                        b["modified"] = mod

    def call(self, ctx: Context, method: str, kw: dict):
        if method not in ALLOWED_CALLS:
            raise TSRUnsupported(f"frappe.call({method!r}) is not on the runtime's allow-list")
        out = ctx.sink.call(method, kw)
        ctx.invalidate()
        return out
