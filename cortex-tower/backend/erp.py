"""Cortex Operations Control Tower — live KOGO ERP (Frappe / KOGO_SAS) client.

The **read** helpers issue only HTTP GET and never change anything.

The **write** helpers (``erp_create`` / ``erp_update`` / ``erp_delete``) are used
ONLY from the opt-in write path in ``writes.py``, which is mode-gated, drafts-only
for submittable doctypes, idempotent and reversible. Nothing in the read path can
reach them.

Every helper swallows errors and returns an empty value (``[]`` / ``{}`` / ``0`` /
``False``) — nothing here raises. Credentials are bootstrapped from the KOGO
gateway (env: ``API_PATH``, ``USER_JWT_TOKEN``, ``SWARM_ID`` / ``AGENT_ID``) and
cached to ``backend/data/sas_creds.json`` so the app keeps working even when the
gateway JWT is absent at runtime; on an auth failure the creds are re-discovered
once and the request retried.

Environment reads happen ONLY here and in ``config.py`` — never in business code.
"""

from __future__ import annotations

import json
import time
from collections import namedtuple
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

import config
import secret_store

# KOGO ERP application id (app_type KOGO_SAS) and gateway/JWT come from config.py
# (single source of truth — no env reads in business code).
APP_ID = config.ERP_APP_ID

DATA_DIR = Path(__file__).resolve().parent / "data"
CREDS_PATH = DATA_DIR / "sas_creds.json"

GATEWAY_TIMEOUT = 40
ERP_TIMEOUT = 40
DATA_TTL = 60       # seconds — short cache so repeated calls stay responsive
STATUS_TTL = 15     # seconds — how long a connectivity probe result is reused

_CREDS_QUERY = (
    "query($a:String!,$w:ID!){ getKogoSasApiKeys(app_id:$a, workspace_id:$w)"
    "{ api_base api_key api_secret } }"
)

_creds: Optional[dict] = None
_last_error: Optional[str] = None
_status_cache: Optional[tuple] = None
_data_cache: dict = {}
#: (doctype, base) -> field names this site refused in a list query (see erp_get_checked).
_DROPPED_FIELDS: dict = {}


# ────────────────────────────────────────────────────────────────────────────
# Internal plumbing
# ────────────────────────────────────────────────────────────────────────────

def _set_error(err: Any) -> None:
    global _last_error
    try:
        _last_error = (str(err) or type(err).__name__)[:300]
    except Exception:
        _last_error = "unknown_error"


def _gateway(query: str, variables: dict) -> dict:
    url = config.API_PATH or ""
    if url and not url.endswith("/gateway"):
        url += "/gateway"
    r = requests.post(
        url,
        json={"query": query, "variables": variables},
        headers={
            "Authorization": f"Bearer {config.USER_JWT_TOKEN}",
            "Content-Type": "application/json",
        },
        timeout=GATEWAY_TIMEOUT,
    )
    r.raise_for_status()
    return r.json().get("data") or {}


def _discover() -> dict:
    """Ask the KOGO gateway for this workspace's KOGO ERP API keys."""
    ws = config.SWARM_ID or config.AGENT_ID
    data = _gateway(_CREDS_QUERY, {"a": APP_ID, "w": ws})
    k = data.get("getKogoSasApiKeys") or {}
    base = (k.get("api_base") or "").rstrip("/")
    key = k.get("api_key")
    secret = k.get("api_secret")
    if not base or not key or not secret:
        return {}
    return {"BASE": base, "AUTH": {"Authorization": f"token {key}:{secret}"}}


def _read_cache() -> dict:
    """Read the cached creds — sealed (v2) or legacy plaintext, both understood."""
    try:
        raw = secret_store.open_json_file(CREDS_PATH)
        if raw.get("BASE") and (raw.get("AUTH") or {}).get("Authorization"):
            return {"BASE": str(raw["BASE"]).rstrip("/"), "AUTH": secret_store.open_dict(raw["AUTH"])}
    except Exception:
        pass
    return {}


def _write_cache(creds: dict) -> None:
    """Cache the creds **sealed** with 0600 permissions (2026-11-04, D-125).

    The file is a convenience so the app still answers when the gateway JWT is absent;
    it must never be a plaintext API key sitting in a folder that gets backed up.
    """
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        secret_store.seal_json_file(CREDS_PATH, {"BASE": creds.get("BASE"),
                                                 "AUTH": creds.get("AUTH") or {}})
    except Exception:
        pass


