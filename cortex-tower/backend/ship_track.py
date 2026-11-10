"""Shipping & document tracking for one deal — what we owe the buyer, when it falls due, and where the goods are.

The Sales Contract is only the promise. Everything the promise *costs us* afterwards lives on four clocks:

* the **factory clock** — ex-factory, ETD, ETA, in-warehouse (the contract's own day counts drive it),
* the **documents clock** — the papers named in ``documents_list``: some are ours to issue, some come from the
  forwarder/carrier, and each is needed by a particular day or the buyer cannot clear the goods,
* the **freight clock** — booking, cut-off, vessel/flight, HBL/MBL/AWB, on-board, arrival,
* the **money clock** — the payment basis and days on the contract decide when the invoice is due.

The ERP holds the *facts* (Sales Contract, Sales Order, Delivery Note, Shipment, Letter of Credit). This module holds
no copy of them: it reads the ERP, derives the plan from the contract's own terms, and remembers only what a person
*ticks off* (a paper actually handed over, on what date, by whom) — because the ERP has no field for "the buyer has
it now".

Nothing here invents a date: a row with no basis says so (``basis: "no date on the contract"``) instead of guessing.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Optional

# ───────────────────────── Incoterms, in the words of the desk ─────────────────────────
# The ERP's Incoterm doctype holds eleven records and nothing else. A merchandiser should never have to guess
# which one is right, so each one carries: what it means, the point where risk passes, and who pays freight,
# insurance and import duty. Written for someone who ships garments, not for a lawyer.
INCOTERMS: list[dict] = [
    {"code": "EXW", "name": "Ex Works", "meaning": "The buyer collects from our factory. We only pack the goods.",
     "risk": "At our factory door", "freight": "Buyer", "insurance": "Buyer", "duty": "Buyer",
     "modes": "any", "use_when": "The buyer has their own forwarder and collects from the factory."},
    {"code": "FCA", "name": "Free Carrier", "meaning": "We hand the goods to the buyer's carrier at a named place "
     "(our airport/CFS), cleared for export. The buyer pays the main freight.",
     "risk": "When the carrier takes them at the named place", "freight": "Buyer", "insurance": "Buyer", "duty": "Buyer",
     "modes": "any", "use_when": "The buyer books the freight but we do the export paperwork and handover."},
    {"code": "FAS", "name": "Free Alongside Ship", "meaning": "We put the goods alongside the vessel at the loading "
     "port. Sea freight only.", "risk": "Alongside the vessel at the port of loading",
     "freight": "Buyer", "insurance": "Buyer", "duty": "Buyer",
     "modes": "sea", "use_when": "Bulk/loose cargo at the quay — rare for garments."},
    {"code": "FOB", "name": "Free On Board", "meaning": "We load the goods on the vessel at the loading port. Sea "
     "freight only; the buyer books and pays the freight.",
     "risk": "When the goods are on board at the loading port", "freight": "Buyer", "insurance": "Buyer", "duty": "Buyer",
     "modes": "sea", "use_when": "The classic garment FOB shipment from China/Vietnam to the US or EU."},
    {"code": "CPT", "name": "Carriage Paid To", "meaning": "We pay the carriage to the named destination; the risk "
     "passes to the buyer when we hand over to the first carrier.",
     "risk": "On handover to the first carrier", "freight": "Seller", "insurance": "Buyer", "duty": "Buyer",
     "modes": "any", "use_when": "We pay freight but the buyer carries the risk in transit (and insures)."},
    {"code": "CIP", "name": "Carriage and Insurance Paid To", "meaning": "As CPT, and we also insure the goods "
     "(all-risk cover) to the named destination.",
     "risk": "On handover to the first carrier", "freight": "Seller", "insurance": "Seller", "duty": "Buyer",
     "modes": "any", "use_when": "We pay freight and insurance; the buyer clears import."},
    {"code": "CFR", "name": "Cost and Freight", "meaning": "We pay the sea freight to the destination port; the risk "
     "passes when the goods are on board. Sea freight only.",
     "risk": "When the goods are on board at the loading port", "freight": "Seller", "insurance": "Buyer", "duty": "Buyer",
     "modes": "sea", "use_when": "We pay the ocean freight, the buyer insures and clears import."},
    {"code": "CIF", "name": "Cost, Insurance and Freight", "meaning": "As CFR, and we insure the goods to the "
     "destination port (minimum cover). Sea freight only.",
     "risk": "When the goods are on board at the loading port", "freight": "Seller", "insurance": "Seller", "duty": "Buyer",
     "modes": "sea", "use_when": "We pay ocean freight + insurance; the buyer clears import."},
    {"code": "DAP", "name": "Delivered At Place", "meaning": "We deliver to the buyer's named place (their warehouse "
     "in Los Angeles), ready to unload. We pay freight and carry the risk to there — the buyer pays import duty "
     "and customs clearance.",
     "risk": "At the buyer's door, before unloading", "freight": "Seller", "insurance": "Seller", "duty": "Buyer",
     "modes": "any", "use_when": "The buyer wants the goods delivered to their door but keeps their own import licence."},
    {"code": "DPU", "name": "Delivered at Place Unloaded", "meaning": "As DAP, but we also unload at the destination. "
     "The buyer pays import duty and clearance.",
     "risk": "Once unloaded at the named place", "freight": "Seller", "insurance": "Seller", "duty": "Buyer",
     "modes": "any", "use_when": "The buyer has no way to unload the truck/container at their end."},
    {"code": "DDP", "name": "Delivered Duty Paid", "meaning": "We deliver to the buyer's door and we pay the import "
     "duty, customs clearance and any import VAT. The most work for us; nothing left for the buyer.",
     "risk": "At the buyer's door, duty paid", "freight": "Seller", "insurance": "Seller", "duty": "Seller",
     "modes": "any", "use_when": "A true door-to-door price — the buyer has no importer of record."},
]
TERMS = {t["code"]: t for t in INCOTERMS}
#: Terms that only make sense on a sea/inland-waterway shipment. Using one on an air shipment is a real problem:
#: there is no vessel, no "alongside", no "on board".
SEA_ONLY = {"FAS", "FOB", "CFR", "CIF"}

#: Documents the contract can name, and who actually produces them. "us" = our desk, "carrier" = forwarder/airline,
#: "authority" = chamber of commerce / customs / inspection body.
DOC_OWNER = {
    "invoice": "us", "commercial invoice": "us", "packing list": "us", "packing": "us",
    "fcr": "carrier", "mawb": "carrier", "awb": "carrier", "hbl": "carrier", "mbl": "carrier", "b/l": "carrier",
    "bl": "carrier", "bill of lading": "carrier", "sea waybill": "carrier", "air waybill": "carrier",
    "certificate of origin": "authority", "coo": "authority", "gsp": "authority",
    "inspection certificate": "authority", "fumigation": "authority",
    "insurance policy": "us", "insurance": "us",
    "test report": "us", "care label": "us", "tc": "us",
}

#: The document each basis needs, and how many days before that the paper must exist. ``at`` = same day.
_TICK = ("given", "chased", "na")


def _d(value) -> Optional[date]:
    """A date from whatever the ERP hands back, or None — never an invented one."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value)[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _i(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _f(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _shift(base: Optional[date], days: int) -> Optional[date]:
    return (base + timedelta(days=days)) if base else None


