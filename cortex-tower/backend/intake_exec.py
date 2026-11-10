"""Intake executor — turn an approved understanding into ERP drafts.

This is the ONLY module that writes to the ERP from the intake path, and every
write it makes is a **draft**. It is called from ``functions.approve_intake``
after a human approved the run; nothing here is reachable from a read function.

Rules (inherited from ``writes.py`` and the intake plan)
-------------------------------------------------------
* **Drafts only.** No ``submit``, no ``cancel``, no amendment of a posted
  document. ``Client Purchase Order`` and ``Project`` are not submittable anyway.
* **Idempotent.** ``source_key`` is unique per (mail, attachment); an approved run
  can never produce a second order. Re-approving returns the first result.
* **Every record is recorded** in ``created_refs`` so the approval can be rolled
  back in reverse order (draft deletes are allowed; posted ones are not).
* **A blocked step does not abort the run.** It is reported, the rest that can be
  created is created, and the operator sees exactly what still needs an answer.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from typing import Optional

import buyer_ref
import config
import erp
import intake
import write_gate as _gate


def _today() -> str:
    return date.today().isoformat()


# ── the write path (2026-11-07) ──────────────────────────────────────────────
# ``approve_intake`` installs a writer that sends every create through ``pipeline.execute`` (role
# check, field guard, the ERP's business rules run in the tower, audit, journal). With no writer
# installed (unit tests, the older ``writes`` actions) the direct REST create is used, as before.
_writer = None


def set_writer(fn) -> None:
    global _writer
    _writer = fn


def _erp_create(doctype: str, payload: dict):
    if _writer is not None:
        return _writer(doctype, payload)
    return erp.erp_create(doctype, payload)


# ── what this ERP actually has (2026-11-07) ──────────────────────────────────
# The plan was written for the older CORTEX doctype set (Client Purchase Order, Buyer Tech Pack,
# Order Size Colour). The Arinox ERP does not carry them, so a "ready" step failed only at approval.
_INSTALLED: dict = {"t": 0.0, "v": None}


def installed_doctypes() -> Optional[set]:
    """Names of every DocType on the site, cached 10 min. ``None`` = could not ask (do not adapt)."""
    import time as _t
    if _INSTALLED["v"] is not None and _t.time() - _INSTALLED["t"] < 600:
        return _INSTALLED["v"]
    try:
        rows = erp.erp_get("DocType", fields=["name"], limit=0) or []
        names = {r.get("name") for r in rows if r.get("name")}
        if not names:
            return None
        _INSTALLED.update(t=_t.time(), v=names)
        return names
    except Exception:
        return None


def _tech_pack_step(key: str, filename: str, facts: dict, matches: dict) -> dict:
    style = facts.get("style") or {}
    payload = {"doctype": "Tech Pack", "customer": matches.get("customer") or "",
               "style_no": style.get("code") or "", "style_name": (style.get("description") or "")[:140],
               "season": facts.get("season") or "", "received_on": _today(), "status": "Draft",
               "source": "Email", "source_reference": (filename or "")[:140], "extracted_by_ai": 1,
               "fabric_content": (style.get("fabric") or "")[:140]}
    if (matches.get("chain") or {}).get("opportunity"):
        payload["opportunity"] = matches["chain"]["opportunity"]
    return _step(key, f"Tech Pack draft for {style.get('code') or 'the style'}"
                      + (f" (from {filename})" if filename else ""), "Tech Pack",
                 {k: v for k, v in payload.items() if v not in ("", None)},
                 reason="the pack stays attached to the mail; the Tech Pack record is started so costing can begin")


def adapt_to_site(steps: list[dict], facts: dict, matches: dict) -> list[dict]:
    """Rewrite steps that target a doctype this ERP does not have. Never invents a doctype."""
    inst = installed_doctypes()
    if not inst:
        return steps
    try:
        import pack_ingest
        has_builder = bool(pack_ingest.builder_dir())
    except Exception:
        has_builder = False
    out = []
    for st in steps:
        dt = st.get("doctype") or ""
        if st.get("kind") == "ingest_pack" and ("Buyer Tech Pack" not in inst or not has_builder):
            if "Tech Pack" in inst and st.get("status") != "blocked":
                out.append(_tech_pack_step(st["key"], (st.get("payload") or {}).get("filename") or "", facts, matches))
            else:
                out.append({**st, "status": "blocked", "kind": "create",
                            "reason": "reading a pack into BOMs needs the pack builder, which is not part of this deployment"})
            continue
        if dt == "Client Purchase Order" and dt not in inst:
            out.append({**st, "status": "skipped", "kind": "skip", "payload": {},
                        "reason": ("this ERP has no Client Purchase Order record — the buyer's PO number and date "
                                   "travel on the Sales Order (Customer's PO / PO date) instead")})
            continue
        if dt and dt not in inst and st.get("status") != "blocked" and st.get("kind") not in ("reuse",):
            out.append({**st, "status": "blocked", "reason": f"{dt} does not exist on this ERP"})
            continue
        # child rows / custom fields the site does not carry are dropped, never sent
        pl = st.get("payload") or {}
        if dt == "Sales Order" and pl:
            pl = dict(pl)
            if "Order Size Colour" not in inst:
                pl.pop("custom_size_colour", None)
            for k in [k for k in pl if k.startswith("custom_")]:
                if not _has_field("Sales Order", k):
                    pl.pop(k, None)
            st = {**st, "payload": pl}
        out.append(st)
    return out


_FIELD_CACHE: dict = {}


def _has_field(doctype: str, field: str) -> bool:
    """Does this doctype really carry the field? Never send a field that is not there."""
    key = doctype
    if key not in _FIELD_CACHE:
        try:
            meta = erp.erp_get("Custom Field", fields=["fieldname"],
                               filters=[["dt", "=", doctype]], limit=0) or []
            _FIELD_CACHE[key] = {r.get("fieldname") for r in meta}
        except Exception:
            _FIELD_CACHE[key] = set()
    return field in (_FIELD_CACHE.get(key) or set())


def _pick(values, preferred, default=""):
    vals = [v for v in (values or []) if v]
    for p in preferred:
        for v in vals:
            if p.lower() in str(v).lower():
                return v
    return vals[0] if vals else default


def _num(v, default=0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


# ────────────────────────────────────────────────────────────────────────────
# What the ERP will REFUSE — read from the site, not hardcoded per order
# ────────────────────────────────────────────────────────────────────────────
# A required field is not a fact about one order: it is a fact about the doctype, and this
# instance makes four more Sales Order fields mandatory through Property Setters than the
# DocType itself declares (delivery_date, incoterm, named_place, payment_terms_template).
# Asking the site at run time is the difference between a Tower that works for a buyer's
# 71242 and one that works for the next order too (2026-11-03).
_REQ_CACHE: dict = {}
_LAYOUT = ("Section Break", "Column Break", "Tab Break", "Heading", "HTML", "Button")
# Fields the FRAMEWORK fills from the record it is about — never a fact about the order.
# `naming_series` is assigned by Frappe from the doctype's own series even though the field
# is marked required, so treating it as missing blocked every Project and Sales Order.
_FRAMEWORK_FILLED = {"naming_series", "amended_from", "owner", "modified_by", "docstatus"}


def required_fields(doctype: str) -> dict:
    """{fieldname: label} the site requires and does not fill itself. Cached per process."""
    if doctype in _REQ_CACHE:
        return _REQ_CACHE[doctype]
    wanted: dict = {}
    try:
        meta = erp.erp_doc("DocType", doctype) or {}
    except Exception:
        meta = {}
    for f in meta.get("fields") or []:
        if f.get("fieldtype") in _LAYOUT or not f.get("fieldname"):
            continue
        if f["fieldname"] in _FRAMEWORK_FILLED or not f.get("reqd"):
            continue
        if f.get("default") not in (None, ""):
            continue          # the server fills it (order_type, transaction_date, status…)
        wanted[f["fieldname"]] = f.get("label") or f["fieldname"]
    # A Custom Field is NOT part of the DocType document that `erp_doc("DocType", …)` returns —
    # Frappe merges it into the meta at runtime. Reading only `meta["fields"]` therefore made
    # every REQUIRED custom field invisible to preflight: `custom_quotation` (reqd=1, label
    # "Quotation") looked fine, the step said "ready", and the ERP refused with
    # `Value missing for Sales Order: Quotation` — the same trap `rulebook._meta_fields()`
    # was fixed for on 2026-11-02, in a second place (2026-11-04, D-142).
    try:
        for cf in (erp.erp_get("Custom Field",
                               fields=["fieldname", "label", "reqd", "fieldtype"],
                               filters=[["dt", "=", doctype], ["reqd", "=", 1]], limit=0) or []):
            fn = cf.get("fieldname")
            if fn and fn not in wanted and fn not in _FRAMEWORK_FILLED:
                wanted[fn] = cf.get("label") or fn
    except Exception:
        pass
    try:
        setters = erp.erp_get("Property Setter",
                              fields=["field_name", "property", "value"],
                              filters=[["doc_type", "=", doctype], ["property", "=", "reqd"]],
                              limit=0) or []
    except Exception:
        setters = []
    for ps in setters:
        name = ps.get("field_name") or ""
        if not name:
            continue
        if str(ps.get("value")).strip().lower() in ("1", "true", "yes"):
            wanted[name] = wanted.get(name, name)
        else:
            wanted.pop(name, None)
    _REQ_CACHE[doctype] = wanted
    return wanted


def _customer_terms(matches: dict) -> Optional[str]:
    """The terms the Customer record carries, when the paper's words match no template."""
    name = matches.get("customer")
    if not name:
        return None
    try:
        doc = erp.erp_doc("Customer", name) or {}
    except Exception:
        return None
    return doc.get("payment_terms") or None


