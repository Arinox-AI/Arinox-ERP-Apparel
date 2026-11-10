"""A ``frappe`` stand-in for *test code*, so the repo's own hosted tests (``portable/hosted_tests``) can run
unchanged through the TSR: every document operation becomes REST + the vendored scripts, with the ERP's own
Server Scripts switched off. Used only by ``tools/conformance.py`` — production code never imports this.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import types
from typing import Optional

from . import shim
from .errors import TSRNotFound, TSRUnsupported, TSRValidationError
from .runner import Context, Engine


class State:
    ctx: Optional[Context] = None
    engine: Optional[Engine] = None
    backend = None


S = State()


class _ScriptHandle:
    def __init__(self, name):
        self.name = name

    def execute_method(self):
        return S.engine.run_api(S.ctx, self.name, form=dict(_local.form_dict))

    def execute_scheduled_method(self):
        return S.engine.run_scheduler(S.ctx, self.name)

    def __getattr__(self, k):
        raise TSRUnsupported(f"Server Script.{k} is not available through the TSR")


class _Local:
    def __init__(self):
        self.form_dict = shim.DotDict()


_local = _Local()


class _DB:
    """The shim's db plus the extra calls tests use."""

    def __init__(self):
        pass

    def __getattr__(self, k):
        inner = shim.Frappe(S.ctx).db
        return getattr(inner, k)

    def set_single_value(self, doctype, field, value=None, **kw):
        values = field if isinstance(field, dict) else {field: value}
        S.engine.set_values(S.ctx, doctype, doctype, values)

    def delete(self, doctype, filters=None):
        for r in S.ctx.backend.get_list(doctype, filters or None, ["name"]):
            S.engine.delete(S.ctx, doctype, r["name"])

    def savepoint(self, *a, **k):
        return None

    def rollback(self, *a, **k):
        return None

    def sql(self, query, values=None, as_dict=False, pluck=None, **kw):
        q = query.strip().lower()
        if q.startswith(("update", "delete", "insert")):
            raise TSRUnsupported("raw SQL write: not possible over REST (hosted sandbox refuses it too)")
        return shim.Frappe(S.ctx).db.sql(query, values, as_dict=as_dict, pluck=pluck)


class _Session:
    @property
    def user(self):
        return S.ctx.user


def _get_doc(doctype, name=None, **kw):
    if doctype == "Server Script":
        return _ScriptHandle(name)
    return shim.Frappe(S.ctx).get_doc(doctype, name)


def _set_user(user):
    S.ctx.user = user


def _add_roles(self, *roles):
    have = {r.role for r in (self.roles or [])}
    for role in roles:
        if role not in have:
            self.append("roles", {"role": role})
    self.save()


shim.Doc.add_roles = _add_roles


def install(engine: Engine, backend, make_ctx):
    """Replace ``frappe`` in ``sys.modules``. ``make_ctx()`` builds a fresh Context for each test."""
    S.engine, S.backend, S.make_ctx = engine, backend, make_ctx

    f = types.ModuleType("frappe")
    f.db = _DB()
    f.local = _local
    f.session = _Session()
    f.flags = shim.DotDict()
    f.get_doc = _get_doc
    f.new_doc = lambda dt, **k: shim.Frappe(S.ctx).new_doc(dt)
    f.get_all = lambda *a, **k: shim.Frappe(S.ctx).get_all(*a, **k)
    f.get_list = f.get_all
    f.delete_doc = lambda *a, **k: shim.Frappe(S.ctx).delete_doc(*a, **k)
    f.throw = lambda msg, *a, **k: (_ for _ in ()).throw(TSRValidationError(str(msg)))
    f.msgprint = lambda *a, **k: None
    f.set_user = _set_user
    f.as_json = lambda o, indent=None: json.dumps(o, default=str)
    f.generate_hash = lambda txt=None, length=10: hashlib.sha1(f"{time.time_ns()}{txt}".encode()).hexdigest()[:length]
    f._dict = shim.DotDict
    f.DoesNotExistError = TSRNotFound
    f.ValidationError = TSRValidationError
    f.utils = types.ModuleType("frappe.utils")
    for n in ("flt", "cint", "getdate", "nowdate", "now_datetime", "add_days", "date_diff", "formatdate", "ceil", "floor"):
        setattr(f.utils, n, getattr(shim._Utils, n))
    f.utils.add_months = lambda d, m: _add_months(d, m)
    f.utils.get_datetime = lambda v=None: shim.now_datetime() if v is None else v
    f.utils.today = shim.nowdate
    f.utils.add_to_date = lambda d, days=0, **k: shim.add_days(d, days)
    f.utils.safe_json_loads = lambda s: json.loads(s)
    sys.modules["frappe"] = f
    sys.modules["frappe.utils"] = f.utils
    desk = types.ModuleType("frappe.desk")
    qr = types.ModuleType("frappe.desk.query_report")

    def _run(*a, **k):
        raise TSRUnsupported("Script Reports run through tsr.reports in the tower, not through frappe.desk.query_report")
    qr.run = _run
    desk.query_report = qr
    f.desk = desk
    sys.modules["frappe.desk"] = desk
    sys.modules["frappe.desk.query_report"] = qr
    return f


def _add_months(d, m):
    import calendar
    import datetime as dt
    d = shim.getdate(d)
    y, mo = divmod(d.month - 1 + int(m), 12)
    y, mo = d.year + y, mo + 1
    return d.replace(year=y, month=mo, day=min(d.day, calendar.monthrange(y, mo)[1]))
