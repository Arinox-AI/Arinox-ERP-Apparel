"""The ``frappe`` object the hosted Server Scripts see, backed by an ERP :class:`Backend`.

Measured surface (grep of all 251 scripts, 2026-11-06): ``throw msgprint log_error get_traceback get_doc
new_doc copy_doc get_cached_doc get_all get_list delete_doc call session.user form_dict flags utils.*``
and ``db.get_value / exists / count / get_single_value / get_default / set_value / sql``; on documents
``insert save db_set append get set as_dict is_new get_doc_before_save has_value_changed add_comment
check_permission``. Anything outside that raises :class:`TSRUnsupported` — never a silent no-op.

Writes never reach the ERP from here directly: they go to ``ctx.sink`` (a journal in live mode, a recorder
in preview/check mode) and, for documents, through the event engine in ``runner.py`` so the Before/After
scripts of the written document fire exactly as they would on a site with Server Scripts.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import math
import traceback
from typing import Any, Callable, Optional

from . import sql as _sql
from .errors import TSRNotFound, TSRUnsupported, TSRValidationError

CHILD_STD = ("name", "owner", "creation", "modified", "modified_by", "docstatus", "idx", "parent", "parentfield", "parenttype")


class DotDict(dict):
    """``frappe._dict``: attribute access, missing keys read as ``None``."""
    def __getattr__(self, k):
        if k.startswith("__"):
            raise AttributeError(k)
        return self.get(k)

    def __setattr__(self, k, v):
        self[k] = v


# ───────────────────────── utils ─────────────────────────

def flt(v, precision=None):
    if v is None or v == "":
        return 0.0
    try:
        if isinstance(v, str):
            v = v.replace(",", "")
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return round(f, precision) if precision is not None else f


def cint(v, default=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def getdate(v=None):
    if v is None or v == "":
        return _dt.date.today()
    if isinstance(v, _dt.datetime):
        return v.date()
    if isinstance(v, _dt.date):
        return v
    s = str(v).strip()
    try:
        return _dt.date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%m-%d-%Y"):
        try:
            return _dt.datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    raise TSRValidationError(f"{v} is not a valid date")


def nowdate():
    return _dt.date.today().isoformat()


def now_datetime():
    return _dt.datetime.now()


def add_days(d, n):
    base = getdate(d)
    out = base + _dt.timedelta(days=cint(n))
    if isinstance(d, _dt.datetime):
        return d + _dt.timedelta(days=cint(n))
    if isinstance(d, _dt.date):
        return out
    return out.isoformat()


def date_diff(a, b):
    return (getdate(a) - getdate(b)).days


def formatdate(d, fmt=None):
    d = getdate(d)
    fmt = fmt or "yyyy-mm-dd"
    f = (fmt.replace("yyyy", "%Y").replace("MMM", "%b").replace("dd", "%d").replace("mm", "%m").replace("MM", "%m"))
    return d.strftime(f)


def dotify(o):
    """Deep ``frappe._dict``: attribute access at every level (what the sandbox hands back from run_script / frappe.call)."""
    if isinstance(o, dict) and not isinstance(o, DotDict):
        return DotDict({k: dotify(v) for k, v in o.items()})
    if isinstance(o, DotDict):
        for k, v in list(o.items()):
            o[k] = dotify(v)
        return o
    if isinstance(o, list):
        return [dotify(x) for x in o]
    return o


class _Json:
    """The sandbox's ``json``: ``dumps`` copes with dates/decimals (frappe.as_json), ``loads`` gives attribute-access dicts
    (frappe.parse_json returns ``frappe._dict``)."""

    @staticmethod
    def dumps(obj, indent=None, **kw):
        from .backend import _default
        return json.dumps(obj, default=_default, indent=indent)

    @staticmethod
    def loads(s, **kw):
        return dotify(json.loads(s))


safe_json = _Json()


class _Utils:
    flt = staticmethod(flt)
    cint = staticmethod(cint)
    getdate = staticmethod(getdate)
    nowdate = staticmethod(nowdate)
    now_datetime = staticmethod(now_datetime)
    add_days = staticmethod(add_days)
    date_diff = staticmethod(date_diff)
    formatdate = staticmethod(formatdate)
    ceil = staticmethod(lambda x: int(math.ceil(x)))
    floor = staticmethod(lambda x: int(math.floor(x)))


# ───────────────────────── documents ─────────────────────────

_KEEP_STR = {"creation", "modified", "modified_by", "owner", "name", "parent"}


def _coerce(fieldtype, key, v):
    """Frappe hands scripts typed values (a Date field is a ``date``); REST hands us strings."""
    if key in _KEEP_STR or fieldtype is None:
        return v
    try:
        if fieldtype == "Date" and isinstance(v, str) and v:
            return _dt.date.fromisoformat(v[:10])
        if fieldtype == "Datetime" and isinstance(v, str) and v:
            return _dt.datetime.fromisoformat(v)
        if fieldtype in ("Int", "Check", "Long Int") and not isinstance(v, bool):
            return int(float(v))
        if fieldtype in ("Float", "Currency", "Percent") and not isinstance(v, bool):
            return float(v)
    except (TypeError, ValueError):
        return v
    return v


class Doc:
    """A document or child row. Fields are plain attributes; an unset field reads as ``None`` (Frappe does the same)."""

    def __init__(self, ctx, data: dict, is_new: bool = False, row: bool = False):
        d = self.__dict__
        d["_ctx"] = ctx
        d["_islocal"] = is_new
        d["_row"] = row
        d["_before"] = None
        d["flags"] = DotDict()
        types = ctx.backend.field_types(data["doctype"]) if (ctx is not None and data and data.get("doctype")) else {}
        for k, v in (data or {}).items():
            if types and not isinstance(v, (list, dict)) and v is not None:
                v = _coerce(types.get(k), k, v)
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                rows = [Doc(ctx, x, is_new=is_new, row=True) for x in v]
                for i, r in enumerate(rows):             # Frappe numbers child rows; scripts sort on idx
                    r.__dict__["idx"] = r.__dict__.get("idx") or i + 1
                    r.__dict__.setdefault("parentfield", k)
                d[k] = rows
            elif isinstance(v, list) and not v:
                d[k] = []
            else:
                d[k] = v
        if not row and ctx is not None:
            ctx.live.append(self)

    # --- reading ---
    def __getattr__(self, k):
        if k.startswith("_"):
            raise AttributeError(k)
        if self._table_field(k):
            lst: list = []
            self.__dict__[k] = lst          # Frappe: an unset child table is an empty list, and appending to it sticks
            return lst
        return None

    def _table_field(self, k) -> bool:
        ctx, dt = self.__dict__.get("_ctx"), self.__dict__.get("doctype")
        if ctx is None or not dt:
            return False
        try:
            return k in ctx.backend.table_fields(dt)
        except Exception:
            return False

    def get(self, k, default=None):
        if k not in self.__dict__ and self._table_field(k):
            return getattr(self, k)
        return self.__dict__.get(k, default)

    def set(self, k, v):
        # Frappe: doc.set("table", [dict, ...]) makes child rows. Storing the dicts as they are broke every script that
        # then reads ``row.field`` (arinox_cost_sheet_validate rebuilds `charges` this way, so no cost sheet could be saved).
        if isinstance(v, list) and any(isinstance(x, dict) and not isinstance(x, Doc) for x in v):
            rows = []
            for i, x in enumerate(v):
                child = x if isinstance(x, Doc) else Doc(self.__dict__.get("_ctx"), dict(x), is_new=True, row=True)
                child.__dict__["idx"] = i + 1
                child.__dict__["parentfield"] = k
                rows.append(child)
            v = rows
        self.__dict__[k] = v

    def update(self, d):
        for k, v in d.items():
            self.set(k, v)

    def as_dict(self):
        out = {}
        for k, v in self.__dict__.items():
            if k.startswith("_") or k == "flags":
                continue
            if isinstance(v, list) and v and isinstance(v[0], Doc):
                out[k] = [x.as_dict() for x in v]
            else:
                out[k] = v
        return DotDict(out)

    @property
    def meta(self):
        """``doc.meta.fields`` — the field definitions (fieldname, fieldtype, options, reqd, label …)."""
        ctx, dt = self.__dict__.get("_ctx"), self.__dict__.get("doctype")
        fields = []
        if ctx is not None and dt:
            try:
                fields = [DotDict(f) for f in ctx.backend.meta(dt)["fields"]]
            except Exception:
                fields = []
        return DotDict(fields=fields, name=dt)

    def is_new(self):
        return bool(self.__dict__["_islocal"])

    def get_doc_before_save(self):
        b = self.__dict__["_before"]
        return None if b is None else Doc(self._ctx, copy.deepcopy(b), row=True)

    def has_value_changed(self, field):
        b = self.__dict__["_before"]
        if b is None:
            return True
        return b.get(field) != self.__dict__.get(field)

    def run_method(self, method, *args, **kwargs):
        """The two ERPNext controller methods the Arinox builders call on an unsaved Quotation / Sales Order.

        Over REST there is no way to run a controller method on a document that is not saved, but ERPNext runs both
        again itself when the document is inserted, so the tower only needs the figures a script reads back before
        then (line amounts and totals). Anything else is refused out loud, never skipped.
        """
        d = self.__dict__
        if method == "set_missing_values":
            if not d.get("transaction_date") and d.get("doctype") in ("Quotation", "Sales Order"):
                d["transaction_date"] = nowdate()
            if d.get("doctype") == "Quotation" and not d.get("valid_till"):
                d["valid_till"] = str(_dt.date.fromisoformat(str(d["transaction_date"])[:10]) + _dt.timedelta(days=30))
            for it in d.get("items") or []:
                it.__dict__.setdefault("conversion_factor", 1)
                if not it.__dict__.get("uom"):
                    it.__dict__["uom"] = "Nos"
            return None
        if method == "calculate_taxes_and_totals":
            total = 0.0
            qty = 0.0
            for it in d.get("items") or []:
                amt = round(float(it.__dict__.get("qty") or 0) * float(it.__dict__.get("rate") or 0), 2)
                it.__dict__["amount"] = amt
                it.__dict__["net_amount"] = amt
                total += amt
                qty += float(it.__dict__.get("qty") or 0)
            for f in ("total", "net_total", "base_total", "base_net_total", "grand_total", "rounded_total"):
                d[f] = round(total, 2)
            d["total_qty"] = qty
            return None
        raise TSRUnsupported(f"doc.run_method({method!r}) is not available over REST")

    def append(self, table, row=None):
        row = dict(row or {})
        child = Doc(self._ctx, row, is_new=True, row=True)
        lst = self.__dict__.get(table)
        if lst is None:
            lst = []
            self.__dict__[table] = lst
        child.__dict__["idx"] = len(lst) + 1
        child.__dict__["parentfield"] = table
        lst.append(child)
        return child

    # --- writing: always through the event engine ---
    def insert(self, ignore_permissions=False, ignore_links=False, **kw):
        self._ctx.engine.insert(self._ctx, self)
        return self

    def save(self, ignore_permissions=False, **kw):
        self._ctx.engine.save(self._ctx, self)
        return self

    def submit(self):
        self._ctx.engine.submit(self._ctx, self)
        return self

    def cancel(self):
        self._ctx.engine.cancel(self._ctx, self)
        return self

    def delete(self, **kw):
        self._ctx.engine.delete(self._ctx, self.doctype, self.name)

    def reload(self):
        data = self._ctx.backend.get_doc(self.doctype, self.name)
        self._ctx.engine.absorb(self, data)
        return self

    def db_set(self, field, value=None, update_modified=True, **kw):
        values = field if isinstance(field, dict) else {field: value}
        self._ctx.engine.db_set(self._ctx, self, values)

    def add_comment(self, kind="Comment", text=None, **kw):
        self._ctx.sink.add_comment(self.doctype, self.name, text or "", kind)

    def check_permission(self, perm="read", **kw):
        self._ctx.check_permission(self.doctype, perm, self.name)

    def __repr__(self):
        return f"<Doc {self.__dict__.get('doctype')} {self.__dict__.get('name')}>"


# ───────────────────────── db ─────────────────────────

class _DB:
    def __init__(self, ctx):
        self.ctx = ctx

    def _cached(self, key, fn):
        c = self.ctx.rcache
        if key not in c:
            c[key] = fn()
        return copy.deepcopy(c[key])

    def get_value(self, doctype, filters=None, fieldname="name", as_dict=False, order_by=None, **kw):
        b = self.ctx.backend
        multi = isinstance(fieldname, (list, tuple))
        fields = list(fieldname) if multi else [fieldname]
        key = ("gv", doctype, json.dumps(filters, default=str, sort_keys=True), tuple(fields), order_by, bool(as_dict))

        def run():
            if b.is_single(doctype):
                row = b.get_single(doctype)
                return {f: row.get(f) for f in fields}
            rows = b.get_list(doctype, _sql_filters(filters), fields, order_by=order_by, limit=1)
            return rows[0] if rows else None
        row = self._cached(key, run)
        if row is None:
            return None
        if as_dict:
            return DotDict({f: row.get(f) for f in fields})
        vals = [row.get(f) for f in fields]
        return tuple(vals) if multi else vals[0]

    def exists(self, doctype, filters=None):
        key = ("ex", doctype, json.dumps(filters, default=str, sort_keys=True))
        return self._cached(key, lambda: self.ctx.backend.exists(doctype, _sql_filters(filters)))

    def count(self, doctype, filters=None):
        key = ("ct", doctype, json.dumps(filters, default=str, sort_keys=True))
        return self._cached(key, lambda: self.ctx.backend.count(doctype, _sql_filters(filters)))

    def get_single_value(self, doctype, field):
        key = ("sv", doctype)
        row = self._cached(key, lambda: self.ctx.backend.get_single(doctype))
        return row.get(field)

    def get_default(self, key):
        # Only the Company default is read by the scripts; it is a User Permission / DefaultValue on the ERP user.
        rows = self.ctx.backend.get_list("DefaultValue", {"parent": self.ctx.user, "defkey": key}, ["defvalue"], limit=1)
        return rows[0]["defvalue"] if rows else None

    def set_value(self, doctype, name, field=None, value=None, update_modified=True, **kw):
        values = field if isinstance(field, dict) else {field: value}
        if isinstance(name, dict):                     # filters instead of a name
            hit = self.ctx.backend.get_list(doctype, name, ["name"], limit=1)
            if not hit:
                return
            name = hit[0]["name"]
        self.ctx.engine.set_values(self.ctx, doctype, name, values)

    def sql(self, query, values=None, as_dict=False, pluck=None, **kw):
        return _sql.execute(self.ctx.backend, query, values, as_dict=as_dict, pluck=pluck, cache=self.ctx.sqlcache)

    def commit(self):          # a script on a real site cannot, and ours never needs to
        return None

    def rollback(self, *a, **k):
        raise TSRUnsupported("frappe.db.rollback is not available; the journal compensates failed runs")


def _sql_filters(f):
    if isinstance(f, str) and f:
        return {"name": f}                      # frappe.db.get_value("Company", "My Co", ...) passes a bare name
    return f if f not in ({}, [], "", None) else None


# ───────────────────────── frappe ─────────────────────────

class Frappe:
    """The module the scripts call. One per execution context."""

    utils = _Utils()

    def __init__(self, ctx):
        self.ctx = ctx
        self.db = _DB(ctx)
        self.flags = DotDict()
        self.form_dict = DotDict()
        self.session = DotDict(user=ctx.user)

    # --- control ---
    def throw(self, msg, exc=None, title=None, **kw):
        raise TSRValidationError(str(msg), title or "")

    def msgprint(self, msg, title=None, indicator=None, alert=False, raise_exception=False, **kw):
        self.ctx.messages.append({"message": str(msg), "title": title or "", "indicator": indicator or "", "alert": bool(alert)})
        if raise_exception:
            raise TSRValidationError(str(msg), title or "")

    def log_error(self, title=None, message=None, **kw):
        self.ctx.errors.append({"title": title or "", "message": str(message or "")[:4000]})

    def get_traceback(self, **kw):
        return traceback.format_exc()

    # --- documents ---
    def get_doc(self, doctype, name=None, **kw):
        ctx = self.ctx
        if isinstance(doctype, dict):
            data = dict(doctype)
            if "doctype" not in data:
                raise TSRValidationError("get_doc({...}) needs a doctype")
            return Doc(ctx, data, is_new=True)
        if isinstance(doctype, Doc):
            return doctype
        if name is None or name == doctype and ctx.backend.is_single(doctype):
            data = ctx.backend.get_single(doctype)
            data.setdefault("doctype", doctype)
            d = Doc(ctx, data)
            d.__dict__["_before"] = copy.deepcopy(d.as_dict())
            return d
        data = ctx.backend.get_doc(doctype, name)
        data.setdefault("doctype", doctype)
        d = Doc(ctx, data)
        d.__dict__["_before"] = copy.deepcopy(d.as_dict())
        return d

    get_cached_doc = get_doc

    def new_doc(self, doctype, **kw):
        return Doc(self.ctx, {"doctype": doctype, "docstatus": 0}, is_new=True)

    def copy_doc(self, doc, ignore_no_copy=True):
        data = copy.deepcopy(doc.as_dict())
        for k in ("name", "owner", "creation", "modified", "modified_by", "amended_from"):
            data.pop(k, None)
        data["docstatus"] = 0
        for v in data.values():
            if isinstance(v, list):
                for row in v:
                    if isinstance(row, dict):
                        for k in ("name", "owner", "creation", "modified", "modified_by", "parent"):
                            row.pop(k, None)
                        row["docstatus"] = 0
        return Doc(self.ctx, data, is_new=True)

    def delete_doc(self, doctype, name, force=0, ignore_permissions=False, **kw):
        self.ctx.engine.delete(self.ctx, doctype, name)

    # --- lists ---
    def get_all(self, doctype, filters=None, fields=None, order_by=None, limit=None, limit_page_length=None,
                limit_start=None, pluck=None, or_filters=None, as_list=False, **kw):
        if or_filters:
            raise TSRUnsupported("or_filters are not supported by the runtime")
        if isinstance(filters, str):
            filters = {"name": filters}
        if isinstance(fields, str):
            fields = [fields]
        if pluck:
            fields = [pluck]
        fields = fields or ["name"]
        for f in fields:
            if "(" in f:
                raise TSRUnsupported(f"SQL function in fields is not supported over REST: {f}")
        n = limit if limit is not None else limit_page_length
        if n == 0:
            n = None
        key = ("ga", doctype, json.dumps(filters, default=str, sort_keys=True), tuple(fields), order_by, n, limit_start)
        c = self.ctx.rcache
        if key not in c:
            rows = self.ctx.backend.get_list(doctype, _sql_filters(filters), fields, order_by=order_by,
                                             limit=(n + (limit_start or 0)) if n else None)
            if limit_start:
                rows = rows[limit_start:]
            c[key] = rows
        rows = copy.deepcopy(c[key])
        if pluck:
            return [r.get(pluck) for r in rows]
        if as_list:
            return [tuple(r.get(f) for f in fields) for r in rows]
        return [DotDict(r) for r in rows]

    get_list = get_all

    # --- calls ---
    def call(self, method, **kw):
        out = self.ctx.engine.call(self.ctx, method, kw)
        if isinstance(out, dict) and out.get("doctype") and not out.get("name", None):
            return Doc(self.ctx, out, is_new=True)
        if isinstance(out, dict) and out.get("doctype"):
            return Doc(self.ctx, out)
        return dotify(out) if isinstance(out, dict) else out

    def enqueue(self, *a, **k):
        raise TSRUnsupported("frappe.enqueue: long work is run by the tower's job runner, not from a script")


def safe_builtins() -> dict:
    import builtins
    names = ("abs all any bool dict enumerate filter float int isinstance len list map max min range reversed round set "
             "sorted str sum tuple zip None True False Exception ValueError KeyError TypeError IndexError AttributeError "
             "ZeroDivisionError StopIteration repr hash divmod pow chr ord bytes frozenset slice iter next").split()
    out = {n: getattr(builtins, n) for n in names if hasattr(builtins, n)}
    out["__build_class__"] = None
    return out