def resolve_required(field: str, facts: dict, matches: dict):
    """One value the site insists on, taken from the record — or None if nobody knows it."""
    c = facts.get("commercial") or {}
    buyer = facts.get("buyer") or {}
    if field == "company":
        # a Company must be a real Company on this site — the config default is a *label*,
        # and writing a Stock Entry against a company that does not exist is worse than
        # blocking the step (2026-11-03)
        for cand in (matches.get("company"), config.DEFAULT_COMPANY):
            if not cand:
                continue
            try:
                if erp.erp_get("Company", fields=["name"], filters=[["name", "=", cand]], limit=1):
                    return cand
            except Exception:
                continue
        return None
    if field == "currency":
        return c.get("currency") or config.DEFAULT_CURRENCY
    if field == "custom_quotation":
        # A Quotation for THIS buyer that names one of these styles, newest first. Nothing is
        # invented: if none exists the step blocks and says so (the site requires the link).
        customer = matches.get("customer") or buyer.get("name")
        if not customer:
            return None
        styles = [ln.get("style") for ln in (facts.get("lines") or []) if ln.get("style")]
        try:
            rows = erp.erp_get("Quotation", fields=["name", "transaction_date"],
                               filters=[["party_name", "=", customer], ["docstatus", "!=", 2]],
                               order="transaction_date desc", limit=20) or []
        except Exception:
            rows = []
        for q in rows:
            try:
                doc = erp.erp_doc("Quotation", q["name"]) or {}
            except Exception:
                continue
            codes = [(i.get("item_code") or "") for i in (doc.get("items") or [])]
            if not styles or any(s and s in c2 for s in styles for c2 in codes):
                return q["name"]
        return None
    if field == "payment_terms_template":
        return _payment_terms(c.get("payment_terms")) or _customer_terms(matches)
    if field == "incoterm":
        return (c.get("incoterm") or "").upper() or None
    if field == "named_place":
        return c.get("named_place") or _city_from(buyer.get("address"))
    if field == "project":
        return matches.get("project_name") or None
    if field in ("delivery_date", "schedule_date", "expected_delivery_date"):
        return facts.get("ship_date") or None
    return None


# fields that a step of THIS approval supplies (the Customer it creates, the Client PO it
# links, the Project it opens). At PLAN time they do not exist yet, so checking the paper for
# them would block every order with a Project — the execute-time check still catches them.
_FILLED_BY_STEPS = {
    "Sales Order": {"customer", "project", "custom_client_po"},
    "Client Purchase Order": {"customer"},
    "Project": {"customer", "company"},
    "Opportunity": {"party_name", "customer_name", "company"},
}


def preflight(doctype: str, payload: dict, facts: dict, matches: dict,
              skip: set = frozenset()) -> tuple:
    """Fill what the site requires, and name what cannot be filled.

    Returns ``(payload, missing)`` where ``missing`` is ``[(field, label, hint)]``. A step
    with a missing field is BLOCKED before the write, never sent to fail: "Value missing for
    Sales Order: Payment Terms Template" is a sentence a merchandiser can do nothing with,
    and it used to arrive after the CPO, the style and the project had already been created
    (2026-11-03).
    """
    out = dict(payload or {})
    out.pop("doctype", None)
    missing = []
    for field, label in required_fields(doctype).items():
        if field in (skip or ()): 
            continue
        if out.get(field) not in (None, "", 0, [], {}):
            continue
        value = resolve_required(field, facts, matches)
        if value not in (None, ""):
            out[field] = value
            continue
        missing.append((field, label, _missing_hint(field, facts, matches)))
    return out, missing


def _missing_hint(field: str, facts: dict, matches: dict) -> str:
    c = facts.get("commercial") or {}
    if field == "payment_terms_template":
        said = c.get("payment_terms") or "nothing"
        try:
            have = [r.get("name") for r in (erp.erp_get("Payment Terms Template",
                                                        fields=["name"], limit=0) or [])]
        except Exception:
            have = []
        return (f"the paper says \"{said}\" and no Payment Terms Template matches it "
                f"(the site has: {', '.join(have) or 'none'}). Add the template, or set it on the "
                f"Customer, then approve again")
    if field == "named_place":
        return "the place of delivery is not on the paper and the address yielded no city"
    if field in ("incoterm",):
        return "the paper does not state the trade term"
    if field == "custom_quotation":
        who = matches.get("customer") or (facts.get("buyer") or {}).get("name") or "this buyer"
        return (f"the site requires a Quotation on a Sales Order and {who} has none on file. "
                f"Issue the quotation first (Phase A), or clear the requirement on Sales Order "
                f"(Custom Field `custom_quotation`, reqd) if import orders may bypass it")
    return f"{field} is required on {field and 'this document'} and nothing on the record supplies it"


# what makes two records THE SAME record — the ERP's own identity, not ours
_IDENTITY = {
    "Client Purchase Order": ("client_po_no", "client_po_no"),
    "Sales Order": ("custom_client_po", "custom_client_po"),
    "Project": ("project_name", "project_name"),
    "Customer": ("customer_name", "customer_name"),
    "Supplier": ("supplier_name", "supplier_name"),
    "Item": ("name", "item_code"),
    "Task": ("subject", "subject"),
}


def find_existing(doctype: str, payload: dict) -> Optional[str]:
    """The record this payload would duplicate, if the site already has it.

    Two doctypes need their own identity: `Item Price`'s name is a hash, and a `Task`'s
    subject is shared by every answer to every buyer. The rest go through the
    (site field, payload key) table.
    """
    if doctype == "Item Price":
        # the SKU in the selling price list is the identity
        try:
            rows = erp.erp_get("Item Price", fields=["name"],
                               filters=[["item_code", "=", payload.get("item_code")],
                                        ["price_list", "=", payload.get("price_list")
                                         or config.SELLING_PRICE_LIST]], limit=1) or []
        except Exception:
            return None
        return rows[0].get("name") if rows else None

    if doctype == "Task":
        # the subject alone would match yesterday's answer to another buyer
        try:
            rows = erp.erp_get("Task", fields=["name"],
                               filters=[["subject", "=", payload.get("subject")],
                                        ["description", "=", payload.get("description")]],
                               limit=1) or []
        except Exception:
            return None
        return rows[0].get("name") if rows else None

    spec = _IDENTITY.get(doctype)
    if not spec:
        return None
    field, key = spec
    value = payload.get(key)
    if value in (None, ""):
        return None

    if doctype == "Client Purchase Order":
        # The identity is (BUYER, their PO number). A PO number is unique per buyer, not on the
        # planet — two companies may number a PO the same way, and blocking that is what made the
        # model work for one company only (2026-11-03).
        buyer = payload.get("customer") or ""
        try:
            for row in erp.erp_get("Client Purchase Order",
                                   fields=["name", "client_po_no", "customer"], limit=0) or []:
                if intake.po_core(row.get("client_po_no") or "") != intake.po_core(str(value)):
                    continue
                if buyer and row.get("customer") and row.get("customer") != buyer:
                    continue          # another company's numbering — not this record
                return row.get("name")
        except Exception:
            return None
        return None

    try:
        rows = erp.erp_get(doctype, fields=["name"], filters=[[field, "=", value]], limit=1) or []
    except Exception:
        return None
    return rows[0].get("name") if rows else None


def create_checked(doctype: str, payload: dict, facts: Optional[dict] = None,
                   matches: Optional[dict] = None) -> tuple:
    """THE one gate every Tower → ERP create passes.

    Returns ``(ok, doc, err, note)``. In order: the site's required fields (filled from the
    record, or refused with the field named), then the duplicate check (link, never twin),
    then the create. Used by the intake, by ``writes`` and by the action paths — so a new
    Property Setter on any doctype cannot turn into a half-written order anywhere.
    """
    facts = facts or {}
    matches = matches or {}
    body = {k: v for k, v in (payload or {}).items() if k != "doctype"}
    filled, missing = preflight(doctype, body, facts, matches)
    if missing:
        return (False, {},
                ("the site requires " + ", ".join(f for f, _l, _h in missing)
                 + " and nothing on the record supplies it ("
                 + " · ".join(h for _f, _l, h in missing) + ")"),
                "")
    existing = find_existing(doctype, filled)
    if existing:
        return (True, {"name": existing, "existing": True}, "",
                f"{doctype} {existing} already exists — linked, not duplicated")
    ok, doc, err = _erp_create(doctype, filled)
    return ok, (doc or {}), err, ""


# ────────────────────────────────────────────────────────────────────────────
# The plan — what approval would create, shown before anything is written
# ────────────────────────────────────────────────────────────────────────────
def build_plan(facts: dict, matches: dict) -> list[dict]:
    """Ordered steps. ``status`` is ``ready`` or ``blocked`` with a reason."""
    steps: list[dict] = []
    c = facts.get("commercial") or {}
    route = intake.route(facts, matches)

    if route == "new_order":
        steps.append(_step_customer(facts, matches))
        steps.append(_step_cpo(facts, matches))
        steps.append(_step_style(facts, matches))
        # the Project comes before the order: `project` is mandatory on a Sales
        # Order on this instance, and the order must carry it from creation
        steps.append(_step_project(facts, matches))
        steps.append(_step_sales_order(facts, matches))
        steps.append(_step_bom(facts, matches))
        steps.append(_step_ack_task(facts, matches))
    elif route == "revision":
        steps.append(_step_cpo(facts, matches))
        steps.append(_step_revision_task(facts, matches))
    elif route == "enquiry":
        # The Customer comes FIRST. Without it the Opportunity is unrunnable and the
        # plan offered no way to make it runnable: on 2026-11-03 the HARBOR & LANE
        # enquiry approved into nothing but a to-do, because the enquiry route had no
        # Customer step while the order route did (RULES: a block must have an exit).
        steps.append(_step_customer(facts, matches))
        steps.append(_step_opportunity(facts, matches))
        # the pack the buyer sent with the enquiry is evidence costing needs — ingest it here
        if facts.get("_pack_documents"):
            steps.extend(_steps_pack_ingest(facts, matches))
        steps.append(_step_cost_task(facts, matches))
    elif route == "chain_reply":
        # A later mail in a live conversation. It is not a new deal: it is an answer,
        # or the tech pack / BOM the deal was waiting for.
        steps.extend(_steps_pack_ingest(facts, matches))
        steps.append(_step_ack_task(facts, matches))
    elif route == "finance":
        steps.append(_step_finance_task(facts, matches))
    else:
        steps.append(_step_generic_task(facts, matches))

    # Steps aimed at doctypes this ERP does not have are rewritten (or skipped) now, so the plan
    # the person approves is the plan that will run.
    try:
        steps = adapt_to_site(steps, facts, matches)
    except Exception:
        pass

    # What the site will REFUSE is known before the click: fill the required fields from the
    # record, and block the step that cannot be filled instead of creating half an order.
    for st in steps:
        if st.get("status") in ("blocked", "skipped") or st.get("kind") in ("reuse", "fill", "ingest_pack",
                                                                            "create_many", "skip"):
            continue
        if not (st.get("payload") and st.get("doctype")):
            continue
        try:
            filled, missing = preflight(st["doctype"], st["payload"], facts, matches,
                                        skip=_FILLED_BY_STEPS.get(st["doctype"], set()))
        except Exception:
            continue
        st["payload"] = {**st["payload"], **filled, "doctype": st["doctype"]}
        # say NOW that this will link a record the site already has, not create a twin
        if not missing and st.get("kind", "create") == "create":
            try:
                already = find_existing(st["doctype"], st["payload"])
            except Exception:
                already = None
            if already:
                st["existing"] = already
                st["reason"] = f"{already} is already on file — it will be linked, not duplicated"
        if missing:
            st["status"] = "blocked"
            st["reason"] = " · ".join(f"{label}: {hint}" for _f, label, hint in missing)

    for i, s in enumerate(steps):
        s["seq"] = i + 1
    return steps