def _rediscover() -> dict:
    """Re-discover creds from the gateway and re-cache them. Never raises."""
    global _creds
    try:
        fresh = _discover()
    except Exception as e:
        _set_error(e)
        return {}
    if fresh:
        _write_cache(fresh)
        _creds = fresh
    return fresh


def get_creds() -> dict:
    """Return cached ERP creds (``{"BASE": ..., "AUTH": {...}}``), re-discovering
    when missing. Never raises — returns ``{}`` when unavailable."""
    global _creds
    if _creds:
        return _creds
    cached = _read_cache()
    if cached:
        _creds = cached
        return _creds
    return _rediscover()


def _request_ex(path: str, params: Optional[dict] = None, retry: bool = True):
    """GET ``<base><path>`` with the failure **classified**.

    Returns ``(ok, payload|None, status:int, reason:str, detail:str)``. Never raises.

    ``reason`` is one of ``""`` (ok), ``record_missing``, ``doctype_missing``,
    ``field_not_permitted``, ``auth``, ``timeout``, ``unreachable``, ``http_<code>``.
    A 404 on a *list* endpoint means the doctype does not exist; a 404 on a
    *document* endpoint means the record does not exist. Those are different
    facts and callers must not confuse them (2026-11-04, D-122).
    """
    global _creds, _status_cache
    creds = get_creds()
    base = (creds or {}).get("BASE") or ""
    headers = (creds or {}).get("AUTH") or {}
    if not base:
        _set_error(_last_error or "no_erp_credentials")
        return False, None, 0, "unreachable", "no_erp_credentials"
    try:
        r = requests.get(base + path, headers=headers, params=params or {}, timeout=ERP_TIMEOUT)
        if r.status_code in (401, 403) and retry:
            # Creds are probably stale — re-discover once, then retry.
            _set_error(f"erp_auth_failed_{r.status_code}")
            _creds = None
            _status_cache = None
            if _rediscover():
                return _request_ex(path, params, retry=False)
            return False, None, r.status_code, "auth", _readable_error(r)
        if r.status_code >= 400:
            _set_error(f"erp_http_{r.status_code}")
            detail = _readable_error(r)
            reason = _classify_failure(r.status_code, detail, path)
            return False, None, r.status_code, reason, detail
        payload = r.json()
        if isinstance(payload, dict) and payload.get("exc"):
            reason = _classify_failure(200, str(payload.get("exc_type") or ""), path)
            _set_error(payload.get("exc_type") or "erp_exception")
            return False, None, 200, reason, str(payload.get("exception") or "")[:300]
        return True, payload, r.status_code, "", ""
    except requests.exceptions.Timeout as e:
        _set_error(e)
        return False, None, 0, "timeout", str(e)[:200]
    except requests.exceptions.ConnectionError as e:
        _set_error(e)
        return False, None, 0, "unreachable", str(e)[:200]
    except Exception as e:
        _set_error(e)
        return False, None, 0, "unreachable", str(e)[:200]


def _path_is_list(path: str) -> bool:
    """True when the path addresses a doctype's list endpoint, not one document."""
    rest = path.split("/api/resource/")[-1].strip("/")
    return bool(rest) and "/" not in rest


def _classify_failure(status: int, detail: str, path: str) -> str:
    """Name WHY a read failed. The caller's decision depends on this string.

    ``field_not_permitted`` is a *query* error, not a data error: treating it as
    ``missing`` would make the caller re-create a record that exists. This bench
    throws it routinely (``417 Field not permitted in query: subject``) exactly
    as it throws ``403`` on child tables such as ``Sales Order Item``.
    """
    low = (detail or "").lower()
    # order matters: "Field not permitted in query" is a 417 QUERY error thrown by the
    # DataError handler, and reading it as `missing` would re-create a record that exists.
    if "field not permitted" in low or "dataerror" in low:
        return "field_not_permitted"
    if status in (401, 403) or "insufficient permission" in low or "permission" in low \
            or "not permitted" in low:
        return "auth"
    if "doesnotexist" in low or "not found" in low:
        # a missing doctype is reported as "DocType X not found"; otherwise the path
        # shape decides — /api/resource/<Doctype> is a list, .../<name> is a record
        if "doctype" in low:
            return "doctype_missing"
        return "doctype_missing" if _path_is_list(path) else "record_missing"
    if "frappe.core.doctype" in low and "no module named" in low:
        # GET /api/resource/<AbsentDoctype>/<name> answers 500 with the module path,
        # not a 404 — the doctype is absent, the record was never a question.
        return "doctype_missing"
    if status == 404:
        # /api/resource/<Doctype>            -> the doctype is absent from the site
        # /api/resource/<Doctype>/<name>     -> the record is absent
        tail = path.rstrip("/").split("/api/resource/")
        rest = (tail[1] if len(tail) > 1 else "").strip("/")
        return "doctype_missing" if rest and "/" not in rest else "record_missing"
    if status >= 500:
        return f"http_{status}"
    return f"http_{status}" if status else "unreachable"