def _row(key: str, label: str, when: Optional[date], *, basis: str = "", today: Optional[date] = None,
         kind: str = "date", extra: Optional[dict] = None) -> dict:
    """One dated obligation, with how it stands today. Never raises for a missing date — it says why."""
    today = today or date.today()
    left = (when - today).days if when else None
    if when is None:
        state = "unknown"
    elif left is None:
        state = "pending"
    elif left < 0:
        state = "late"
    elif left == 0:
        state = "today"
    elif left <= 3:
        state = "soon"
    else:
        state = "pending"
    out = {"key": key, "label": label, "date": when.isoformat() if when else "", "days_left": left,
           "state": state, "kind": kind,
           # a missing date is never papered over with the rule that would have produced it
           "basis": ("no date on the contract" if when is None else (basis or "")),
           "rule": basis or ""}
    if extra:
        out.update(extra)
    return out


# ───────────────────────── the contract, read once ─────────────────────────

def _items(contract: dict) -> list[dict]:
    return [i for i in (contract.get("items") or []) if isinstance(i, dict)]


def _contract_clocks(contract: dict) -> dict:
    """Every date the contract itself sets, by its own terms.

    The header carries the *lead times* (``days_ex_factory_to_etd``, ``transit_days``) and each line carries the
    *anchors* (``ex_factory_date``, ``in_warehouse_date``). A date that only exists on a line is taken from the
    **latest** line: the shipment is not ready until its last style is.
    """
    items = _items(contract)
    exf = max((_d(i.get("ex_factory_date")) for i in items if _d(i.get("ex_factory_date"))), default=None)
    etd = max((_d(i.get("etd")) for i in items if _d(i.get("etd"))), default=None)
    iwd = max((_d(i.get("in_warehouse_date")) for i in items if _d(i.get("in_warehouse_date"))), default=None)
    gap = _i(contract.get("days_ex_factory_to_etd"))
    transit = _i(contract.get("transit_days"))
    if etd is None and exf is not None and gap:
        etd = _shift(exf, gap)
    eta = _shift(etd, transit) if (etd and transit) else None
    basis = (contract.get("payment_basis") or "").strip()
    pay_days = _i(contract.get("payment_days"))
    return {"items": items, "ex_factory": exf, "etd": etd, "eta": eta, "in_warehouse": iwd,
            "gap": gap, "transit": transit, "payment_basis": basis, "payment_days": pay_days}