def _step(key: str, label: str, doctype: str, payload: dict, status: str = "ready",
          reason: str = "", kind: str = "create") -> dict:
    return {"key": key, "label": label, "doctype": doctype, "payload": payload,
            "status": status, "reason": reason, "kind": kind}


def _customer_payload(facts: dict, matches: dict) -> dict:
    buyer = facts.get("buyer") or {}
    groups = [g.get("name") for g in (erp.erp_get(
        "Customer Group", fields=["name", "is_group"], limit=0) or []) if g.get("name") and not g.get("is_group")]
    terr = [t.get("name") for t in (erp.erp_get(
        "Territory", fields=["name", "is_group"], limit=0) or []) if t.get("name") and not t.get("is_group")]
    payload = {
        "doctype": "Customer",
        "customer_name": buyer.get("name"),
        "customer_type": "Company",
        "customer_group": _pick(groups, ["Apparel Buyers", "Commercial"], "Commercial"),
        "territory": _pick(terr, ["Rest Of The World"], "Rest Of The World"),
    }
    if buyer.get("email"):
        payload["email_id"] = buyer["email"]
    if buyer.get("country"):
        payload["custom_country_of_origin"] = buyer["country"] if _has_field("Customer", "custom_country_of_origin") else payload.get("custom_country_of_origin", "")
        if not payload.get("custom_country_of_origin"):
            payload.pop("custom_country_of_origin", None)
    return payload


# A name that is a WORD, not a company. Creating a Customer called "estimate" is worse than
# asking: it is a record nobody can find later and it takes a unique name slot (2026-11-03 —
# a deterministic re-read of the HARBOR & LANE enquiry read the buyer as "estimate").
_NAME_STOP = {"estimate", "estimation", "buyer", "customer", "client", "sir", "madam",
              "team", "company", "unknown", "none", "n/a", "na", "dear", "order",
              "quotation", "quote", "inquiry", "enquiry", "to", "from", "hi", "hello"}


def _buyer_name_problem(name: str) -> str:
    """Why this name cannot become a Customer. Empty string = it can."""
    n = (name or "").strip()
    if len(n) < 3:
        return "the buyer name is too short to be a company — correct buyer.name and re-plan"
    if n.lower().strip(" .,") in _NAME_STOP:
        return (f'the buyer was read as "{n}" — that is not a company name. Correct buyer.name '
                "in the card, then re-plan")
    if not any(c.isalpha() for c in n):
        return f'the buyer was read as "{n}" — no letters in it, so it is not a company name'
    if n.islower() and " " not in n:
        return (f'the buyer was read as "{n}" — a company name is not a lower-case word. '
                "Correct buyer.name in the card, then re-plan")
    return ""


def buyer_name_problem(name: str) -> str:
    """Public form of :func:`_buyer_name_problem` — the review sheet asks the same question the
    plan does, so a person typing a new buyer name is told before approval, not after (2026-11-07)."""
    return _buyer_name_problem(name)


def _step_customer(facts: dict, matches: dict) -> dict:
    if matches.get("customer"):
        return _step("customer", f"Customer — reuse {matches['customer']}", "Customer",
                     {"existing": matches["customer"]}, status="ready",
                     reason="already in the ERP", kind="reuse")
    name = (facts.get("buyer") or {}).get("name")
    if not name:
        return _step("customer", "Customer — unknown", "Customer", {}, status="blocked",
                     reason="the buyer name could not be read from the mail")
    problem = _buyer_name_problem(name)
    if problem:
        return _step("customer", f"Customer — cannot create \"{name}\"", "Customer", {},
                     status="blocked", reason=problem)
    # A candidate at 60-85 % is NOT "no customer" — it is "prove it". Creating a second
    # Customer beside an existing one forks the buyer for good (two CPOs for one PO,
    # 2026-11-03). So the run stops and asks, and `set_intake_customer` is the way out.
    cands = matches.get("customer_candidates") or []
    if cands:
        best = cands[0]
        return _step("customer",
                     f"Customer — looks like {best.get('name')} ({best.get('score', 0):.0%})",
                     "Customer", {}, status="blocked",
                     reason=(f"the buyer reads like {best.get('name')} — link it, or create a new "
                             "Customer if it is a different company"))
    return _step("customer", f"Customer — create {name}", "Customer", _customer_payload(facts, matches))


def _cpo_payload(facts: dict, matches: dict) -> dict:
    """The Client PO as the paper states it (header + lines)."""
    c = facts.get("commercial") or {}
    po = facts.get("po") or {}
    style = facts.get("style") or {}
    buyer = facts.get("buyer") or {}
    vendor = facts.get("to") or {}
    lines = []
    for i, line in enumerate(facts.get("lines") or [], start=1):
        lines.append({
            "doctype": "Client Purchase Order Line",
            "line_no": i,
            "style_no": style.get("code") or "",
            # the buyer's item, and OUR item. `item_code` is the ERP link (the SKU);
            # `_resolve_item_code` returns None for a style not yet in the master, so
            # a new style never writes a dangling link before its SKUs exist.
            "item_code": _resolve_item_code(style.get("code"), line.get("size"), matches) or "",
            "item_name": style.get("description") or "",
            "description": style.get("description") or "",
            "fabric": style.get("fabric") or "",
            "buyer_colour": line.get("colour") or "",
            "shade": line.get("shade") or "",
            "size": line.get("size") or "",
            "qty": _num(line.get("qty")),
            "rate": _num(line.get("rate") or c.get("rate")),
            "amount": _num(line.get("qty")) * _num(line.get("rate") or c.get("rate")),
            "cartons": line.get("cartons") or 0,
            "pack_size": (facts.get("quality") or {}).get("carton_ratio") or 0,
            "ship_date": facts.get("ship_date") or None,
            "source_page": 1,
        })
    # The buyer's own numbers, typed (2026-11-03). `matches["refs"]` was classified against the
    # customer's own format records, so nothing here decides that a second number is an "EM" —
    # the legacy `em_no` column is not written for new records at all, and the sheets read
    # `order_ref` (see build/print_build/build_cpo_print.py).
    refs = matches.get("refs") or []
    po_value = po.get("number")
    order_ref = matches.get("order_ref") or po_value
    ident = next((r for r in refs if r.get("ref_value") == order_ref), None) or {}
    payload = {
        "doctype": "Client Purchase Order",
        "client_po_no": po_value,
        "refs": buyer_ref.rows_for_payload(refs) if refs else [],
        "order_ref": order_ref,
        "order_ref_type": matches.get("order_ref_type") or ident.get("ref_type") or None,
        "order_ref_label": matches.get("order_ref_label") or ident.get("ref_label") or None,
        "order_ref_normalised": ident.get("normalised") or None,
        "po_date": po.get("date") or _today(),
        "customer": matches.get("customer") or "",          # filled after the Customer step
        # parties: From = the buyer (the `customer` link above), To = our own company
        "from_name": (buyer.get("name") or "")[:140],
        "from_address": (buyer.get("address") or "")[:2000],
        "from_phone": (buyer.get("phone") or "")[:60],
        "from_email": (buyer.get("email") or "")[:140],
        "company": matches.get("company") or "",
        "to_name": (vendor.get("name") or "")[:140],
        "to_address": (vendor.get("address") or "")[:2000],
        "to_phone": (vendor.get("phone") or "")[:60],
        "to_email": (vendor.get("email") or "")[:140],
        "is_revision": 1 if facts.get("document_type") == "po_revision" else 0,
        "status": "Received",
        "currency": c.get("currency") or "",
        "named_place": c.get("named_place") or "",
        "payment_terms_text": c.get("payment_terms") or "",
        "ship_date": facts.get("ship_date") or None,
        "season": facts.get("season") or "",
        "buyer_reference": (po.get("reference") or "")[:140],
        "total_qty": _num(c.get("total_qty")),
        "total_value": _num(c.get("total_value")),
        "buyer_po_no_text": po.get("number") or "",
        "intake_status": "Received",
        "parse_confidence": round(_avg_conf(facts), 2),
        "source_message_id": (facts.get("_message_id") or "")[:140],
        "source_attachment": (facts.get("_attachment") or "")[:140],
        "notes": _notes(facts),
        "lines": lines,
        "supersedes": (matches.get("po_existing") or None) if facts.get("document_type") == "po_revision" else None,
        # the pre-existing flat evidence fields stay filled, so the reports that
        # already read them (order gate, desk cards) keep working
        "qty": _num(c.get("total_qty")),
        "style_no": style.get("code") or "",
        "colour": (lines[0]["buyer_colour"] if len(lines) == 1 else
                   ("MULTI" if len(lines) > 1 else "")),
        "amount_usd": _num(c.get("total_value")) if (c.get("currency") or "").upper() == "USD" else 0,
    }
    incoterm = (c.get("incoterm") or "").upper()
    if incoterm:
        try:
            valid = {i.get("name") for i in (erp.erp_get("Incoterm", fields=["name"], limit=0) or [])}
        except Exception:
            valid = set()
        if incoterm in valid:               # `incoterm` is a Link on this doctype, not a Select
            payload["incoterm"] = incoterm
    return payload


