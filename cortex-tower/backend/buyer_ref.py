"""The buyer's own order number — read from records, never from a company name in code.

Why this module exists (2026-11-03)
----------------------------------
The intake reader and the Client PO model treated one company's numbering as *the* numbering:
`em_no`, `customer_em_no`, `custom_client_po_em_no` — "EM" is **EMJ Apparel Group's** series.
Every other buyer numbers their own way, and two buyers may legitimately use the same digits.

So the type of a number is a record (`Buyer Order Ref Type`), what each buyer prints is a record
(`Customer.order_ref_formats`), and the number itself is a row (`Buyer Order Ref`) stamped onto the
document that received it. This module is the single reader of those three records:

    formats(erp, customer)     the numbers THIS buyer prints, with their printed labels and patterns
    classify(erp, customer, …) turn the strings found on a paper into typed rows + the identity
    key(erp, customer, value)  the comparable form, so "PO 69785" == "69785" and nothing else does
    same_order(…)              is this PO number the same order for this buyer?

Nothing here knows the string "EM": it is the `ref_code` of one seeded row.
"""
from __future__ import annotations

import re
import time
from typing import Any, Optional

import erp as _erp

_TTL = 300
_cache: dict = {}

_TYPE = "Buyer Order Ref Type"
_FMT = "Customer Order Ref Format"


def _now() -> float:
    return time.time()


def _cached(key, loader):
    hit = _cache.get(key)
    if hit and (_now() - hit[0]) < _TTL:
        return hit[1]
    val = loader()
    _cache[key] = (_now(), val)
    return val


def invalidate() -> None:
    _cache.clear()


# ─────────────────────────────────────────────────────────────────────────────
# the records
# ─────────────────────────────────────────────────────────────────────────────
def ref_types(erp=None) -> dict:
    """ref_type name → its record. Empty dict when the master is absent (older site)."""
    erp = erp or _erp

    def load():
        rows = erp.erp_get(_TYPE, fields=["name", "ref_code", "ref_label", "role", "normalise",
                                          "strip_prefix", "format_regex", "is_active"], limit=0) or []
        return {r["name"]: r for r in rows if r.get("name")}

    return _cached("types", load)


def formats(erp, customer: Optional[str]) -> list:
    """The numbers this customer prints, in the order their paper prints them.

    A customer with no configuration returns [] — and the caller must then accept what the paper
    carries without inventing a label or a pattern (RULES/03, classification rule 6)."""
    if not customer:
        return []
    erp = erp or _erp

    def load():
        doc = erp.erp_doc("Customer", customer) or {}
        rows = [r for r in (doc.get("order_ref_formats") or []) if isinstance(r, dict)]
        return sorted(rows, key=lambda r: (r.get("sequence") or 0))

    return _cached(("fmt", customer), load)


def type_for_role(erp, role: str) -> Optional[dict]:
    for t in (ref_types(erp) or {}).values():
        if (t.get("role") or "") == role and t.get("is_active") in (1, True, None):
            return t
    return None


def identity_type(erp, customer: Optional[str]) -> Optional[dict]:
    """The type that NAMES the order for this buyer.

    Their own record first (`is_identity`), then — for a buyer we have no configuration for — the
    commercial PO, because that is the one number every buyer prints. NOT the default "Order
    identity" type: that role describes a number that names an order *for the buyer who uses it*
    (EM is EMJ's), so applying it to an unconfigured buyer would hand them someone else's
    convention (2026-11-03)."""
    for f in formats(erp, customer):
        if f.get("is_identity"):
            t = (ref_types(erp) or {}).get(f.get("ref_type"))
            if t:
                return t
    return type_for_role(erp, "Commercial PO")


def enforces(erp, customer: Optional[str]) -> bool:
    """True when the buyer has a configuration, i.e. intake may refuse a missing required number."""
    return bool(formats(erp, customer))


# ─────────────────────────────────────────────────────────────────────────────
# the comparable form
# ─────────────────────────────────────────────────────────────────────────────
def normalise(value: Any, kind: Optional[str], prefix: Optional[str] = "") -> str:
    v = str(value or "").strip().upper()
    if kind == "As printed":
        return re.sub(r"\s+", " ", v)
    if kind == "Digits only":
        return re.sub(r"\D", "", v)
    if kind == "Strip prefix + alnum":
        # alnum FIRST, then the prefix: "P.O. #69785" and "PO-69785" are the same number
        core = re.sub(r"[^A-Z0-9]", "", v)
        p = re.sub(r"[^A-Z0-9]", "", str(prefix or "").upper())
        if p and core.startswith(p):
            core = core[len(p):]
        return core
    return re.sub(r"[^A-Z0-9]", "", v)