def _payment_due(clocks: dict, signed_on: Optional[date]) -> tuple[Optional[date], str]:
    """When the money is due, from the contract's own basis. Says the rule in words, so nobody has to remember it."""
    basis, days = clocks["payment_basis"].lower(), clocks["payment_days"]
    anchor, why = None, ""
    if "rog" in basis or "receipt of goods" in basis:
        anchor, why = clocks["in_warehouse"], f"{days} days after the goods arrive in the buyer's warehouse"
    elif "bill of lading" in basis or basis.strip() in ("bl", "b/l"):
        anchor, why = clocks["etd"], f"{days} days after the bill of lading / AWB date"
    elif "invoice" in basis:
        anchor, why = clocks["etd"], f"{days} days after the invoice date"
    elif "sight" in basis or "advance" in basis:
        anchor, why = clocks["in_warehouse"], "at sight — payment is due when the documents are presented"
    elif "shipment" in basis:
        anchor, why = clocks["etd"], f"{days} days after shipment"
    elif "acceptance" in basis:
        anchor, why = clocks["etd"], f"{days} days after acceptance"
    else:
        anchor, why = clocks["in_warehouse"], (f"{days} days after the goods arrive" if days else "basis not readable on the contract")
    return (_shift(anchor, days) if anchor else None), why


# ───────────────────────── documents: what we owe and by when ─────────────────────────

def _split_docs(text: str) -> list[tuple[str, str]]:
    """The contract's ``documents_list`` is free text ("Invoice, Packing List, FCR or MAWB"). Read the papers out of it.

    Returns ``(key, label)`` pairs, de-duplicated, with the label written the way a shipping desk writes it ("MAWB",
    not "Mawb") because this list is what the buyer checks the envelope against.
    """
    raw = (text or "").replace("\n", ",").replace(";", ",").replace("/", ",")
    seen, out = set(), []
    for chunk in raw.split(","):
        c = chunk.strip(" .-").strip()
        if not c:
            continue
        low = c.lower()
        # "FCR or MAWB" is one line naming two papers
        for part in low.replace(" or ", ",").replace(" and ", ",").split(","):
            p = part.strip()
            if not p:
                continue
            k = _doc_key(p)
            if k in seen:
                continue
            seen.add(k)
            out.append((k, DOC_LABEL.get(k) or c))
    return out


#: How each paper is written on a shipping envelope. The contract's free text is often abbreviated or title-cased by
#: the form; the desk's own name for the paper is used instead.
DOC_LABEL = {
    "invoice": "Commercial Invoice", "packing_list": "Packing List", "fcr": "FCR (forwarder's cargo receipt)",
    "awb": "MAWB / AWB", "bl": "Bill of Lading", "certificate_of_origin": "Certificate of Origin",
    "insurance": "Insurance Policy", "inspection_certificate": "Inspection Certificate",
    "fumigation": "Fumigation Certificate", "test_report": "Test Report",
}


def _doc_key(label: str) -> str:
    low = label.lower().strip()
    if "packing" in low:
        return "packing_list"
    if "invoice" in low:
        return "invoice"
    if "fcr" in low or "forwarder" in low:
        return "fcr"
    if "mawb" in low or "awb" in low or "air waybill" in low:
        return "awb"
    if "hbl" in low or "mbl" in low or "b/l" in low or "bill of lading" in low or "bl" == low:
        return "bl"
    if "origin" in low or low == "coo":
        return "certificate_of_origin"
    if "insurance" in low:
        return "insurance"
    if "inspect" in low:
        return "inspection_certificate"
    if "fumig" in low:
        return "fumigation"
    if "test" in low:
        return "test_report"
    return "doc:" + low[:40].replace(" ", "_")