def _step_cpo(facts: dict, matches: dict) -> dict:
    po = facts.get("po") or {}
    payload = _cpo_payload(facts, matches)
    lines = payload.get("lines") or []

    # The same buyer document must never become two Client POs. When the number is
    # already on file the correct act is to LINK it — and to FILL what the migration
    # left blank (thirteen of fifteen CPOs are header-only, so the PO and the order
    # used to describe different things). Only empty fields are filled; nothing a
    # human typed is ever overwritten.
    if matches.get("po_existing") and facts.get("document_type") != "po_revision":
        existing = matches["po_existing"]
        header = {k: v for k, v in payload.items()
                  if k not in ("doctype", "lines", "customer", "client_po_no", "supersedes")}
        others = [d for d in (matches.get("po_other_buyer") or [])
                  if d.get("cpo") != existing or (matches.get("customer") and d.get("customer") != matches.get("customer"))]
        if others:
            names = ", ".join(f'{d["customer"]} ({d["cpo"]})' for d in others)
            return _step("cpo", f"Client PO {po.get('number')} — the number is already on file for {names}",
                         "Client Purchase Order",
                         {"existing": existing, "fill": header, "lines": lines},
                         status="blocked", kind="fill",
                         reason="this PO number is recorded for a different buyer — confirm it is the same order before linking, or record the buyer's own PO number")
        return _step("cpo", f"Client PO {po.get('number')} — already on file ({existing}); fill what is blank",
                     "Client Purchase Order",
                     {"existing": existing, "fill": header, "lines": lines}, kind="fill",
                     reason="the same PO number is already recorded — only empty fields and an empty line table are filled")

    if not po.get("number"):
        return _step("cpo", "Client Purchase Order — no PO number", "Client Purchase Order", {},
                     status="blocked", reason="a PO without its number cannot be recorded")
    blocked = "" if (facts.get("commercial") or {}).get("currency") else \
        "currency not read — set it before the order can be priced"
    return _step("cpo", f"Client Purchase Order {po.get('number')} (+{len(lines)} line(s))",
                 "Client Purchase Order", payload,
                 status="blocked" if blocked else "ready", reason=blocked)


def _grid_sizes(facts: dict) -> dict:
    """{SIZE: qty} from the first line that carries a readable grid."""
    for line in facts.get("lines") or []:
        g = line.get("size_grid")
        if isinstance(g, dict) and g:
            return {str(k).upper(): v for k, v in g.items()}
    return {}


def _step_style(facts: dict, matches: dict) -> dict:
    """Create the style in the item master when it does not exist yet.

    A Sales Order line must name a purchasable SKU. When the PO is for a style we
    have never sold, the process starts with the style — one item per size the
    buyer's grid asks for — exactly as the merchandiser would create it.
    """
    style = (facts.get("style") or {}).get("code")
    sizes = _grid_sizes(facts)
    if not style:
        return _step("style", "Style — no style code read", "Item", {}, status="blocked",
                     reason="the paper does not carry a style code")
    if matches.get("style_item") or matches.get("style_variants"):
        return _step("style", f"Style {style} — already in the item master", "Item",
                     {"existing": matches.get("style_item") or ",".join(matches.get("style_variants") or [])},
                     kind="reuse", reason="SKUs exist")
    if not sizes:
        return _step("style", f"Style {style} — cannot be created yet", "Item", {}, status="blocked",
                     reason="a new style needs its size grid before any SKU can exist (none read from the paper)")
    desc = (facts.get("style") or {}).get("description") or style
    payloads = [{"doctype": "Item", "item_code": style, "item_name": desc,
                 "item_group": matches.get("item_group") or "Products",
                 "stock_uom": matches.get("stock_uom") or "Nos",
                 "is_stock_item": 1, "has_variants": 0,
                 "description": desc}]
    for size in sizes:
        code = f"{style}-{size}"
        payloads.append({"doctype": "Item", "item_code": code,
                         "item_name": f"{desc} {size}", "item_group": matches.get("item_group") or "Products",
                         "stock_uom": matches.get("stock_uom") or "Nos", "is_stock_item": 1,
                         "variant_of": None, "description": f"{desc} · size {size}"})
    rate = _num((facts.get("commercial") or {}).get("rate"))
    currency = (facts.get("commercial") or {}).get("currency") or ""
    if rate and currency:
        for size in sizes:
            payloads.append({"doctype": "Item Price", "item_code": f"{style}-{size}",
                             "price_list": config.SELLING_PRICE_LIST, "price_list_rate": rate,
                             "currency": currency})
    step = _step("style", f"Style {style} — create the style, {len(sizes)} size SKU(s) and their price",
                 "Item", {"payloads": payloads}, reason="the style is not in the item master")
    step["kind"] = "create_many"
    return step


def _step_sales_order(facts: dict, matches: dict) -> dict:
    c = facts.get("commercial") or {}
    po = facts.get("po") or {}
    style = facts.get("style") or {}
    has_customer = bool(matches.get("customer") or (facts.get("buyer") or {}).get("name"))
    if not has_customer:
        return _step("sales_order", "Sales Order (draft) — no buyer", "Sales Order", {},
                     status="blocked", reason="the buyer could not be read from the mail")

    items, missing_items = [], []
    sizes = _grid_sizes(facts)
    for line in facts.get("lines") or []:
        rate = _num(line.get("rate") or c.get("rate"))
        grid = line.get("size_grid") if isinstance(line.get("size_grid"), dict) else None
        if grid:
            # a real size grid: one order line per size, named the way the SKU is
            for size, qty in grid.items():
                q = _num(qty)
                if not q:
                    continue
                code = f"{(style.get('code') or '').upper()}-{str(size).upper()}"
                row = {"item_code": code, "qty": q, "rate": rate, "price_list_rate": rate}
                if facts.get("ship_date"):
                    row["delivery_date"] = facts["ship_date"]
                if line.get("colour"):
                    row["description"] = f"{line['colour']} / {str(size).upper()}"
                items.append(row)
            continue
        code = _resolve_item_code(style.get("code"), line.get("size"), matches)
        if not code:
            missing_items.append(line.get("size") or line.get("colour") or "line")
            continue
        row = {"item_code": code, "qty": _num(line.get("qty")) or 1, "rate": rate,
               "price_list_rate": rate}
        if facts.get("ship_date"):
            row["delivery_date"] = facts["ship_date"]
        if line.get("colour"):
            row["description"] = f"{line.get('colour')}{' / ' + line['size'] if line.get('size') else ''}"
        items.append(row)

    if not items:
        reason = ("no size grid on the PO, so no SKU can be named — the order header is captured, "
                  "the Sales Order waits for sizes" if not _has_sizes(facts)
                  else "the style has no purchasable SKU yet — create the item variants first")
        return _step("sales_order", "Sales Order (draft) — blocked", "Sales Order", {},
                     status="blocked", reason=reason)

    if facts.get("ship_date") and facts["ship_date"] < _today() and not po.get("date"):
        return _step("sales_order", "Sales Order (draft) — cannot be dated", "Sales Order", {},
                     status="blocked",
                     reason=(f"the PO ships {facts['ship_date']}, which is in the past, and the PO's own "
                             f"date was not read — set it (edit the PO date) so the order can be dated "
                             f"correctly instead of today"))

    currency = c.get("currency") or config.DEFAULT_CURRENCY
    company = matches.get("company") or ""
    company_currency = (matches.get("company_currency") or config.DEFAULT_CURRENCY or "USD").upper()
    fx = matches.get("currency_rate") or (1.0 if currency.upper() == company_currency else None)
    if fx is None:
        return _step("sales_order", "Sales Order (draft) — no exchange rate", "Sales Order", {},
                     status="blocked",
                     reason=(f"no {currency}→{company_currency} exchange rate on file — the order cannot be "
                             f"valued. Add the rate in Currency Exchange, then approve again."))
    payload = {
        "doctype": "Sales Order",
        "customer": matches.get("customer"),
        "company": company,
        "currency": currency,
        "conversion_rate": fx,
        "selling_price_list": config.SELLING_PRICE_LIST,
        "price_list_currency": currency,
        "plc_conversion_rate": fx,
        # A real PO can arrive with a ship date already behind us (a late-recorded
        # order, a migration). Dating the order "today" makes ERPNext reject it, so
        # the order carries the PO's own date — which is also the truth.
        "transaction_date": (po.get("date") if (po.get("date") and facts.get("ship_date")
                                                and po.get("date") < facts["ship_date"]) else _today()),
        "delivery_date": facts.get("ship_date") or _today(),
        "po_no": po.get("number") or "",
        "po_date": po.get("date") or None,
        "items": items,
        "ignore_pricing_rule": 1,
        # the contract's trade terms are mandatory on this instance
        "incoterm": (c.get("incoterm") or "").upper() or None,
        "named_place": (c.get("named_place") or _city_from((facts.get("buyer") or {}).get("address"))
                        or None),
        "payment_terms_template": _payment_terms(c.get("payment_terms")),
        "custom_intake_note": f"created by intake from mail — {len(items)} line(s) read from the buyer's PO",
    }
    if matches.get("client_po"):
        payload["custom_client_po"] = matches["client_po"]

    # the ERP's own contract gate: `custom_quotation` and `custom_size_colour` are
    # mandatory on this instance. Fill what the paper gives us; block on the rest.
    grid_rows = []
    for line in facts.get("lines") or []:
        g = line.get("size_grid")
        if isinstance(g, dict):
            for size, qty in g.items():
                grid_rows.append({"doctype": "Order Size Colour", "size": str(size).upper(),
                                  "colour": line.get("colour") or "",
                                  "qty": _num(qty),
                                  "item_code": f"{(style.get('code') or '').upper()}-{str(size).upper()}",
                                  "delivery_date": facts.get("ship_date") or None})
    if grid_rows:
        payload["custom_size_colour"] = grid_rows
    try:
        from models import IntakeRunModel as _IR  # noqa: F401  (kept for symmetry)
    except Exception:
        pass
    quotation = None
    try:
        qs = erp.erp_get("Quotation", fields=["name", "party_name", "docstatus"], limit=0) or []
        quotation = next((q["name"] for q in qs
                          if (q.get("party_name") or "") == (matches.get("customer") or "")
                          and int(q.get("docstatus") or 0) == 0), None)
    except Exception:
        quotation = None
    if quotation:
        payload["custom_quotation"] = quotation
    # ERPNext refuses a stock line with no source warehouse; take the company's
    # finished-goods store (never invent one)
    wh = matches.get("warehouse")
    if not wh:
        try:
            stores = erp.erp_get("Warehouse", fields=["name", "company", "is_group"],
                                 filters=[["company", "=", company], ["is_group", "=", 0]], limit=0) or []
            wh = next((w["name"] for w in stores if "finished" in (w.get("name") or "").lower()), None) \
                 or (stores[0]["name"] if stores else None)
        except Exception:
            wh = None
    if wh:
        payload["set_warehouse"] = wh
    note = ""
    if missing_items:
        note = f"{len(missing_items)} line(s) could not be named: {', '.join(map(str, missing_items))[:120]}"
    step = _step("sales_order", f"Sales Order (draft) — {len(items)} line(s)", "Sales Order", payload,
                 reason=note)
    step["depends_on"] = "customer"
    return step


def _city_from(address: Optional[str]) -> Optional[str]:
    """The destination city printed on the paper ("…, Los Angeles CA 90015" → Los Angeles)."""
    if not address:
        return None
    parts = [p.strip() for p in str(address).split(",") if p.strip()]
    if not parts:
        return None
    tail = parts[-1]
    m = re.match(r"([A-Za-z .'-]+?)(?:\s+[A-Z]{2})?\s+\d", tail)
    if m:
        return m.group(1).strip(" .")
    return tail if len(tail) < 40 else None