def _request(path: str, params: Optional[dict] = None, retry: bool = True):
    """GET ``<base><path>``. Returns ``(ok, payload_dict|None)``. Never raises.

    The two-state wrapper over :func:`_request_ex` — kept so the 149 existing read
    call sites did not have to change when the tri-state layer arrived.
    """
    ok, payload, _status, _reason, _detail = _request_ex(path, params, retry)
    return ok, payload


def _cache_get(key):
    hit = _data_cache.get(key)
    if hit and (time.time() - hit[0]) < DATA_TTL:
        return True, hit[1]
    return False, None


def erp_invalidate_cache() -> None:
    """Drop the read cache — call after any write so reads reflect it."""
    _data_cache.clear()


def _readable_error(r) -> str:
    """Best-effort extraction of a human message from a Frappe error response."""
    try:
        body = r.json()
    except Exception:
        return f"http_{r.status_code}"
    if isinstance(body, dict):
        msgs = body.get("_server_messages")
        if msgs:
            try:
                parsed = json.loads(msgs)
                if isinstance(parsed, list) and parsed:
                    first = json.loads(parsed[0]) if isinstance(parsed[0], str) else parsed[0]
                    text = (first or {}).get("message") if isinstance(first, dict) else str(first)
                    if text:
                        return str(text)[:300]
            except Exception:
                pass
        for k in ("exception", "exc_type", "message"):
            if body.get(k):
                return str(body[k])[:300]
    return f"http_{r.status_code}"


def _write_request(method: str, path: str, data: Optional[dict] = None, retry: bool = True):
    """POST/PUT/DELETE ``<base><path>``. Returns ``(ok, payload, error)``.

    Only reached from ``writes.py``. Never raises.
    """
    global _creds, _status_cache
    creds = get_creds()
    base = (creds or {}).get("BASE") or ""
    headers = dict((creds or {}).get("AUTH") or {})
    headers["Content-Type"] = "application/json"
    if not base:
        return False, None, "no_erp_credentials"
    try:
        r = requests.request(method, base + path, headers=headers, json=data, timeout=ERP_TIMEOUT)
        if r.status_code in (401, 403) and retry:
            _creds = None
            _status_cache = None
            if _rediscover():
                return _write_request(method, path, data, retry=False)
            return False, None, f"erp_auth_failed_{r.status_code}"
        if r.status_code >= 400:
            return False, None, _readable_error(r)
        erp_invalidate_cache()
        try:
            return True, r.json(), None
        except Exception:
            return True, {}, None
    except Exception as e:
        _set_error(e)
        return False, None, str(e)[:300]


def erp_create(doctype: str, data: dict):
    """Create one document. Returns ``(ok, doc_dict, error)``. Never raises."""
    path = f"/api/resource/{quote(str(doctype))}"
    ok, payload, err = _write_request("POST", path, data)
    doc = (payload or {}).get("data") if ok else None
    if ok:
        erp_invalidate_cache()
    return ok, (doc if isinstance(doc, dict) else {}), err


def erp_update(doctype: str, name: str, data: dict):
    """Update one document. Returns ``(ok, doc_dict, error)``. Never raises."""
    path = f"/api/resource/{quote(str(doctype))}/{quote(str(name))}"
    ok, payload, err = _write_request("PUT", path, data)
    doc = (payload or {}).get("data") if ok else None
    if ok:
        erp_invalidate_cache()
    return ok, (doc if isinstance(doc, dict) else {}), err


def erp_delete(doctype: str, name: str):
    """Delete one document. Returns ``(ok, error)``. Never raises."""
    path = f"/api/resource/{quote(str(doctype))}/{quote(str(name))}"
    ok, _payload, err = _write_request("DELETE", path)
    if ok:
        erp_invalidate_cache()
    return ok, err