def _doc_owner(label: str) -> str:
    low = label.lower()
    for k, v in DOC_OWNER.items():
        if k in low:
            return v
    return "us"


def _doc_due(key: str, clocks: dict) -> tuple[Optional[date], str]:
    """When each paper has to exist. Before the goods fly, the papers that travel with them must be ready."""
    etd, iwd = clocks["etd"], clocks["in_warehouse"]
    if key in ("invoice", "packing_list"):
        return etd, "needed on the day the goods move (ETD)"
    if key in ("fcr", "awb", "bl"):
        return etd, "the carrier issues it when the goods are handed over (ETD)"
    if key in ("certificate_of_origin", "inspection_certificate", "fumigation", "test_report", "insurance"):
        return _shift(etd, -3), "must be in hand 3 days before ETD"
    return etd, "the contract names it but not its date — treated as needed at ETD"


def documents(contract: dict, clocks: dict, ticks: dict) -> list[dict]:
    """Every paper the contract obliges, with its due date, who produces it, and whether it has been handed over."""
    out: list[dict] = []
    for key, label in _split_docs(contract.get("documents_list") or ""):
        due, basis = _doc_due(key, clocks)
        tick = ticks.get(key) or {}
        out.append(_row(key, label, due, basis=basis, kind="document",
                        extra={"owner": _doc_owner(label), "given_on": tick.get("on") or "",
                               "given_by": tick.get("by") or "", "note": tick.get("note") or "",
                               "ticked": bool(tick.get("on")), "id": key}))
    # the contract's own clause set, and the LC when there is one, are paper obligations too
    for extra_row in _clause_docs(contract, clocks, ticks):
        out.append(extra_row)
    return out


def _clause_docs(contract: dict, clocks: dict, ticks: dict) -> list[dict]:
    """Papers the *terms* imply even when ``documents_list`` is short: a claim window, a signed contract copy back."""
    out = []
    if contract.get("_signed") or _d(contract.get("company_signed_on")) or _d(contract.get("buyer_signed_on")):
        key = "_contract_copy"
        t = ticks.get(key) or {}
        anchor = _d(contract.get("buyer_signed_on")) or _d(contract.get("company_signed_on")) or _d(contract.get("contract_date"))
        out.append(_row(key, "Signed contract copy back to the buyer", _shift(anchor, 2),
                        basis="2 days after the signing date", kind="document",
                        extra={"owner": "us", "given_on": t.get("on") or "", "given_by": t.get("by") or "",
                               "note": t.get("note") or "", "ticked": bool(t.get("on")), "id": key}))
    if contract.get("payment_terms_template") or "lc" in (contract.get("payment_basis") or "").lower():
        key = "_lc_presentation"
        t = ticks.get(key) or {}
        out.append(_row(key, "Documents presented under the L/C", _shift(clocks["etd"], 7),
                        basis="within 7 days of ETD (typical L/C presentation window)", kind="document",
                        extra={"owner": "us", "given_on": t.get("on") or "", "given_by": t.get("by") or "",
                               "note": t.get("note") or "", "ticked": bool(t.get("on")), "id": key}))
    return out


# ───────────────────────── the schedule ─────────────────────────

def schedule(contract: dict, clocks: dict, signed_on: Optional[date]) -> list[dict]:
    """The forward plan from the contract's own terms: factory → ETD → ETA → warehouse → payment."""
    out = [
        _row("ex_factory", "Ex-factory (goods packed and ready)", clocks["ex_factory"],
             basis="latest line on the contract"),
        _row("etd", "ETD — leaves origin", clocks["etd"],
             basis=f"ex-factory + {clocks['gap']} day(s)" if clocks["gap"] else "on the contract"),
        _row("eta", "ETA — arrives at destination", clocks["eta"],
             basis=f"ETD + {clocks['transit']} transit day(s)" if clocks["transit"] else "arrival not on the contract"),
        _row("in_warehouse", "In the buyer's warehouse", clocks["in_warehouse"],
             basis="latest line on the contract"),
    ]
    due, why = _payment_due(clocks, signed_on)
    out.append(_row("payment_due", "Payment due", due, basis=why, kind="money"))
    if signed_on:
        out.append(_row("signed", "Contract signed", signed_on, basis="the ERP's own signing date", kind="milestone"))
    return out