_TERM_BASIS = ("rog", "bl", "receipt", "shipment", "invoice", "delivery", "lc", "cad", "telex")


def _terms_key(text: str) -> tuple:
    """"15 Days from ROG" and "15 Days ROG" are the same term; "5 days from RECEIPT" is not.

    A template name and a buyer's sentence rarely match character for character, so the
    identity is (the number of days, the event the clock starts on) — both read from the
    text, neither invented.
    """
    t = intake._slug(str(text or ""))
    days = re.search(r"\d+", t)
    basis = next((b for b in _TERM_BASIS if b in t.split("-") or f"-{b}" in t), "")
    if not basis:
        basis = next((b for b in _TERM_BASIS if b in t), "")
    return (days.group(0) if days else "", basis)


def _payment_terms(text: Optional[str]) -> Optional[str]:
    """'15 days from ROG' → the Payment Terms Template that exists, if any.

    Never invents one: a template states when money is due, and that is a commitment, not a
    formatting decision. No match = the step blocks with the words the buyer used.
    """
    if not text:
        return None
    try:
        rows = erp.erp_get("Payment Terms Template", fields=["name"], limit=0) or []
    except Exception:
        return None
    key = intake._slug(str(text))
    for row in rows:                                   # exact, then one contains the other
        if intake._slug(row.get("name") or "") == key:
            return row["name"]
    for row in rows:
        cand = intake._slug(row.get("name") or "")
        if cand and (cand in key or key in cand):
            return row["name"]
    want = _terms_key(text)                            # same days, same event
    if want[0]:
        for row in rows:
            if _terms_key(row.get("name") or "") == want:
                return row["name"]
    return None


def _step_project(facts: dict, matches: dict) -> dict:
    po = facts.get("po") or {}
    if not (matches.get("customer") or (facts.get("buyer") or {}).get("name")):
        return _step("project", "Project — blocked", "Project", {}, status="blocked",
                     reason="needs the Customer")
    name = f"{(facts.get('buyer') or {}).get('name') or matches.get('customer')} · {po.get('number') or 'no PO'}"
    step = _step("project", f"Project — {name[:60]}", "Project",
                 {"doctype": "Project", "project_name": name[:140],
                  "company": matches.get("company") or "", "status": "Open"})
    step["depends_on"] = "customer"
    return step


def _step_bom(facts: dict, matches: dict) -> dict:
    reason = ""
    if not _has_sizes(facts):
        reason = "no size grid on the paper — a BOM is per size, so this waits for the buyer's grid"
    elif not matches.get("fabric_item"):
        reason = "the fabric on the PO is not mapped to one of our items (Item Mapping)"
    else:
        reason = "consumption (yardage per size) is not on the PO — the CAD room issues it"
    return _step("bom", "BOM per size — not created", "BOM", {}, status="blocked", reason=reason)


def _step_ack_task(facts: dict, matches: dict) -> dict:
    asks = facts.get("asks") or []
    subject = "Answer the buyer" + (f" — {len(asks)} question(s)" if asks else "")
    desc = "\n".join(f"- {a}" for a in asks) or "- no direct question in the mail"
    return _step("ack", subject, "Task",
                 {"doctype": "Task", "subject": subject[:140],
                  "description": f"From the intake of {(facts.get('po') or {}).get('number') or 'an order mail'}:\n{desc}",
                  "priority": "High" if asks else "Medium"}, kind="task")


def _step_opportunity(facts: dict, matches: dict) -> dict:
    po = facts.get("po") or {}
    styles = [x for x in (facts.get("styles") or []) if x]
    if not styles and (facts.get("style") or {}).get("code"):
        styles = [facts["style"]["code"]]
    asked = " / ".join(styles) if len(styles) > 1 else (po.get("number") or (styles[0] if styles else "enquiry"))
    title = f"{(facts.get('buyer') or {}).get('name') or 'Buyer'} — {asked}"
    buyer = (facts.get("buyer") or {}).get("name")
    payload = {"doctype": "Opportunity", "opportunity_from": "Customer",
               "party_name": matches.get("customer") or "",
               "customer_name": buyer or "",
               "title": title[:140], "status": "Open",
               "currency": (facts.get("commercial") or {}).get("currency") or config.DEFAULT_CURRENCY,
               "opportunity_amount": _num((facts.get("commercial") or {}).get("total_value")),
               "transaction_date": _today()}
    if facts.get("ship_date"):
        payload["expected_closing"] = facts["ship_date"]

    # The styles the buyer asked for, as Opportunity Item rows — the native home for "what
    # they want". A style we have made before carries the price we last sold it at, so the
    # enquiry is valued from history instead of starting at zero (2026-11-03).
    items: list[dict] = []
    notes: list[dict] = []
    try:
        import inquiry as _inq
        asked = _inq.lines(facts, codes=styles)
        total = _num((facts.get("commercial") or {}).get("total_qty"))
        if len(asked) > 1 and total:
            notes.append({"doctype": "CRM Note",
                          "note": (f"<p>Quantity asked: <b>{int(total):,} pcs</b> across "
                                   f"{len(asked)} styles — the mail does not split it per style.</p>")})
        for line in asked:
            qty = _num(line.get("qty"))
            rate = _num(line.get("last_price"))
            # ERPNext refuses a line whose qty is 0, and a split we do not have cannot be
            # invented — so an unquantified ask becomes a NOTE on the Opportunity instead of
            # a line pretending to be 1 pc (2026-11-03: "Quantity must be greater than 0").
            if qty > 0:
                row = {"item_name": line.get("style"),
                       "description": (line.get("description") or line.get("style") or "")[:140],
                       "qty": qty, "rate": rate, "amount": round(qty * rate, 2),
                       "base_rate": rate, "base_amount": round(qty * rate, 2)}
                if line.get("item"):
                    row["item_code"] = line["item"]
                if line.get("uom"):
                    row["uom"] = line["uom"]
                items.append(row)
            notes.append({"doctype": "CRM Note", "note": _style_note(line)})
    except Exception:                                                # noqa: BLE001
        items, notes = [], []        # no history read = no lines, and the step says so below
    if items:
        payload["items"] = items
        if not payload["opportunity_amount"]:
            total_ = sum(i["amount"] for i in items)
            if total_:
                payload["opportunity_amount"] = round(total_, 2)
    if notes:
        payload["notes"] = notes

    # The Customer step runs first and its name is filled in there, so the only
    # remaining block is having no buyer at all.
    blocked = "" if (matches.get("customer") or buyer) else \
        "the buyer name could not be read from the mail"
    step = _step("opportunity", f"Opportunity — {title[:50]}", "Opportunity", payload,
                 status="blocked" if blocked else "ready", reason=blocked)
    if not blocked and not items:
        step_reason = "the styles in this mail could not be read against the item master"
        step["reason"] = step_reason
    elif not blocked and items:
        known = [i for i in items if i.get("rate")]
        step["reason"] = (f"{len(items)} style(s) on the line — "
                          + (f"{len(known)} already priced from history" if known else
                             "none made before, so the price comes from costing"))
    if not blocked and not matches.get("customer"):
        step["depends_on"] = "customer"
        step["reason"] = (step.get("reason") or "") + \
            " · carries the Customer this approval creates"
    return step


PACK_WORDS = ("tech pack", "techpack", "tech-pack", "bill of material", "bom",
              "measurement", "spec sheet", "size spec", "grading", "grade rule")


def _style_note(line: dict) -> str:
    """One style, its verdict, and the record behind it — written on the Opportunity."""
    bits = [f"<b>{line.get('style')}</b>"]
    if line.get("description"):
        bits.append(str(line["description"])[:120])
    verdict = line.get("verdict") or "new"
    if verdict in ("made", "costed") and line.get("last_price"):
        last = line.get("last_order") or {}
        tail = f" (last sold {line.get('currency') or ''} {_num(line.get('last_price')):,.2f}"
        if last.get("sales_order"):
            tail += f" on {last.get('sales_order')} {last.get('date') or ''}".rstrip()
        bits.append((line.get("label") or verdict) + tail + ")")
    else:
        bits.append(line.get("label") or verdict)
    if (line.get("cost") or {}).get("name"):
        bits.append(f"cost sheet {line['cost']['name']}")
    if (line.get("bom") or {}).get("count"):
        bits.append(f"{line['bom']['count']} BOM(s)")
    if (line.get("tech_pack") or {}).get("name"):
        bits.append(f"pack {line['tech_pack']['name']}")
    return "<p>Asked: " + " · ".join(bits) + "</p>"


def _steps_pack_ingest(facts: dict, matches: dict) -> list[dict]:
    """The tech pack / BOM documents arrived in the thread — read each into the ERP.

    ONE step per document: a mail can carry three BOMs, and ingesting "the biggest one" left
    two styles without a BOM and said nothing about it (2026-11-03).

    Deliberately a step the human approves, not something the mailbox does on its own:
    ingesting a pack creates a Buyer Tech Pack, a Buyer BOM and one BOM per size, and that
    is a costing decision, not a mail-reading one.
    """
    packs = facts.get("_pack_documents") or []
    if packs:
        steps = []
        for n, d in enumerate(packs, 1):
            name = d.get("filename") or ""
            payload = {"doctype": "Buyer Tech Pack", "attachment_id": d.get("attachment_id"),
                       "filename": name,
                       "style_code": (facts.get("style") or {}).get("code") or "",
                       "customer": matches.get("customer") or "",
                       "opportunity": (matches.get("chain") or {}).get("opportunity") or ""}
            steps.append(_step(f"pack{n}", f"Ingest the pack — {name}", "Buyer Tech Pack", payload,
                               status="ready", kind="ingest_pack",
                               reason=f"reads as a {d.get('kind')} — Buyer Tech Pack + one BOM per size"))
        return steps

    # older facts (before the per-document split) — behave as one document
    att_id = facts.get("_attachment_id")
    name = facts.get("_attachment_name") or ""
    if not att_id:
        return [_step("pack", "Tech pack — nothing attached", "Buyer Tech Pack", {},
                      status="blocked",
                      reason="this mail carries no document — the pack was not attached")]
    words = facts.get("_pack_words") or []
    if not words:
        return [_step("pack", f"Tech pack — {name}", "Buyer Tech Pack", {}, status="blocked",
                      reason=("the attachment does not read as a tech pack or a BOM "
                              "(no measurement, material list or size spec found in it)"))]
    payload = {"doctype": "Buyer Tech Pack", "attachment_id": att_id, "filename": name,
               "style_code": (facts.get("style") or {}).get("code") or "",
               "customer": matches.get("customer") or "",
               "opportunity": (matches.get("chain") or {}).get("opportunity") or "",
               "words": words}
    return [_step("pack", f"Ingest the pack — {name}", "Buyer Tech Pack", payload,
                  status="ready", kind="ingest_pack",
                  reason="reads as a " + "/".join(words[:3]) + " — Buyer Tech Pack + one BOM per size")]