def erp_submit(doctype: str, name: str):
    """Submit an existing document. Returns ``(ok, doc_dict, error)``. Never raises."""
    doc = erp_doc(doctype, name)
    if not doc:
        return False, {}, "document not found"
    ok, payload, err = _write_request(
        "POST", "/api/method/frappe.client.submit", {"doc": json.dumps(doc)})
    if not ok:
        return False, {}, err
    erp_invalidate_cache()
    return True, (payload or {}).get("message") or {}, None


def erp_cancel(doctype: str, name: str):
    """Cancel a submitted document. Returns ``(ok, error)``. Never raises."""
    ok, _payload, err = _write_request(
        "POST", "/api/method/frappe.client.cancel", {"doctype": str(doctype), "name": str(name)})
    if not ok:
        return False, err
    erp_invalidate_cache()
    return True, None


def _cache_put(key, value) -> None:
    _data_cache[key] = (time.time(), value)


def _base_key():
    return ((get_creds() or {}).get("BASE") or "")


# ────────────────────────────────────────────────────────────────────────────
# Public read helpers — all GET, all error-swallowing
# ────────────────────────────────────────────────────────────────────────────

def erp_get_checked(doctype: str, fields=None, filters=None, limit: int = 500, order=None):
    """List documents from ``doctype``. Returns ``(ok: bool, rows: list)``.

    Use this when the caller needs to distinguish "empty result" from "read
    failed". Never raises.

    **Field tolerance (2026-11-06).** A list query is all-or-nothing on Frappe: ONE field
    this site does not carry (or does not permit in a query) throws 417 and the caller
    gets nothing at all. That is how a dashboard built against one ERP went blank against
    this one over two Cortex-only custom fields (``custom_source_document``,
    ``custom_source_terms``). So when the failure is ``field_not_permitted`` the offending
    field is dropped, the query retried, and the field recorded in
    :func:`last_dropped_fields` — a missing field costs one blank column, never the screen.
    """
    doctype = str(doctype)
    path = f"/api/resource/{quote(doctype)}"
    base_fields = list(fields) if fields is not None else None
    dropped: list[str] = []
    params: dict = {"limit_page_length": int(limit or 0)}
    if base_fields is not None:
        params["fields"] = json.dumps(base_fields)
    if filters is not None:
        params["filters"] = json.dumps(filters)
    if order:
        params["order_by"] = order

    key = ("get", _base_key(), doctype, json.dumps(fields), json.dumps(filters), limit, order)
    cached, val = _cache_get(key)
    if cached:
        return True, val

    for _attempt in range(24):                       # bounded: at most one drop per field
        ok, payload, _status, reason, detail = _request_ex(path, params)
        if ok:
            if dropped:
                _DROPPED_FIELDS[(doctype, _base_key())] = dropped
            break
        if reason != "field_not_permitted":
            return False, []
        bad = _offending_field(detail, json.loads(params.get("fields") or "[]"))
        if not bad:
            return False, []
        dropped.append(bad)
        params["fields"] = json.dumps([f for f in json.loads(params["fields"]) if f != bad])
    else:
        return False, []

    data = (payload or {}).get("data")
    rows = data if isinstance(data, list) else []
    _cache_put(key, rows)
    return True, rows


def _offending_field(detail: str, requested) -> str:
    """The field name out of ``417 Field not permitted in query: <field>``.

    Falls back to the first requested field the message names, so an unexpected wording still
    makes progress instead of giving up.
    """
    msg = str(detail or "")
    for marker in ("not permitted in query:", "Field not permitted in query:", "not permitted:"):
        if marker in msg:
            tail = msg.split(marker, 1)[1].strip().split()[0] if msg.split(marker, 1)[1].strip() else ""
            if tail:
                return tail.strip("'\".,")
    for f in requested:
        if f and str(f) in msg:
            return str(f)
    return ""


def last_dropped_fields(doctype: str = "") -> list:
    """Fields this site refused in a list query, so the UI can say why a column is blank."""
    key = (str(doctype), _base_key()) if doctype else None
    if key:
        return list(_DROPPED_FIELDS.get(key) or [])
    out = []
    for v in _DROPPED_FIELDS.values():
        out.extend(v)
    return sorted(set(out))