# ───────────────────────── the shipment, as the ERP holds it ─────────────────────────

#: The shipment fields the tower reads and may write. Kept to one list so a typo cannot silently drop a field.
SHIPMENT_FIELDS = [
    "name", "status", "apparel_ship_status", "carrier", "awb_number", "tracking_url", "tracking_status",
    "tracking_status_info", "apparel_forwarder", "apparel_booking_no", "apparel_booking_date",
    "apparel_service_type", "apparel_pol", "apparel_pod", "apparel_final_destination", "apparel_vessel_voyage",
    "apparel_cutoff", "apparel_etd", "apparel_eta", "apparel_on_board_date", "apparel_arrival_date",
    "apparel_delivery_date", "apparel_bl_type", "apparel_hbl_no", "apparel_mbl_no", "apparel_mode",
    "apparel_declared_gross_kg", "apparel_carrier_gross_kg", "apparel_declared_cbm", "apparel_carrier_cbm",
    "apparel_containers", "apparel_documents", "apparel_contracts", "value_of_goods", "pickup_date",
    "apparel_freight_terms", "apparel_air_cost_borne_by", "apparel_chargeable_kg",
]
WRITABLE_SHIPMENT = ["carrier", "awb_number", "tracking_url", "tracking_status", "tracking_status_info",
                     "apparel_forwarder", "apparel_booking_no", "apparel_booking_date", "apparel_service_type",
                     "apparel_vessel_voyage", "apparel_cutoff", "apparel_etd", "apparel_eta",
                     "apparel_on_board_date", "apparel_arrival_date", "apparel_delivery_date",
                     "apparel_bl_type", "apparel_hbl_no", "apparel_mbl_no", "apparel_gross_kg_label"]


def shipments_for(be, contract_name: str, order_name: str = "", limit: int = 40) -> list[dict]:
    """The ERP's Shipment rows that belong to this contract.

    The Shipment keeps its contracts in a free-text field (``apparel_contracts``), so the search is a text match on
    the contract name — the only reliable link this ERP offers. When it has a Delivery Note, that note carries the
    Sales Order, which is checked as a second path so a shipment recorded without the contract name is still found.
    """
    rows: list[dict] = []
    try:
        if contract_name:
            rows = be.get_list("Shipment", [["apparel_contracts", "like", f"%{contract_name}%"]],
                               SHIPMENT_FIELDS, limit=limit) or []
    except Exception:
        rows = []
    if not rows:
        try:                                    # fallback: the order's delivery notes → shipments
            dns = be.get_list("Delivery Note", [["sales_order", "=", order_name]] if order_name else None,
                              ["name"], limit=20) if order_name else []
            for dn in dns or []:
                for s in be.get_list("Shipment", None, SHIPMENT_FIELDS, limit=200) or []:
                    if any((r or {}).get("delivery_note") == dn["name"] for r in (s.get("shipment_delivery_note") or [])):
                        rows.append(s)
        except Exception:
            pass
    # de-duplicate by name, newest first
    seen, out = set(), []
    for r in sorted(rows, key=lambda x: str(x.get("name")), reverse=True):
        if r.get("name") in seen:
            continue
        seen.add(r.get("name"))
        out.append(r)
    return out