def _step_cost_task(facts: dict, matches: dict) -> dict:
    return _step("costing", "Cost the enquiry (Task)", "Task",
                 {"doctype": "Task", "subject": "Cost the enquiry and issue a quotation",
                  "description": "Intake read an enquiry. Draft the cost sheet, then the quotation.",
                  "priority": "High"}, kind="task")


def _step_revision_task(facts: dict, matches: dict) -> dict:
    diff = _diff_note(facts, matches)
    return _step("revision", "Apply the revision (Task)", "Task",
                 {"doctype": "Task", "subject": f"Apply PO revision {(facts.get('po') or {}).get('number')}",
                  "description": diff, "priority": "High"}, kind="task")


def _step_finance_task(facts: dict, matches: dict) -> dict:
    po = (facts.get("po") or {}).get("number") or "no reference"
    return _step("finance", "Reconcile (Task)", "Task",
                 {"doctype": "Task", "subject": f"Reconcile {facts.get('document_type')} — {po}",
                  "description": "Matched to the mailbox; needs the accounts desk.", "priority": "Medium"},
                 kind="task")


def _step_generic_task(facts: dict, matches: dict) -> dict:
    return _step("general", "Handle the mail (Task)", "Task",
                 {"doctype": "Task", "subject": f"Inbound mail — {(facts.get('po') or {}).get('number') or facts.get('document_type')}",
                  "description": "No process matched automatically.", "priority": "Low"}, kind="task")


# ── helpers ────────────────────────────────────────────────────────────────
def _has_sizes(facts: dict) -> bool:
    for line in facts.get("lines") or []:
        if line.get("size_grid") or line.get("size"):
            return True
    return False


def _resolve_item_code(style_code: Optional[str], size: Optional[str], matches: dict) -> Optional[str]:
    variants = matches.get("style_variants") or []
    if not style_code and not variants:
        return None
    code = (style_code or "").upper()
    if size and code:
        exact = f"{code}-{size.upper()}"
        if exact in variants:
            return exact
        if not variants:
            # a single-SKU order (no size) may sit on the template's first variant
            first = sorted(variants)[0] if variants else None
            return first
        return None
    if len(variants) == 1:
        return variants[0]
    return matches.get("style_item") if not variants else None


def _avg_conf(facts: dict) -> float:
    conf = [v for v in (facts.get("confidence") or {}).values() if isinstance(v, (int, float))]
    return sum(conf) / len(conf) if conf else 0.0


def _notes(facts: dict) -> str:
    bits = []
    for item in facts.get("claims") or []:
        bits.append(f"buyer instruction: {item}")
    for item in facts.get("asks") or []:
        bits.append(f"buyer asks: {item}")
    for item in facts.get("missing") or []:
        bits.append(f"not on the paper: {item}")
    return "\n".join(bits)[:4000]


def _diff_note(facts: dict, matches: dict) -> str:
    ex = matches.get("po_existing_detail") or {}
    c = facts.get("commercial") or {}
    out = []
    if ex.get("total_qty") and c.get("total_qty") and _num(ex["total_qty"]) != _num(c["total_qty"]):
        out.append(f"quantity {_num(ex['total_qty']):,.0f} → {_num(c['total_qty']):,.0f}")
    if facts.get("ship_date"):
        out.append(f"ship date now {facts['ship_date']}")
    if not out:
        out.append("revision read, but no quantity or date change was found — check the paper")
    out.append("quantity, price and date changes are never applied automatically.")
    return "\n".join(out)


# ────────────────────────────────────────────────────────────────────────────
# Execute
# ────────────────────────────────────────────────────────────────────────────
_PACK_WORDS = ("tech pack", "techpack", "tech-pack", "bill of material", "bom",
               "measurement", "spec sheet", "size spec", "grading", "grade rule")
_PACK_EXT = (".pdf", ".xlsx", ".xlsm", ".xls", ".csv")


def pack_words(filename: str = "", mime: str = "", text: str = "") -> list[str]:
    """Does this attachment read as a tech pack / BOM? Returns the words that say so.

    Deterministic on purpose: a pack is recognised by what is IN it (measurements, a
    material list, a size spec) or by what it is CALLED, and the answer is reported so a
    human can disagree. Nothing is ingested just because a file is attached.
    """
    name = (filename or "").lower()
    if not (name.endswith(_PACK_EXT) or (mime or "").startswith(("application/pdf",
                                                                 "application/vnd.ms-excel",
                                                                 "application/vnd.openxmlformats"))):
        return []
    blob = f"{name}\n{(text or '')[:200000]}".lower()
    return [w for w in _PACK_WORDS if w in blob]


def _link_chain(db, run, refs: list[dict], customer: Optional[str]) -> None:
    """Attach everything this approval created to the conversation it came from.

    The point is that the next mail in the thread — and a human six weeks later — finds
    the Opportunity from the mail, not from a search on the buyer's name.
    """
    if db is None:
        return
    try:
        import chain as chain_mod
        row = chain_mod.newest_for_run(db, run)
        if row is None:
            return
        if customer:
            chain_mod.link(db, row, "Customer", customer)
            row.customer = customer
        for ref in refs or []:
            chain_mod.link(db, row, ref.get("doctype") or "", ref.get("name") or "")
        db.commit()
    except Exception as ex:                                            # noqa: BLE001
        print(f"chain link skipped: {type(ex).__name__}: {ex}", file=__import__("sys").stderr)


def _verify_refs(refs: list[dict]) -> tuple[list, list, list]:
    """Split the ledger into what the ERP still holds, what is gone, and what we
    could not check. **The ledger is a claim; the ERP is the fact** (2026-11-04, D-123).

    Before this, a record deleted in the ERP still counted as "already created by an
    earlier approval", so the queue skipped the step and then built a Sales Order
    against the ghost: `Could not find Customer: HARBOR & LANE…, Project: PROJ-0043,
    Client Purchase Order: CPO-01242`.
    """
    live, ghosts, unknown = [], [], []
    for ref in refs or []:
        if not isinstance(ref, dict):
            continue
        dt, name = ref.get("doctype"), ref.get("name")
        if not dt or not name:
            continue
        state = erp.erp_ref_state(dt, name)
        if state == erp.FOUND:
            live.append(ref)
        elif state == erp.MISSING:
            ghosts.append(ref)
        else:
            unknown.append({**ref, "reason": erp.erp_doc_checked(dt, name).reason})
    return live, ghosts, unknown


# Payload fields that name an ERP record. A frozen plan carries these as literals
# (``project: PROJ-0043``), so execute() must re-ask the ERP rather than trust them.
_PLAN_LINK_FIELDS = {
    "customer": "Customer",
    "party_name": "Customer",
    "project": "Project",
    "custom_client_po": "Client Purchase Order",
    "opportunity": "Opportunity",
    "supplier": "Supplier",
}


def _drop_dead_links(payload: dict, notes: list, fresh: Optional[set] = None,
                     doctype: str = "") -> bool:
    """Blank any link in ``payload`` whose target no longer exists.

    Returns False when a target could not be *checked* (ERP unavailable): the caller
    must stop rather than guess. ``company`` and item fields are deliberately left
    alone — a company is a constant and a style line is (re)created by an earlier step.
    """
    ok = True
    fresh = fresh or set()
    try:
        _required_map = required_fields(doctype) if doctype else {}
    except Exception:
        _required_map = {}
    # `required_fields()` deliberately omits the fields a *step* of the approval fills
    # (`_FILLED_BY_STEPS`), which is exactly where `customer` lives. At execute time those
    # must not be dropped either: a Sales Order or a Client PO without a buyer is a record
    # nobody can act on. Blocking is the honest answer (2026-11-04).
    _must_have = set(_required_map) | {"customer"}
    for field, doctype in _PLAN_LINK_FIELDS.items():
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        if (doctype, value) in fresh:
            continue            # written by this very execution — no need to re-read it
        res = erp.erp_doc_checked(doctype, value)
        if res.state == erp.FOUND:
            continue
        if res.state == erp.MISSING:
            if field in _must_have:
                # required on this doctype: blanking it would create a document with no buyer
                notes.append(f"blocked: {field}={value} — {doctype} no longer exists in the ERP, "
                             f"and the site requires a {field}")
                ok = False
                continue
            payload.pop(field, None)
            notes.append(f"dropped {field}={value} — {doctype} no longer exists in the ERP")
        else:
            ok = False
            notes.append(f"cannot verify {field}={value} ({doctype}): {res.reason} — stopping")
    return ok


def prune_matches(matches: dict) -> list:
    """Drop every pointer in ``matches`` that the ERP no longer holds.

    ``matches`` is written when the card is READ. By the time it is approved the world may
    have moved, and a stale pointer is worse than no pointer: run 9's plan said
    *"Customer — reuse HARBOR & LANE APPAREL CO. … already in the ERP"* for a buyer that had
    been deleted, which is the sentence that made the operator trust the plan. Pruning here
    means the plan he is shown is the plan that will run (2026-11-04).
    """
    dropped = []
    for field, doctype in (("customer", "Customer"), ("po_existing", "Client Purchase Order"),
                           ("project_name", "Project"), ("style_item", "Item"),
                           ("fabric_item", "Item"), ("company", "Company")):
        value = (matches or {}).get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        state = erp.erp_ref_state(doctype, value)
        if state == erp.MISSING:
            matches.pop(field, None)
            dropped.append(f"{field}={value}")
        elif state == erp.UNAVAILABLE:
            dropped.append(f"{field}={value} (unverifiable)")
    if dropped:
        matches["_stale_dropped"] = dropped
    return dropped


def rebuilt_plan(facts: dict, matches: dict) -> tuple:
    """``(plan, notes)`` — prune what is gone, re-classify the buyer's references, re-plan."""
    notes = []
    dropped = prune_matches(matches)
    if dropped:
        notes.append("dropped stale pointers: " + ", ".join(dropped))
    try:
        import buyer_ref as _refs
        f_po = (facts.get("po") or {})
        cls = _refs.classify(erp, matches.get("customer"),
                             [f_po.get("number"), f_po.get("reference")])
        for _k in ("refs", "order_ref", "order_ref_label", "order_ref_type"):
            if cls.get(_k) is not None:
                matches[_k] = cls.get(_k)
    except Exception:                                            # noqa: BLE001
        pass
    try:
        return build_plan(facts, matches), notes
    except Exception as exc:                                     # noqa: BLE001
        notes.append(f"could not rebuild the plan ({type(exc).__name__})")
        return [], notes