def erp_get(doctype: str, fields=None, filters=None, limit: int = 500, order=None) -> list:
    """List documents from ``doctype``. Returns ``[]`` on any failure. Never raises."""
    try:
        _ok, rows = erp_get_checked(doctype, fields=fields, filters=filters, limit=limit, order=order)
        return rows
    except Exception as e:
        _set_error(e)
        return []


def erp_doc(doctype: str, name: str) -> dict:
    """Fetch a single full document (required for child tables such as ``items``).
    Returns ``{}`` on any failure. Never raises."""
    try:
        path = f"/api/resource/{quote(str(doctype))}/{quote(str(name))}"
        key = ("doc", _base_key(), str(doctype), str(name))
        cached, val = _cache_get(key)
        if cached:
            return val
        ok, payload = _request(path)
        if not ok:
            return {}
        data = (payload or {}).get("data")
        if not isinstance(data, dict):
            return {}
        _cache_put(key, data)
        return data
    except Exception as e:
        _set_error(e)
        return {}


# ────────────────────────────────────────────────────────────────────────────
# Tri-state reads — FOUND · MISSING · UNAVAILABLE  (2026-11-04, D-122)
#
# Why this exists: ``erp_doc`` returns ``{}`` for a 404, a permission refusal and a
# timeout alike, so "this record was deleted" and "I could not check" were the same
# answer to every caller. The intake ledger then treated a deleted record as
# "already created" and a Sales Order was built against a ghost. Every caller that
# has to *decide* something must use these; callers that only paint a dashboard may
# keep the degrading versions above.
# ────────────────────────────────────────────────────────────────────────────

FOUND = "found"
MISSING = "missing"
UNAVAILABLE = "unavailable"

ReadResult = namedtuple("ReadResult", "state value reason detail")


def _result(ok: bool, payload, reason: str, detail: str, single: bool):
    if ok:
        data = (payload or {}).get("data")
        if single:
            return ReadResult(FOUND, data if isinstance(data, dict) else {}, "", "")
        return ReadResult(FOUND, data if isinstance(data, list) else [], "", "")
    state = MISSING if reason in ("record_missing", "doctype_missing") else UNAVAILABLE
    empty = {} if single else []
    return ReadResult(state, empty, reason or "unknown", detail)


def erp_doc_checked(doctype: str, name: str, use_cache: bool = False) -> ReadResult:
    """One document, with the difference between absent and unreadable preserved.

    ``use_cache=False`` by default on purpose: a just-deleted record would otherwise
    be served from the 60-second read cache and read as FOUND (the resolution path
    must see the ERP, not a memory of it).
    """
    try:
        path = f"/api/resource/{quote(str(doctype))}/{quote(str(name))}"
        key = ("doc", _base_key(), str(doctype), str(name))
        if use_cache:
            cached, val = _cache_get(key)
            if cached:
                return ReadResult(FOUND, val, "", "")
        ok, payload, _status, reason, detail = _request_ex(path)
        res = _result(ok, payload, reason, detail, single=True)
        if res.state == FOUND and use_cache:
            _cache_put(key, res.value)
        return res
    except Exception as e:
        _set_error(e)
        return ReadResult(UNAVAILABLE, {}, "unreachable", str(e)[:200])


def erp_list_checked(doctype: str, fields=None, filters=None, limit: int = 500,
                     order: Optional[str] = None, use_cache: bool = True) -> ReadResult:
    """A list, with an empty result distinguished from a failed read."""
    try:
        path = f"/api/resource/{quote(str(doctype))}"
        params: dict = {"limit_page_length": int(limit or 0)}
        if fields is not None:
            params["fields"] = json.dumps(fields)
        if filters is not None:
            params["filters"] = json.dumps(filters)
        if order:
            params["order_by"] = order
        key = ("get", _base_key(), str(doctype), json.dumps(fields), json.dumps(filters), limit, order)
        if use_cache:
            cached, val = _cache_get(key)
            if cached:
                return ReadResult(FOUND, val if isinstance(val, list) else [], "", "")
        ok, payload, _status, reason, detail = _request_ex(path, params)
        res = _result(ok, payload, reason, detail, single=False)
        if res.state == FOUND and use_cache:
            _cache_put(key, res.value)
        return res
    except Exception as e:
        _set_error(e)
        return ReadResult(UNAVAILABLE, [], "unreachable", str(e)[:200])