def shipment_view(row: dict) -> dict:
    """One Shipment as the tracking card shows it: the facts, grouped so the eye can find them."""
    return {
        "name": row.get("name") or "",
        "status": row.get("status") or "",
        "ship_status": row.get("apparel_ship_status") or "",
        "mode": row.get("apparel_mode") or "",
        "forwarder": row.get("apparel_forwarder") or "",
        "booking_no": row.get("apparel_booking_no") or "",
        "booking_date": str(row.get("apparel_booking_date") or "")[:10],
        "service_type": row.get("apparel_service_type") or "",
        "pol": row.get("apparel_pol") or "", "pod": row.get("apparel_pod") or "",
        "destination": row.get("apparel_final_destination") or "",
        "vessel_voyage": row.get("apparel_vessel_voyage") or "",
        "cutoff": str(row.get("apparel_cutoff") or "")[:10],
        "etd": str(row.get("apparel_etd") or "")[:10], "eta": str(row.get("apparel_eta") or "")[:10],
        "on_board": str(row.get("apparel_on_board_date") or "")[:10],
        "arrival": str(row.get("apparel_arrival_date") or "")[:10],
        "delivery": str(row.get("apparel_delivery_date") or "")[:10],
        "bl_type": row.get("apparel_bl_type") or "",
        "hbl": row.get("apparel_hbl_no") or "", "mbl": row.get("apparel_mbl_no") or "",
        "carrier": row.get("carrier") or "", "awb": row.get("awb_number") or "",
        "tracking_url": row.get("tracking_url") or "",
        "tracking_status": row.get("tracking_status") or "",
        "tracking_info": row.get("tracking_status_info") or "",
        "gross_kg": row.get("apparel_carrier_gross_kg") or row.get("apparel_declared_gross_kg") or "",
        "cbm": row.get("apparel_carrier_cbm") or row.get("apparel_declared_cbm") or "",
        "containers": [c.get("container_no") or c.get("name") for c in (row.get("apparel_containers") or []) if isinstance(c, dict)],
        "documents": [d.get("document_type") or d.get("name") for d in (row.get("apparel_documents") or []) if isinstance(d, dict)],
        "contracts": row.get("apparel_contracts") or "",
        "value": row.get("value_of_goods") or "",
    }


def shipment_alerts(view: dict, clocks: dict, mode: str, today: Optional[date] = None) -> list[dict]:
    """Where this shipment is not keeping up with the contract. Empty when it is on plan."""
    today = today or date.today()
    out: list[dict] = []
    is_air = "air" in (mode or "").lower() or "air" in (view.get("mode") or "").lower()
    etd = _d(view.get("etd")) or clocks["etd"]
    etd_k = _d(clocks["etd"])
    if etd_k and etd and etd > etd_k:
        out.append({"tone": "warn", "title": f"ETD pushed to {etd.isoformat()}",
                    "sub": f"the contract says {etd_k.isoformat()} — the buyer must agree this in writing, "
                           f"or it becomes a late shipment claim."})
    if not view.get("booking_no") and etd_k and (etd_k - today).days <= 21:
        out.append({"tone": "warn", "title": "No booking yet",
                    "sub": f"ETD is {etd_k.isoformat()} ({(etd_k - today).days} days). Book the space before the cut-off."})
    cutoff = _d(view.get("cutoff"))
    if cutoff:
        left = (cutoff - today).days
        if 0 <= left <= 3:
            out.append({"tone": "bad" if left <= 1 else "warn", "title": f"Cargo cut-off in {left} day(s)",
                        "sub": f"{cutoff.isoformat()} — the goods must be at the CFS by then."})
        elif left < 0 and not view.get("on_board"):
            out.append({"tone": "bad", "title": "Cut-off passed, nothing on board",
                        "sub": f"cut-off was {cutoff.isoformat()} and no on-board date is recorded — the shipment "
                               f"has almost certainly missed that flight/vessel."})
    if is_air and not view.get("awb"):
        out.append({"tone": "warn", "title": "No AWB number",
                    "sub": "an air shipment is only tracked by its AWB — ask the forwarder for it at handover."})
    if view.get("awb") and not view.get("tracking_url"):
        out.append({"tone": "info", "title": "AWB recorded without a tracking link",
                    "sub": f"{view.get('carrier') or 'the carrier'} — paste the tracking URL so anyone can follow it."})
    onb, arr = _d(view.get("on_board")), _d(view.get("arrival"))
    if etd_k and not onb and etd_k < today:
        out.append({"tone": "bad", "title": "ETD passed with no on-board date",
                    "sub": f"the contract ETD was {etd_k.isoformat()}. Either the goods flew and nobody recorded it, "
                           f"or we are late — check the forwarder."})
    eta_k = _d(view.get("eta")) or clocks["eta"]
    if eta_k and not arr and eta_k < today:
        out.append({"tone": "warn", "title": "ETA passed with no arrival date",
                    "sub": f"expected {eta_k.isoformat()} — confirm arrival with the forwarder, the payment clock starts there."})
    if not view.get("documents"):
        out.append({"tone": "info", "title": "No documents attached to the shipment",
                    "sub": "invoice, packing list and the carrier's document are recorded on the Shipment in the ERP."})
    return out


# ───────────────────────── the whole picture ─────────────────────────