def execute(db, run, actor: str = "Ops Manager", rebuild: bool = False) -> dict:
    """Run the plan. Draft-only, in order, stopping each step that cannot work.

    ``rebuild=True`` (the approval path) recomputes the plan from the mail **now** instead of
    trusting the payload frozen when the card was read. A stored plan is a photograph of a
    world that has moved: run 9's was built on 11-03 12:38, before the buyer-reference
    classifier existed, so the Client PO it created carried no typed reference at all
    (2026-11-04). Unit tests keep passing their own plan, so ``rebuild`` defaults to False.
    """
    import json as _json
    plan = _json.loads(run.plan or "[]")
    facts = _json.loads(run.facts or "{}")
    matches = _json.loads(run.matches or "{}")
    # What an EARLIER attempt already created. A run can fail halfway (a validation on one
    # record blocks the rest), and re-approving it must finish the job, not duplicate the
    # Customer and the Task it already made (2026-11-03: the Opportunity was refused over a
    # qty of 0 and the re-approval would have created "HARBOR & LANE" twice).
    try:
        prev_refs = _json.loads(run.created_refs or "[]")
    except Exception:
        prev_refs = []
    notes: list[str] = []

    if rebuild:
        fresh_plan, plan_notes = rebuilt_plan(facts, matches)
        notes.extend(plan_notes)
        if fresh_plan:
            plan = fresh_plan
            notes.append("the plan was rebuilt from the mail at approval time")

    # ── the ledger is verified against the ERP before it is believed (D-123) ──
    live_refs, ghost_refs, unknown_refs = _verify_refs([r for r in prev_refs if isinstance(r, dict)])
    if unknown_refs:
        # Fail closed: skipping on an unverified ref duplicates records, and creating
        # on an unverified ref makes twins. Neither is acceptable, so say what is wrong.
        names = ", ".join(f"{r['doctype']} {r['name']} ({r.get('reason') or '?'})"
                          for r in unknown_refs[:6])
        run.status = "blocked"
        run.result_note = ("cannot verify " + str(len(unknown_refs)) + " earlier record(s) against the "
                           "ERP: " + names + " — nothing was written; approve again when the ERP answers")
        run.decided_by = actor
        from datetime import datetime as _dt0
        run.decided_at = _dt0.now()
        if db is not None:
            db.commit()
        return {"ok": False, "status": "blocked", "refs": live_refs, "note": run.result_note,
                "customer": matches.get("customer"), "client_po": None, "sales_order": None,
                "unverifiable": unknown_refs}
    if ghost_refs:
        notes.append("the ERP no longer holds " + str(len(ghost_refs)) + " record(s) this approval "
                     "created — they will be created again: "
                     + ", ".join(f"{r['doctype']} {r['name']}" for r in ghost_refs[:6]))
    refs: list[dict] = live_refs
    # one envelope for this execution: the cap (config.MAX_WRITES_PER_RUN) + per-record audit
    batch = _gate.Batch(db, actor, label=f"intake #{getattr(run, 'id', '?')} "
                                            f"({getattr(run, 'route', '?')})")
    for _r in live_refs:
        batch.register(_r.get("doctype"), _r.get("name"), existed=True)
    done = {r.get("step") for r in refs if r.get("step")}
    # a step whose only evidence was a ghost must run again
    for r in ghost_refs:
        done.discard(r.get("step"))
    failed = False

    customer = matches.get("customer")
    if customer:
        res = erp.erp_doc_checked("Customer", customer)
        if res.state != erp.FOUND:
            notes.append(f"the buyer {customer} is no longer in the ERP — resolving it again")
            matches.pop("customer", None)
            customer = None
    cpo_name = None
    so_name = None
    project_name = None
    for r in refs:
        dt, name = r.get("doctype"), r.get("name")
        if dt == "Customer":
            customer = name
        elif dt == "Client Purchase Order":
            cpo_name = name
        elif dt == "Sales Order":
            so_name = name
        elif dt == "Project":
            project_name = name

    for step in plan:
        if step.get("status") == "skipped" or step.get("kind") == "skip":
            notes.append(f"{step['label']}: skipped — {step.get('reason') or 'not used on this ERP'}")
            continue
        if step.get("status") == "blocked":
            notes.append(f"{step['label']}: {step.get('reason') or 'blocked'}")
            continue
        if step.get("key") in done:
            notes.append(f"{step['label']}: already created by an earlier approval — not repeated")
            continue
        payload = dict(step.get("payload") or {})

        if step.get("kind") == "create_many" and payload.get("payloads"):
            made = 0
            skipped = 0
            for row in payload["payloads"]:
                row = dict(row)
                dt = row.pop("doctype", step.get("doctype"))
                # anything already on file is linked, never made twice — the style, its size
                # SKUs and their prices are all keyed on what the site already holds
                if find_existing(dt, row):
                    skipped += 1
                    continue
                if not batch.can_create():
                    notes.append(f"{dt} {row.get('item_code')}: not created — " + batch.errors[-1])
                    continue
                ok, doc, err = _erp_create(dt, row)
                if ok and doc.get("name"):
                    refs.append({"doctype": dt, "name": doc["name"], "step": step["key"]})
                    batch.register(dt, doc["name"], step=step.get("key"))
                    made += 1
                else:
                    notes.append(f"{dt} {row.get('item_code')}: {err}")
            notes.append(f"created {made} record(s) for the style"
                         + (f", {skipped} already on file" if skipped else ""))
            continue

        doctype = payload.pop("doctype", step.get("doctype"))

        # A step that hands the chain's document to the pack builder. It writes a Buyer
        # Tech Pack (+ one BOM per size, when the caller asks for it) through the ONE
        # builder that knows how to read a pack — never a second reader here.
        if step.get("kind") == "ingest_pack":
            import pack_ingest
            from models import MailAttachmentModel
            att = None
            if payload.get("attachment_id"):
                att = (db.query(MailAttachmentModel)
                       .filter(MailAttachmentModel.id == int(payload["attachment_id"])).first())
            import chain as chain_mod
            row = chain_mod.newest_for_run(db, run)
            already = ((json.loads(row.ingested or "{}") or {}).get("_packs") or []) if row else []
            job = {**payload,
                   "path": pack_ingest.resolve_path(att.path if att else ""),
                   "filename": (att.filename if att else payload.get("filename")) or "",
                   "already": already}
            res = pack_ingest.ingest(job, apply=True)
            for ref in res.get("refs") or []:
                refs.append({**ref, "step": step["key"]})
            notes.append(res.get("note") or "")
            if not res.get("ok"):
                failed = True
            continue

        # a "reuse" step carries an existing record forward (the customer already in
        # the ERP, or the Client PO the migration already created) — it is a link,
        # never a copy, and downstream steps must see it.
        if step.get("kind") == "reuse":
            existing = payload.get("existing")
            # A reuse step carries a record the plan *believed* was on file. If it has been
            # deleted since, reusing it builds a document on a ghost — this is exactly how
            # `existing: "HARBOR & LANE APPAREL CO."` reached a Sales Order (D-123).
            if existing:
                res = erp.erp_doc_checked(doctype, existing)
                if res.state == erp.UNAVAILABLE:
                    failed = True
                    notes.append(f"{doctype} {existing}: cannot verify ({res.reason}) — stopping")
                    break
                if res.state == erp.MISSING:
                    notes.append(f"{doctype} {existing} is no longer in the ERP — it will be created again")
                    existing = None
            if doctype == "Customer" and existing:
                customer = existing
                matches["customer"] = existing
                continue
            if doctype == "Client Purchase Order" and existing:
                cpo_name = existing
                matches["po_existing"] = existing
                notes.append(f"linked to existing {doctype} {existing} (not duplicated)")
                continue
            if doctype == "Customer" and not existing:
                # The buyer this plan meant to REUSE was deleted in the ERP. `continue` here
                # used to leave `customer = None`, so every downstream document was built
                # without a buyer: "Sales Order: BLOCKED — Customer: customer is required"
                # (2026-11-04). A missing reuse target is not a skip — it is a CREATE.
                rebuilt = _customer_payload(facts, matches)
                if not rebuilt.get("customer_name"):
                    failed = True
                    notes.append("Customer: the plan meant to reuse a buyer that no longer "
                                 "exists, and the mail names no buyer to create")
                    continue
                if not batch.can_create():
                    failed = True
                    notes.append("Customer: " + batch.errors[-1])
                    continue
                ok_c, doc_c, err_c, _note_c = batch.create(
                    "Customer", rebuilt, facts, {**matches, "customer": None},
                    step=step.get("key"))
                if ok_c and (doc_c or {}).get("name"):
                    customer = doc_c["name"]
                    matches["customer"] = customer
                    refs.append({"doctype": "Customer", "name": customer,
                                 "step": step.get("key")})
                    notes.append(f"created Customer {customer} again "
                                 f"(it had been deleted from the ERP)")
                else:
                    failed = True
                    notes.append(f"Customer: FAILED — {err_c}")
                continue
            continue

        # A "fill" step completes a record that already exists. Thirteen of the
        # fifteen migrated Client POs are header-only, so the PO and the order it
        # produced described different things. Fill ONLY blanks: an empty header
        # field, or an empty line table. A value a human typed is never replaced.
        if step.get("kind") == "fill":
            existing = payload.get("existing")
            if not existing:
                continue
            if doctype == "Client Purchase Order":
                cpo_name = existing
                matches["po_existing"] = existing
                current = erp.erp_doc(doctype, existing) or {}
                blanks = {k: v for k, v in (payload.get("fill") or {}).items()
                          if v not in (None, "", 0, 0.0) and current.get(k) in (None, "", 0, 0.0)}
                row_lines = payload.get("lines") or []
                if not (current.get("lines") or []) and row_lines:
                    blanks["lines"] = row_lines
                elif row_lines:
                    notes.append(f"{existing} already carries {len(current.get('lines') or [])} line(s) — left untouched")
                if blanks:
                    ok, _doc, err = erp.erp_update(doctype, existing, blanks)
                    notes.append(f"filled {len(blanks)} field(s) on {existing}" if ok
                                 else f"fill {existing}: FAILED — {err}")
                    if not ok:
                        failed = True
                else:
                    notes.append(f"{existing} already complete — nothing to fill")
            continue

        # fill the links the earlier steps produced, after dropping any that no longer
        # exist in the ERP (a frozen plan carries literals such as `project: PROJ-0043`)
        if doctype == "Client Purchase Order":
            payload["customer"] = customer or ""
        if doctype == "Sales Order":
            payload["customer"] = customer or payload.get("customer")
            if cpo_name:
                payload["custom_client_po"] = cpo_name
            if project_name:
                payload["project"] = project_name
        if doctype == "Project":
            payload["company"] = payload.get("company") or (matches.get("company") or "")
            if payload.get("project_name"):
                matches["project_name"] = payload["project_name"]
        if doctype == "Opportunity":
            # the Customer is created by an earlier step in this same approval
            payload["party_name"] = customer or payload.get("party_name") or ""
        if doctype == "Purchase" or not doctype:
            continue

        # every remaining link must still exist — verified, not trusted
        if not _drop_dead_links(payload, notes,
                                {(r.get("doctype"), r.get("name")) for r in refs}, doctype):
            failed = True
            continue

        # The site's own required fields, resolved NOW: the Customer, the Client PO and the
        # Project of this approval are only known after the links above are filled.
        try:
            payload, missing = preflight(doctype, payload, facts, matches)
            payload["doctype"] = doctype
        except Exception:
            missing = []
        if missing:
            failed = True
            notes.append(f"{doctype}: BLOCKED — " +
                         " · ".join(f"{lbl}: {hint}" for _f, lbl, hint in missing))
            continue

        # De-duplicate against the SITE, not against a list of step keys: a second mail
        # carrying the same PO, or a re-approval after any failure, must link the record
        # that exists rather than make a twin (2026-11-03).
        try:
            already = find_existing(doctype, payload)
        except Exception:
            already = None
        if already:
            refs.append({"doctype": doctype, "name": already, "step": step["key"]})
            notes.append(f"{doctype} {already} already exists — linked, not duplicated")
            if doctype == "Customer":
                customer = already
                matches["customer"] = already
            elif doctype == "Client Purchase Order":
                cpo_name = already
            elif doctype == "Project":
                project_name = already
                matches["project_name"] = already
            continue

        if not batch.can_create():
            failed = True
            notes.append(f"{doctype}: " + batch.errors[-1])
            continue
        ok, doc, err = _erp_create(doctype, payload)
        # a duplicate is not a failure when the record is the one we meant to make
        if not ok and doctype == "Customer" and payload.get("customer_name"):
            found = erp.erp_get("Customer", fields=["name"],
                                filters=[["customer_name", "=", payload["customer_name"]]],
                                limit=1) or []
            if found:
                ok, doc, err = True, {"name": found[0]["name"]}, ""
                notes.append(f"Customer {found[0]['name']} was already on file — linked, not duplicated")
        if ok and doc.get("name"):
            name = doc["name"]
            refs.append({"doctype": doctype, "name": name, "step": step["key"]})
            batch.register(doctype, name, step=step.get("key"))
            if doctype == "Customer":
                customer = name
                matches["customer"] = name
            elif doctype == "Client Purchase Order":
                cpo_name = name
            elif doctype == "Project":
                project_name = name
            elif doctype == "Sales Order":
                so_name = name
                if cpo_name:
                    erp.erp_update("Client Purchase Order", cpo_name,
                                   {"linked_sales_order": so_name, "intake_status": "Ordered"})
            notes.append(f"created {doctype} {name}")
        else:
            failed = True
            notes.append(f"{doctype}: FAILED — {err}")
            if doctype in ("Customer", "Client Purchase Order"):
                break            # everything downstream depends on these

    # The CPO step can run BEFORE the buyer exists (a `reuse` step whose target was deleted,
    # re-created a step later). Fill the blank rather than leave a PO with no buyer.
    if cpo_name:
        try:
            cur = erp.erp_doc("Client Purchase Order", cpo_name) or {}
            fill: dict = {}
            if customer and not cur.get("customer"):
                fill["customer"] = customer
            if not (cur.get("refs") or []) and (matches.get("refs") or []):
                refs_rows = buyer_ref.rows_for_payload(matches["refs"])
                if refs_rows:
                    fill["refs"] = refs_rows
                    for _k in ("order_ref", "order_ref_type", "order_ref_label",
                               "order_ref_normalised"):
                        if matches.get(_k) and not cur.get(_k):
                            fill[_k] = matches[_k]
            if fill:
                ok_fix, _d, err_fix = erp.erp_update("Client Purchase Order", cpo_name, fill)
                notes.append(f"filled {', '.join(sorted(fill))} on {cpo_name}" if ok_fix
                             else f"could not fill {cpo_name}: {err_fix}")
        except Exception:
            pass

    # a draft order created against an EXISTING client PO must point at it
    if so_name and cpo_name:
        try:
            erp.erp_update("Sales Order", so_name, {"custom_client_po": cpo_name})
        except Exception:
            pass

    # stamp the CPO with the provenance and the final state
    if cpo_name and not failed:
        erp.erp_update("Client Purchase Order", cpo_name, {
            "intake_status": "Ordered" if so_name else "Received",
            "source_message_id": (facts.get("_message_id") or "")[:140],
            "source_attachment": (facts.get("_attachment") or "")[:140],
            "parse_confidence": round(_avg_conf(facts), 2),
        })

    status = "blocked" if failed else "approved"
    run.status = status
    run.created_refs = _json.dumps(refs)
    run.result_note = "\n".join(notes)[:4000]
    run.decided_by = actor
    from datetime import datetime as _dt
    run.decided_at = _dt.now()
    _link_chain(db, run, refs, customer)
    if db is not None:
        db.commit()
    return {"ok": not failed, "status": status, "refs": refs, "note": run.result_note,
            "customer": customer, "client_po": cpo_name, "sales_order": so_name}


