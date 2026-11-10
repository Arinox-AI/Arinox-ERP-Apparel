"""ERP backends for the TSR. One interface, two implementations:

* :class:`HttpBackend` — a Frappe site over REST (token auth). Used against the real ERP and against the
  ERPNext-only test site.
* ``fake.FakeBackend`` (tests) — an in-memory store with the same behaviour for the parts the scripts use.

Reads page until exhausted (``limit_page_length`` caps at the site's max). Child tables are listed through
``frappe.client.get_list`` with ``parent=`` because plain ``/api/resource/<Child>`` refuses them (measured
2026-11-06 on ERPNext v16).
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from decimal import Decimal
from typing import Any, Optional

import requests

from .errors import TSRBackendError, TSRConflict, TSRNotFound, TSRValidationError

def _default(o):
    if isinstance(o, _dt.datetime):
        return o.strftime("%Y-%m-%d %H:%M:%S.%f")
    if isinstance(o, _dt.date):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    raise TypeError(f"{type(o).__name__} is not JSON serialisable")


PAGE = 500
MAX_ROWS = 50000          # a read that would return more than this is refused, not truncated


class Backend:
    """The interface. Subclasses implement the primitives; everything else is derived."""

    # ---- primitives ----
    def get_doc(self, doctype: str, name: str) -> dict: raise NotImplementedError
    def get_list(self, doctype: str, filters=None, fields=None, order_by: str | None = None,
                 limit: int | None = None, parent: str | None = None) -> list[dict]: raise NotImplementedError
    def get_single(self, doctype: str) -> dict: raise NotImplementedError
    def insert(self, doc: dict) -> dict: raise NotImplementedError
    def save(self, doc: dict) -> dict: raise NotImplementedError
    def submit(self, doctype: str, name: str, doc: dict | None = None) -> dict: raise NotImplementedError
    def cancel(self, doctype: str, name: str) -> dict: raise NotImplementedError
    def delete(self, doctype: str, name: str) -> None: raise NotImplementedError
    def set_value(self, doctype: str, name: str, values: dict) -> dict: raise NotImplementedError
    def call(self, method: str, kwargs: dict) -> Any: raise NotImplementedError
    def meta(self, doctype: str) -> dict: raise NotImplementedError
    def add_comment(self, doctype: str, name: str, text: str, kind: str = "Comment") -> None: raise NotImplementedError
    def user_roles(self, user: str) -> list[str]: raise NotImplementedError

    # ---- derived ----
    def exists(self, doctype: str, filters) -> str | None:
        rows = self.get_list(doctype, _name_filter(filters), ["name"], limit=1)
        return rows[0]["name"] if rows else None

    def count(self, doctype: str, filters=None) -> int:
        return len(self.get_list(doctype, filters, ["name"]))

    def get_value(self, doctype: str, filters, fieldname):
        """Mirror of ``frappe.db.get_value``: scalar for a string field, list-like row for several."""
        multi = isinstance(fieldname, (list, tuple))
        fields = list(fieldname) if multi else [fieldname]
        if self.is_single(doctype):
            row = self.get_single(doctype)
            vals = [row.get(f) for f in fields]
            return (vals if multi else vals[0])
        rows = self.get_list(doctype, _name_filter(filters), fields, limit=1)
        if not rows:
            return None
        vals = [rows[0].get(f) for f in fields]
        return vals if multi else vals[0]

    def field_types(self, doctype: str) -> dict:
        """{fieldname: fieldtype} for value coercion on load."""
        try:
            return {f["fieldname"]: f["fieldtype"] for f in self.meta(doctype)["fields"]}
        except Exception:
            return {}

    def table_fields(self, doctype: str) -> set:
        try:
            return {f["fieldname"] for f in self.meta(doctype)["fields"] if f["fieldtype"] in ("Table", "Table MultiSelect")}
        except Exception:
            return set()

    def is_single(self, doctype: str) -> bool:
        try:
            return bool(self.meta(doctype).get("issingle"))
        except Exception:
            return False


def _name_filter(filters):
    """``frappe.db.get_value("X", "NAME", ...)`` passes a bare name; ``{}``/None means no filter."""
    if isinstance(filters, str):
        return {"name": filters}
    return filters or None


class HttpBackend(Backend):
    """A Frappe site over REST. ``base`` like ``http://hosted.localhost:8001``; ``token`` like ``key:secret``."""

    def __init__(self, base: str, token: str, timeout: int = 40, session: Optional[requests.Session] = None):
        self.base = base.rstrip("/")
        self.headers = {"Authorization": f"token {token}"} if token else {}
        self.timeout = timeout
        self.http = session or requests.Session()
        self._meta: dict[str, dict] = {}

    # ---- plumbing ----
    def _req(self, method: str, path: str, params=None, data=None):
        try:
            hdrs = dict(self.headers)
            body = None
            if method != "GET" and data is not None:
                body = json.dumps(data, default=_default)
                hdrs["Content-Type"] = "application/json"
            r = self.http.request(method, self.base + path, headers=hdrs, params=params, data=body, timeout=self.timeout)
        except requests.exceptions.Timeout as e:
            raise TSRBackendError("The ERP did not answer in time.", 0, str(e)[:200])
        except requests.exceptions.RequestException as e:
            raise TSRBackendError("The ERP is not reachable.", 0, str(e)[:200])
        if r.status_code >= 400:
            raise self._error(r)
        try:
            body = r.json()
        except ValueError:
            raise TSRBackendError("The ERP answered with something that is not JSON.", r.status_code, r.text[:200])
        return body

    @staticmethod
    def _server_messages(r) -> str:
        try:
            j = r.json()
        except ValueError:
            return r.text[:300]
        msgs = j.get("_server_messages")
        if msgs:
            try:
                out = []
                for m in json.loads(msgs):
                    out.append(re.sub(r"<[^>]+>", "", json.loads(m).get("message", "")))
                return " ".join(x for x in out if x)[:600]
            except Exception:
                pass
        return str(j.get("exception") or j.get("message") or "")[:600]

    def _error(self, r):
        msg = self._server_messages(r)
        low = (msg or "").lower()
        if r.status_code == 404 or "doesnotexist" in low:
            return TSRNotFound("", msg)
        if "TimestampMismatchError" in low or "document has been modified" in low:
            return TSRConflict("", "", "", "")
        if r.status_code in (417, 417) or "ValidationError" in (r.text or "")[:2000] or "validationerror" in low:
            return TSRValidationError(msg or "The ERP refused the change.")
        if r.status_code == 503:
            return TSRBackendError("The ERP is busy (its job queue is full). Nothing was changed; try again shortly.", 503, msg)
        if r.status_code in (401, 403):
            return TSRBackendError("The ERP refused the credentials or the permission.", r.status_code, msg)
        return TSRBackendError(f"ERP error {r.status_code}", r.status_code, msg)

    # ---- reads ----
    def get_doc(self, doctype, name):
        try:
            body = self._req("GET", f"/api/resource/{doctype}/{requests.utils.quote(str(name), safe='')}")
        except TSRNotFound:
            raise TSRNotFound(doctype, name)
        return body["data"]

    def get_list(self, doctype, filters=None, fields=None, order_by=None, limit=None, parent=None):
        out: list[dict] = []
        start = 0
        want = limit if limit is not None else MAX_ROWS
        while len(out) < want:
            n = min(PAGE, want - len(out))
            params = {"doctype": doctype, "fields": json.dumps(fields or ["name"], default=_default),
                      "limit_start": start, "limit_page_length": n}
            if filters:
                params["filters"] = json.dumps(filters, default=_default)
            if order_by:
                params["order_by"] = order_by
            if parent:
                params["parent"] = parent
            else:
                # child doctypes need a parent doctype; discover it once and cache it in the meta
                if self._is_table(doctype):
                    params["parent"] = self._parent_of(doctype)
            try:
                rows = self._req("GET", "/api/method/frappe.client.get_list", params=params)["message"]
            except TSRNotFound:
                raise TSRNotFound(doctype, "")
            out.extend(rows)
            if len(rows) < n:
                break
            start += n
        else:
            if limit is None:
                raise TSRBackendError(f"{doctype}: more than {MAX_ROWS} rows; narrow the filter.", 0, "")
        return out

    def get_single(self, doctype):
        try:
            return self._req("GET", f"/api/resource/{doctype}/{doctype}")["data"]
        except TSRNotFound:
            return {}

    def count(self, doctype, filters=None):
        params = {"doctype": doctype}
        if filters:
            params["filters"] = json.dumps(filters, default=_default)
        return int(self._req("GET", "/api/method/frappe.client.get_count", params=params)["message"] or 0)

    def meta(self, doctype):
        m = self._meta.get(doctype)
        if m is None:
            docs = self._req("GET", "/api/method/frappe.desk.form.load.getdoctype",
                             params={"doctype": doctype})["docs"]
            main = next(d for d in docs if d["name"] == doctype)
            m = {"name": doctype, "istable": bool(main.get("istable")), "issingle": bool(main.get("issingle")),
                 "is_submittable": bool(main.get("is_submittable")), "autoname": main.get("autoname"),
                 "fields": [{"fieldname": f["fieldname"], "fieldtype": f["fieldtype"], "options": f.get("options"),
                             "reqd": f.get("reqd"), "read_only": f.get("read_only"), "hidden": f.get("hidden"),
                             "label": f.get("label"), "in_list_view": f.get("in_list_view"),
                             "depends_on": f.get("depends_on"), "allow_on_submit": f.get("allow_on_submit"),
                             "permlevel": f.get("permlevel") or 0, "default": f.get("default")}
                            for f in main.get("fields", [])],
                 "permissions": main.get("permissions", [])}
            self._meta[doctype] = m
        return m

    def _is_table(self, doctype: str) -> bool:
        try:
            return self.meta(doctype)["istable"]
        except Exception:
            return False

    #: child tables that more than one doctype owns: the one the Arinox scripts read through (found by S5: the roll batches of a receipt are
    #: `Serial and Batch Entry` rows of a Serial and Batch Bundle; the first parent the ERP lists is Stock Reservation Entry, which has none of them)
    _PARENT_PREFERENCE = {"Serial and Batch Entry": "Serial and Batch Bundle"}

    def _parent_of(self, child: str) -> str:
        if child in self._PARENT_PREFERENCE:
            return self._PARENT_PREFERENCE[child]
        rows = self._req("GET", "/api/method/frappe.client.get_list",
                         params={"doctype": "DocField", "fields": json.dumps(["parent"]),
                                 "filters": json.dumps({"options": child, "fieldtype": ["in", ["Table", "Table MultiSelect"]]}, default=_default),
                                 "limit_page_length": 1, "parent": "DocType"})["message"]
        if rows:
            return rows[0]["parent"]
        # a child table added to a standard doctype by a Custom Field (found by S9: Shipment.apparel_declarations -> Shipment Declaration) has no DocField row
        cf = self._req("GET", "/api/method/frappe.client.get_list",
                       params={"doctype": "Custom Field", "fields": json.dumps(["dt"]),
                               "filters": json.dumps({"options": child, "fieldtype": ["in", ["Table", "Table MultiSelect"]]}, default=_default),
                               "limit_page_length": 1})["message"]
        if not cf:
            raise TSRBackendError(f"No parent doctype found for child table {child}.", 0, "")
        return cf[0]["dt"]

    # ---- writes ----
    def insert(self, doc):
        doc = dict(doc)
        return self._req("POST", "/api/method/frappe.client.insert", data={"doc": doc})["message"]

    def save(self, doc):
        """Optimistic save: the document carries the ``modified`` it was read with; the server refuses on mismatch."""
        try:
            return self._req("POST", "/api/method/frappe.client.save", data={"doc": doc})["message"]
        except TSRConflict:
            cur = self.get_value(doc["doctype"], doc["name"], "modified")
            raise TSRConflict(doc["doctype"], doc["name"], str(doc.get("modified")), str(cur))

    def submit(self, doctype, name, doc=None):
        payload = dict(doc) if doc else self.get_doc(doctype, name)
        payload["docstatus"] = 0           # the server performs the 0 -> 1 transition itself
        payload.setdefault("doctype", doctype)
        return self._req("POST", "/api/method/frappe.client.submit", data={"doc": payload})["message"]

    def cancel(self, doctype, name):
        return self._req("POST", "/api/method/frappe.client.cancel", data={"doctype": doctype, "name": name})["message"]

    def delete(self, doctype, name):
        try:
            self._req("DELETE", f"/api/resource/{doctype}/{requests.utils.quote(str(name), safe='')}")
        except TSRNotFound:
            return

    def set_value(self, doctype, name, values):
        return self._req("POST", "/api/method/frappe.client.set_value",
                         data={"doctype": doctype, "name": name, "fieldname": values})["message"]

    def call(self, method, kwargs):
        return self._req("POST", f"/api/method/{method}", data=kwargs).get("message")

    def add_comment(self, doctype, name, text, kind="Comment"):
        self._req("POST", "/api/method/frappe.desk.form.utils.add_comment",
                  data={"reference_doctype": doctype, "reference_name": name, "content": text,
                        "comment_email": "Administrator", "comment_by": "Cortex Tower"})

    def user_roles(self, user):
        return self.get_list("Has Role", {"parent": user, "parenttype": "User"}, ["role"]) and \
            [r["role"] for r in self.get_list("Has Role", {"parent": user, "parenttype": "User"}, ["role"])]