def date_notes(contract: dict, clocks: dict, today: Optional[date] = None) -> list[dict]:
    """The contract's own dates, checked against each other.

    The header carries lead times and the lines carry dates, and nothing in the ERP forces the two to agree. A
    contract that says "ex-factory 8 Dec, +6 days to ETD" while also saying "ETD 8 Dec" is not a small mistake: it is
    the difference between shipping on time and a late-shipment claim, so it is named here.
    """
    today = today or date.today()
    out: list[dict] = []
    exf, etd, eta, iwd = clocks["ex_factory"], clocks["etd"], clocks["eta"], clocks["in_warehouse"]
    gap, transit = clocks["gap"], clocks["transit"]
    if exf and etd and gap:
        calc = _shift(exf, gap)
        if calc != etd:
            out.append({"tone": "warn", "title": "ETD and the lead time disagree",
                        "sub": f"ex-factory {exf.isoformat()} + {gap} day(s) is {calc.isoformat()}, but the line's ETD is "
                               f"{etd.isoformat()}. Set the ETD from the lead time, or correct the lead time."})
    if iwd and exf and iwd < exf:
        out.append({"tone": "bad", "title": "In-warehouse date is before ex-factory",
                    "sub": f"{iwd.isoformat()} cannot be earlier than {exf.isoformat()} — the goods do not exist yet."})
    if iwd and eta and iwd < eta:
        out.append({"tone": "bad", "title": "The goods arrive after they are in the warehouse",
                    "sub": f"ETA {eta.isoformat()} is later than the in-warehouse date {iwd.isoformat()}. Either the "
                           f"transit time ({transit} day(s)) is too long for this lane or the in-warehouse date is wrong."})
    items = clocks["items"]
    exfs = {_d(i.get("ex_factory_date")) for i in items if _d(i.get("ex_factory_date"))}
    if len(exfs) > 1:
        out.append({"tone": "info", "title": f"{len(exfs)} different ex-factory dates across the lines",
                    "sub": "the shipment is only ready as late as its last style — "
                           f"{max(exfs).isoformat()}. If it must go as one consignment, the earlier lines wait."})
    if exf and exf < today:
        out.append({"tone": "warn", "title": f"Ex-factory date was {exf.isoformat()}",
                    "sub": f"{(today - exf).days} day(s) ago. Confirm the goods are packed and the forwarder has them."})
    return out


def plan(deal, contract: dict, be=None, ticks: Optional[dict] = None, today: Optional[date] = None) -> dict:
    """Everything owed on this deal: the schedule, the papers, the shipments, the warnings and the trade term.

    ``be`` may be None (the ERP is down): the plan is still built from the contract's own terms, and every ERP fact
    is reported as unavailable rather than guessed.
    """
    today = today or date.today()
    ticks = ticks or {}
    clocks = _contract_clocks(contract or {})
    # "signed" is the ERP's own fact (a submitted contract), never just a signature date typed on a draft: a contract
    # that says "signed 7 Nov" while it is still a draft must not tell anyone it is signed.
    signed = bool((contract or {}).get("_signed")) or _i((contract or {}).get("docstatus")) == 1
    signed_on = ((_d((contract or {}).get("buyer_signed_on")) or _d((contract or {}).get("company_signed_on"))
                  or _d((contract or {}).get("contract_date"))) if signed else None)
    refs = deal.refs_dict() if hasattr(deal, "refs_dict") else {}
    contract_name = refs.get("sales_contract") or ""
    order_name = refs.get("sales_order") or ""
    rows: list[dict] = []
    erp_error = ""
    if be is not None:
        try:
            rows = shipments_for(be, contract_name, order_name)
        except Exception as e:                      # the plan survives an ERP hiccup
            erp_error = str(e)[:160]
    views = [shipment_view(r) for r in rows]
    docs = documents(contract or {}, clocks, ticks)
    sched = schedule(contract or {}, clocks, signed_on)
    term = TERMS.get((contract or {}).get("incoterm") or "")
    alerts = trade_term_notes(contract or {}, clocks) + date_notes(contract or {}, clocks, today)
    for v in views:
        alerts += shipment_alerts(v, clocks, (contract or {}).get("shipment_mode") or "")
    # a document that is late and not ticked is the loudest thing on the page
    for d in docs:
        if d["state"] == "late" and not d["ticked"]:
            alerts.insert(0, {"tone": "bad", "title": f"{d['label']} needed by {d['date']}",
                              "sub": f"{-d['days_left']} day(s) overdue and not marked as given. "
                                     f"{'The buyer cannot clear the goods without it.' if d['owner'] != 'us' else 'Issue it and mark it given.'}"})
    done = sum(1 for d in docs if d["ticked"])
    return {
        "ok": True,
        "contract": contract_name, "sales_order": order_name,
        "signed": signed,
        "schedule": sched,
        "documents": docs,
        "documents_done": done, "documents_total": len(docs),
        "shipments": views, "shipment": (views[0] if views else {}),
        "alerts": alerts,
        "incoterm": term or {},
        "incoterm_code": (contract or {}).get("incoterm") or "",
        "incoterm_help": INCOTERMS,
        "mode": (contract or {}).get("shipment_mode") or "",
        "erp_error": erp_error,
        "today": today.isoformat(),
    }