def rollback(refs: list[dict]) -> dict:
    """Delete what this approval created, newest first. Drafts only.

    Delegates to :func:`write_gate.rollback_refs` — ONE rollback for both write paths.
    The local implementation counted a 404 as *kept*, so ``rollback_intake`` reported
    failure and never cleared ``created_refs``; a record someone had already deleted in
    the ERP is now *already gone*, which is the desired end state, not an error
    (2026-11-04, D-124).
    """
    res = _gate.rollback_refs(refs)
    return {"ok": res["ok"], "deleted": res["deleted"], "kept": res["kept"],
            "already_missing": res.get("already_missing") or []}


# ────────────────────────────────────────────────────────────────────────────
# Acknowledgement (grounded — only what the ERP knows)
# ────────────────────────────────────────────────────────────────────────────
def ack_draft(facts: dict, matches: dict, refs: list[dict], sender_name: str = "") -> dict:
    """A reply to the buyer that answers only what the mail asked, using facts only."""
    import email_engine

    po = (facts.get("po") or {}).get("number") or "your order"
    buyer = (facts.get("buyer") or {}).get("name") or "Sir/Madam"
    style = (facts.get("style") or {}).get("code") or ""
    c = facts.get("commercial") or {}
    lines = facts.get("lines") or []
    qty = c.get("total_qty")
    ship = facts.get("ship_date")

    if lines:
        qty_txt = ", ".join(f"{l.get('colour')} {int(_num(l.get('qty'))):,}" for l in lines if l.get("colour"))
        if not qty_txt:
            qty_txt = f"{int(_num(qty)):,} pcs" if qty else ""
    else:
        qty_txt = f"{int(_num(qty)):,} pcs" if qty else ""

    body_lines = [f"Dear {buyer},", "", f"Thank you for {po}. We have recorded it as follows:", ""]
    if style:
        body_lines.append(f"Style: {style}")
    if qty_txt:
        body_lines.append(f"Quantity: {qty_txt}")
    if c.get("rate"):
        body_lines.append(f"Rate: {c.get('currency') or ''} {_num(c.get('rate')):,.2f} per piece".replace("  ", " "))
    if ship:
        body_lines.append(f"Ship date: {ship}")
    if c.get("incoterm"):
        body_lines.append(f"Terms: {c['incoterm']} {c.get('named_place') or ''}".strip())
    if c.get("payment_terms"):
        body_lines.append(f"Payment: {c['payment_terms']}")
    body_lines.append("")

    asks = facts.get("asks") or []
    answered = []
    for ask in asks:
        low = ask.lower()
        if "confirm" in low and ("ship" in low or "date" in low):
            answered.append(f"Ship date: we have {ship} against {po}." if ship
                            else "Ship date: we are confirming it and will revert today.")
        elif "lab dip" in low:
            answered.append("Lab dip: we will send it for your approval.")
        elif "packing" in low or "carton" in low:
            ratio = (facts.get("quality") or {}).get("carton_ratio")
            answered.append(f"Packing: {int(_num(ratio))} pcs per carton." if ratio else
                            "Packing: we will confirm the carton ratio.")
    if answered:
        body_lines += answered + [""]

    if facts.get("claims"):
        body_lines.append("Noted on production:")
        body_lines += [f"- {c_}" for c_ in facts["claims"]]
        body_lines.append("")

    created = [r for r in refs if r.get("doctype") in ("Client Purchase Order", "Sales Order")]
    if created:
        body_lines.append("Our reference: " + ", ".join(f"{r['doctype']} {r['name']}" for r in created))
        body_lines.append("")
    body_lines += ["Best regards,", sender_name or "Cortex Textile Limited"]
    body = "\n".join(body_lines)

    draft = {"subject": f"RE: {po}" + (f" — {style}" if style else ""), "body": body}
    # grounding: every number/date/ref in the draft must exist in the fact sheet
    sheet = {"facts": _flat_facts(facts), "records": refs,
             "window": {"from": facts.get("po", {}).get("date"), "to": ship}}
    verdict = email_engine.validate_grounding(draft, sheet)
    return {**draft, "grounding": verdict}


def _flat_facts(facts: dict) -> dict:
    """Flatten to primitives so ``_allowed`` can whitelist every value used."""
    out: dict = {}

    def walk(node, prefix=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{prefix}{k}.")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{prefix}{i}.")
        elif isinstance(node, (str, int, float)) and node not in (None, ""):
            out[prefix.rstrip(".")] = node
            if isinstance(node, str):
                # a number quoted INSIDE a fact ("60 days from BL") is part of the
                # evidence, so it must be allowed in the draft that quotes it.
                for i, tok in enumerate(re.findall(r"\d[\d,]*\.?\d*", node)):
                    out[f"{prefix}num{i}"] = tok

    walk(facts)
    return out