def erp_ref_state(doctype: str, name: str) -> str:
    """``found`` | ``missing`` | ``unavailable`` for one (doctype, name) pointer.

    The one call the intake ledger needs: it answers "does this record still exist?"
    instead of trusting a local list. Never raises.
    """
    return erp_doc_checked(doctype, name).state


def erp_delete_checked(doctype: str, name: str):
    """Delete one document, telling *already gone* apart from *could not delete*.

    Returns ``(ok, state, error)`` where ``ok`` is True when the record is gone
    afterwards — whether this call removed it or it was already absent. A rollback
    must not report a missing record as a failure to roll back (2026-11-04).
    """
    try:
        path = f"/api/resource/{quote(str(doctype))}/{quote(str(name))}"
        ok, _payload, err = _write_request("DELETE", path)
        if ok:
            return True, "deleted", ""
        low = (err or "").lower()
        if "doesnotexist" in low or "not found" in low or "404" in low:
            return True, "already_missing", ""
        return False, "unavailable", err or "delete failed"
    except Exception as e:
        _set_error(e)
        return False, "unavailable", str(e)[:200]


# ────────────────────────────────────────────────────────────────────────────
# Links into the ERP — the ONE place this app builds an ERP web address
# ────────────────────────────────────────────────────────────────────────────
#
# Every screen that offers "open this in the ERP" asks for the address here; no module, page or component types a path
# of its own. Two things are asked of the ERP instead of being assumed:
#
# * **where its desk lives** — a site that has moved off ``/app`` answers ``/desk`` and ``/app`` only by a redirect, an
#   older one has no ``/desk`` at all (see :func:`desk_prefix`);
# * **how a doctype is spelled in a route** — the desk router registers every readable DocType under
#   ``name.lower().replace(" ", "-")`` (``frappe.router.slug`` in this site's own desk bundle, and the doctype has to be
#   in ``boot.user.can_read`` for the route to resolve at all), which is :func:`doctype_slug`.
#
# A wrong segment does not error: the desk simply opens its **home page**, which is exactly the bug this replaces
# (2026-11-09: "take me to the ERP takes me to the main page and not the intended page").

_DESK_PREFIX: Optional[tuple] = None       # (site base, "desk" | "app"), asked once per site
_DESK_PROBE_FAILED_AT: float = 0.0          # when the last probe could not reach the site (back-off below)
_DESK_BACKOFF = 120.0                       # seconds: do not re-probe a site that just refused to answer
_SLUG_CACHE: dict = {}                      # doctype -> route segment


def doctype_slug(doctype: str) -> str:
    """The route segment the ERP's desk router uses for a DocType: ``Sales Order`` -> ``sales-order``.

    Derived, never a table of literals: Frappe slugifies the DocType name itself, and it does it for **every** readable
    doctype, including the Cortex ones (Tech Pack, Cost Sheet, Sales Contract, Price Negotiation).
    """
    dt = str(doctype or "").strip()
    if not dt:
        return ""
    slug = _SLUG_CACHE.get(dt)
    if slug is None:
        slug = _SLUG_CACHE[dt] = dt.lower().replace(" ", "-")
    return slug


def desk_prefix() -> str:
    """Where THIS ERP serves its desk: ``desk`` or ``app``. Asked once, then remembered.

    Frappe moved the desk from ``/app`` to ``/desk``; on a site that has not moved, ``/desk`` is a 404 and every link
    built on the guess would be dead. A guest request is enough to tell: the desk answers (a page, or a redirect to the
    login page that carries ``redirect-to``), a missing route does not. When the site cannot be reached the current
    spelling is used — a link is still better than none, and the caller decides whether to show it.
    """
    global _DESK_PREFIX, _DESK_PROBE_FAILED_AT
    base = _base_key().rstrip("/")
    if _DESK_PREFIX and _DESK_PREFIX[0] == base:
        return _DESK_PREFIX[1]
    if not base:
        return "desk"
    if _DESK_PROBE_FAILED_AT and (time.time() - _DESK_PROBE_FAILED_AT) < _DESK_BACKOFF:
        return "desk"                          # the site just did not answer: do not make every page wait for it
    for prefix in ("desk", "app"):
        try:
            r = requests.get(base + "/" + prefix, timeout=(5, 15), allow_redirects=False)
            to_login = r.status_code in (301, 302, 303, 307, 308) and "/login" in (r.headers.get("Location") or "")
            if r.status_code < 400 or to_login:
                _DESK_PREFIX = (base, prefix)
                return prefix
        except Exception as e:                     # noqa: BLE001 - unreachable site: fall through to the default
            _set_error(e)
            _DESK_PROBE_FAILED_AT = time.time()
            break
    return "desk"