def trade_term_notes(contract: dict, clocks: dict) -> list[dict]:
    """A trade term that contradicts the contract's own freight/insurance/mode lines is refused by nobody but the
    forwarder or the buyer — months later. So it is named here, in words that say what happens."""
    out: list[dict] = []
    code = (contract.get("incoterm") or "").upper()
    term = TERMS.get(code)
    mode = (contract.get("shipment_mode") or "").lower()
    freight = (contract.get("freight_by") or "").strip()
    insurance = (contract.get("insurance_by") or "").strip()
    place = (contract.get("named_place") or "").strip()
    if not code:
        out.append({"tone": "bad", "title": "No Incoterm on the contract",
                    "sub": "the ERP needs one of the eleven trade terms — it decides who pays freight, insurance and duty."})
        return out
    if not term:
        out.append({"tone": "bad", "title": f'Incoterm "{code}" is not one of the eleven',
                    "sub": "pick from the ERP's own Incoterm list."})
        return out
    if not place:
        out.append({"tone": "bad", "title": f"{code} needs a named place",
                    "sub": f"{term['meaning']} The named place is what the term points at."})
    if "air" in mode and code in SEA_ONLY:
        out.append({"tone": "bad", "title": f"{code} is a sea term on an air shipment",
                    "sub": f"{code} means handing over to a vessel. The mode-neutral term for air is FCA (buyer's "
                           f"freight) or CPT/CIP (our freight) — DAP/DDP also work for air."})
    if freight and term["freight"] != freight:
        out.append({"tone": "warn", "title": f"{code} says freight is {term['freight'].lower()}, the contract says {freight.lower()}",
                    "sub": f"if the buyer pays the freight, {code} is the wrong term — the forwarder will bill the "
                           f"wrong party."})
    if not insurance:
        out.append({"tone": "warn", "title": "Insurance party left blank",
                    "sub": f"{code} puts insurance with the {term['insurance'].lower()}. Say who actually insures — "
                           f"an uninsured claim on a {code} shipment is ours to absorb."})
    elif term["insurance"] != insurance:
        out.append({"tone": "warn", "title": f"{code} puts insurance with the {term['insurance'].lower()}, the contract says {insurance.lower()}",
                    "sub": "this is allowed if the buyer agrees it in writing, otherwise fix the term or the line."})
    if code in ("DAP", "DPU", "DDP") and not clocks["transit"]:
        out.append({"tone": "warn", "title": f"{code} has no transit time on the contract",
                    "sub": "we promise delivery to the door, so the delivery date needs the transit days to be real."})
    if not _i(contract.get("production_lead_days")):
        out.append({"tone": "info", "title": "Production lead time is 0 days",
                    "sub": "accepting an order with no lead time is how an ex-factory date becomes impossible."})
    return out


def tick_key(deal_id) -> str:
    return f"shipdocs:{int(deal_id or 0)}"


def load_ticks(db, deal_id) -> dict:
    from models import KVModel
    r = db.query(KVModel).filter(KVModel.key == tick_key(deal_id)).first()
    if not r or not r.value:
        return {}
    try:
        return json.loads(r.value)
    except (ValueError, TypeError):
        return {}


def save_ticks(db, deal_id, ticks: dict) -> None:
    from models import KVModel
    r = db.query(KVModel).filter(KVModel.key == tick_key(deal_id)).first()
    val = json.dumps(ticks, default=str)
    if r:
        r.value = val
    else:
        db.add(KVModel(key=tick_key(deal_id), value=val))
    db.commit()