def key(erp, customer: Optional[str], value: Any, role: str = "Commercial PO") -> str:
    """The number's comparable form, using the buyer's own rule where one is configured."""
    for f in formats(erp, customer):
        t = (ref_types(erp) or {}).get(f.get("ref_type"))
        if t and (t.get("role") or "") == role:
            return normalise(value, t.get("normalise"), t.get("strip_prefix"))
    t = type_for_role(erp, role)
    if t:
        return normalise(value, t.get("normalise"), t.get("strip_prefix"))
    return normalise(value, "Strip prefix + alnum", "PO")


def same_order(erp, customer, value, other_customer, other_value) -> bool:
    """Two PO strings describe the same order when the buyer is the same and the keys match.

    The buyer is part of the key on purpose: "69785" is EMJ's order and may be another company's
    PO next month. Number-alone matching is what produced two Client POs for one physical order.
    """
    if not (customer and other_customer) or str(customer) != str(other_customer):
        return False
    a, b = key(erp, customer, value), key(erp, other_customer, other_value)
    return bool(a) and a == b


# ─────────────────────────────────────────────────────────────────────────────
# reading a paper
# ─────────────────────────────────────────────────────────────────────────────
def _matches(pattern: Optional[str], value: str) -> bool:
    if not pattern:
        return True
    try:
        return bool(re.search(pattern, value))
    except re.error:
        return True


def classify(erp, customer: Optional[str], candidates: list) -> dict:
    """Turn the strings read off a paper into typed reference rows.

    ``candidates`` is every number the readers found, most trustworthy first
    (``po.number`` then ``po.reference`` then anything else). Each configured format takes the
    first candidate that fits its pattern; a candidate already claimed is not reused, so EMJ's
    EM92430 and PO 70795 land in two different rows.
    """
    out: dict = {"refs": [], "order_ref": None, "order_ref_label": None,
                 "order_ref_type": None, "warnings": []}
    values = [str(c).strip() for c in (candidates or []) if c and str(c).strip()]
    seen = set()
    fmts = formats(erp, customer)
    types = ref_types(erp) or {}

    if not fmts:
        # No configuration: keep what the paper gave us, typed as the commercial PO. Never guess
        # a second number's meaning, and never refuse a buyer we have no format for.
        for v in values:
            if v in seen:
                continue
            seen.add(v)
            out["refs"].append({"ref_type": (type_for_role(erp, "Commercial PO") or {}).get("name"),
                                "ref_value": v, "ref_label": "PO No.",
                                "is_identity": 0 if out["refs"] else 1,
                                "normalised": key(erp, customer, v)})
            break                                  # only the PO number, without a configuration
        if out["refs"]:
            out["refs"][0]["is_identity"] = 1
            out["order_ref"] = out["refs"][0]["ref_value"]
            out["order_ref_label"] = out["refs"][0]["ref_label"]
            out["order_ref_type"] = out["refs"][0]["ref_type"]
        return out

    for f in fmts:
        t = types.get(f.get("ref_type")) or {}
        label = f.get("label_as_printed") or t.get("ref_label") or f.get("ref_type")
        pattern = f.get("format_regex") or t.get("format_regex")
        picked = None
        for v in values:
            if v in seen:
                continue
            if _matches(pattern, v):
                picked = v
                break
        if picked:
            seen.add(picked)
            out["refs"].append({
                "ref_type": f.get("ref_type"),
                "ref_value": picked,
                "ref_label": label,
                "is_identity": 1 if f.get("is_identity") else 0,
                "normalised": normalise(picked, t.get("normalise"), t.get("strip_prefix")),
            })
        elif f.get("is_required"):
            out["warnings"].append(
                f"this buyer's order always prints {label} — it was not found on the paper")

    identity = next((r for r in out["refs"] if r.get("is_identity")), None)
    if not identity:
        ident_type = identity_type(erp, customer)
        if ident_type:
            identity = next((r for r in out["refs"] if r.get("ref_type") == ident_type.get("name")), None)
    if not identity and out["refs"]:
        identity = out["refs"][0]
    if identity:
        identity["is_identity"] = 1
        out["order_ref"] = identity["ref_value"]
        out["order_ref_label"] = identity["ref_label"]
        out["order_ref_type"] = identity["ref_type"]
    return out


def rows_for_payload(refs: list) -> list:
    """The child rows as the ERP expects them."""
    return [{"doctype": "Buyer Order Ref", "ref_type": r.get("ref_type"),
             "ref_value": r.get("ref_value"), "ref_label": r.get("ref_label"),
             "normalised": r.get("normalised"), "is_identity": r.get("is_identity") or 0,
             "source": r.get("source") or "agent intake"}
            for r in (refs or []) if r.get("ref_value") and r.get("ref_type")]