def _desk_base() -> str:
    """``<site>/<desk>`` — the root the document and list routes hang off. Empty when there is no ERP."""
    base = _base_key().rstrip("/")
    if not base:
        return ""
    return f"{base}/{desk_prefix()}"


def doc_url(doctype: str, name: str) -> str:
    """The ERP's own page for one document, so a person can open it and confirm / submit it there.

    e.g. ``https://<site>/desk/tech-pack/TP-2026-00003``. Nothing is written to make this URL: it is a plain link, and
    the ERP asks for its own login, so no credential ever leaves the tower.
    """
    root = _desk_base()
    slug = doctype_slug(doctype)
    if not root or not slug or not name:
        return ""
    return f"{root}/{slug}/{quote(str(name), safe='')}"


def list_url(doctype: str) -> str:
    """The ERP's list page for a DocType — where to send someone when the document does not exist yet.

    This is what makes "open the ERP" honest before a record is made: the Sales Order the person is about to create
    does not have a page until it exists, but the list of Sales Orders does, and that is where they will find it.
    """
    root = _desk_base()
    slug = doctype_slug(doctype)
    return f"{root}/{slug}" if (root and slug) else ""


def desk_url() -> str:
    """The ERP's front page, for a plain "open the ERP" link (the last resort, not the default)."""
    return _desk_base()


def url_for(doctype: str = "", name: str = "") -> str:
    """The one entry point: the document's page when it has one, else the DocType's list page.

    Callers should never build an ERP address themselves — they name the record they mean and this decides the shape.
    """
    if doctype and name:
        return doc_url(doctype, name)
    return list_url(doctype) if doctype else desk_url()


def erp_count(doctype: str, filters=None) -> int:
    """Count documents of ``doctype``. Returns ``0`` on any failure. Never raises."""
    try:
        params: dict = {"doctype": str(doctype)}
        if filters is not None:
            params["filters"] = json.dumps(filters)
        key = ("count", _base_key(), str(doctype), json.dumps(filters))
        cached, val = _cache_get(key)
        if cached:
            return val
        ok, payload = _request("/api/method/frappe.client.get_count", params)
        if not ok:
            return 0
        try:
            n = int((payload or {}).get("message") or 0)
        except Exception:
            n = 0
        _cache_put(key, n)
        return n
    except Exception as e:
        _set_error(e)
        return 0


def erp_status() -> dict:
    """``{"connected": bool, "base": str, "error": str|None}`` — cached briefly.
    Never raises."""
    global _status_cache
    try:
        now = time.time()
        if _status_cache and (now - _status_cache[0]) < STATUS_TTL:
            return _status_cache[1]

        creds = get_creds()
        base = (creds or {}).get("BASE") or ""
        connected = False
        error: Optional[str] = None

        if base:
            ok, _payload = _request("/api/method/frappe.ping")
            connected = bool(ok)
            if not connected:
                error = _last_error or "erp_unreachable"
        else:
            error = _last_error or "no_erp_credentials"

        status = {"connected": connected, "base": base,
                  "error": None if connected else (error or "erp_unavailable")}
        _status_cache = (now, status)
        return status
    except Exception as e:
        _set_error(e)
        return {"connected": False, "base": "", "error": "erp_unavailable"}


def last_error() -> Optional[str]:
    """The most recent swallowed error (for diagnostics in ``connection.error``)."""
    return _last_error


def erp_logged_user() -> Optional[str]:
    """The ERP user the API key belongs to (used to fill link fields such as
    ``inspected_by``). Returns ``None`` on failure. Never raises."""
    try:
        ok, payload = _request("/api/method/frappe.auth.get_logged_user")
        if ok:
            return (payload or {}).get("message")
    except Exception as e:
        _set_error(e)
    return None


def erp_available() -> bool:
    """True when the ERP answers. Never raises."""
    try:
        return bool(erp_status().get("connected"))
    except Exception:
        return False


if __name__ == "__main__":
    print(json.dumps({
        "status": erp_status(),
        "available": erp_available(),
        "sales_orders": erp_count("Sales Order"),
        "sample": erp_get("Sales Order", fields=["name", "status"], limit=2),
    }, indent=2, default=str))
