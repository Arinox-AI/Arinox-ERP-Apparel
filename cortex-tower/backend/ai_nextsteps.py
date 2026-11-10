"""Cortex Control Tower — Phase 3: grounded AI next-step layer.

Turns each live risk into a **concrete, reasoned next-step plan** using an LLM
(reached through the KOGO agent stream — the same contract the chat module uses),
but with three guard-rails so it is trustworthy on real data:

1. **Grounded** — the model is given a closed *evidence pack* (the exact numbers
   the engine computed) and told to use only those.
2. **Validated** — every number the model returns is checked against the evidence
   pack; anything unsourced is recorded and the suggestion is flagged.
3. **Fallback + cache** — results are cached per risk (invalidated when the live
   evidence changes); if the model is unreachable or returns junk, the engine's
   deterministic action is used instead. Never blocks the dashboard.

Nothing here writes to the ERP.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Optional

import requests

import config
import rulebook

# ── LLM transport (KOGO agent stream) ───────────────────────────────────────
def _chat_api_path() -> str:
    p = config.CHAT_API_PATH or ""
    if not p:
        api = config.API_PATH or ""
        base = api[:-len("/gateway")] if api.endswith("/gateway") else api
        p = f"{base}/chatai" if base else ""
    return p


def _kv_get(db, key, default=None):
    from models import KVModel
    try:
        row = db.query(KVModel).filter(KVModel.key == key).first()
        return row.value if row else default
    except Exception:
        return default


def _kv_set(db, key, value):
    from models import KVModel
    try:
        row = db.query(KVModel).filter(KVModel.key == key).first()
        if row:
            row.value = value
        else:
            db.add(KVModel(key=key, value=value))
        db.commit()
    except Exception:
        db.rollback()


def _llm(db, message: str, timeout: int = 120) -> Optional[str]:
    """Send one message to the KOGO agent and return its reply text. Reuses a
    single thread so app-triggered generation doesn't spawn a thread per call."""
    path = _chat_api_path()
    jwt = config.USER_JWT_TOKEN
    if not path or not jwt:
        return None
    sender = config.USER_ID
    dep = config.DEPLOYMENT_ID
    swarm = config.SWARM_ID
    thread = _kv_get(db, "ai_thread_id")
    url = f"{path}/deployment_stream_kogo_os_stream"
    payload = {"sender": sender, "guest_sender": None, "guest_name": None,
               "thread_id": thread, "message": message,
               "deployment_id": dep, "kogo_swarm_id": swarm}
    try:
        r = requests.post(url, json=payload,
                          headers={"Authorization": jwt, "Content-Type": "application/json"},
                          stream=True, timeout=timeout)
        if r.status_code != 200:
            return None
        buf = ""
        reply = ""
        # NB: do NOT use decode_unicode=True — the stream sends UTF-8 with no
        # charset in the Content-Type, so requests would fall back to ISO-8859-1
        # and mangle every non-ASCII character ("â€”" instead of "—"). We decode
        # the raw bytes as UTF-8 ourselves.
        for chunk in r.iter_content(chunk_size=None):
            if not chunk:
                continue
            if isinstance(chunk, bytes):
                chunk = chunk.decode("utf-8", "replace")
            buf += chunk
            while "\n\n" in buf:
                event, buf = buf.split("\n\n", 1)
                for line in event.split("\n"):
                    if not line.startswith("data:"):
                        continue
                    try:
                        d = json.loads(line[5:].strip())
                    except Exception:
                        continue
                    inner = d.get("data", {}) or {}
                    if d.get("type") == "streaming" and inner.get("boatReply"):
                        reply += inner["boatReply"]
                    elif d.get("type") == "final":
                        if inner.get("boatReply"):
                            reply = inner["boatReply"]
                        if inner.get("created_thread_id"):
                            _kv_set(db, "ai_thread_id", inner["created_thread_id"])
        return _clean(reply)
    except Exception:
        return None


_TAG_RE = re.compile(r"<[^>]+>")
# The KOGO agent stream puts the model's private chain-of-thought inside a
# <think>...</think> block (with <starttime>/<endtime> stamps). That reasoning is
# NOT part of the answer and must never reach the UI. We drop the whole block.
_THINK_RE = re.compile(r"<(think|thinking|reasoning)\b[^>]*>.*?</\1\s*>", re.S | re.I)
_THINK_OPEN_RE = re.compile(r"<(?:think|thinking|reasoning)\b[^>]*>.*$", re.S | re.I)
_THINK_CLOSE_RE = re.compile(r"</(?:think|thinking|reasoning)\s*>", re.I)
_HEADING_RE = re.compile(r"^\s*(?:kogo\s+analysis|analysis|reasoning|thinking)\s*[:\-]?\s*\n", re.I)
# The stream also emits short progress lines while the model is working. They arrive inside the reply text, so a
# JSON answer can come back as `"item_code": "ST022",Hold tight… "material_type": ...` and stop parsing. They are
# never part of an answer, so they are removed before anything else looks at the text.
_PROGRESS_RE = re.compile(
    r"(?:hold\s+tight|hang\s+on|one\s+moment|just\s+a\s+(?:moment|second|sec)|give\s+me\s+a\s+(?:moment|second)|"
    r"please\s+wait|working\s+on\s+it|one\s+sec|almost\s+there|let\s+me\s+(?:read|check|look))\s*[…\.!]*",
    re.I)
# Shorter notes only count when they end in an ellipsis or a bang - otherwise a real word in a description would go.
_PROGRESS_SHORT_RE = re.compile(r"(?:on\s+it|got\s+it|reading|checking|looking|thinking|working|done|okay|ok)\s*(?:…|\.\.\.|!)",
                                re.I)
# The stream can also drop a note in the middle of a word, inside a value: "BUTTONCrunching…S (ART # B56-0213)". A real
# word is preceded by a space, so anything that is *glued* to what came before it and ends in an ellipsis is that note.
_PROGRESS_GLUED_RE = re.compile(r"(?<=[^\s\W])[A-Z][a-z]{3,14}(?:…|\.\.\.)")


def _clean(raw: str) -> str:
    if not raw:
        return ""
    txt = raw
    # 1) discard the private reasoning block(s) entirely — keep only the answer
    txt = _THINK_RE.sub("", txt)
    # 2) safety net: an unclosed reasoning block (truncated stream) -> drop to end
    txt = _THINK_OPEN_RE.sub("", txt)
    # 3) safety net: a stray closing tag -> keep only what follows the last one
    m = None
    for m in _THINK_CLOSE_RE.finditer(txt):
        pass
    if m:
        txt = txt[m.end():]
    # 4) generic tags / leaked stream artefacts / whitespace
    txt = _TAG_RE.sub("", txt)
    txt = _PROGRESS_RE.sub("", txt)                        # "Hold tight…" style progress notes inside the reply
    txt = _PROGRESS_SHORT_RE.sub("", txt)
    txt = _PROGRESS_GLUED_RE.sub("", txt)
    txt = re.sub(r"\d{13,}", "", txt)                       # stream/trace timestamps
    txt = re.sub(r"fa-(?:regular|solid) fa-[\w-]+", "", txt)  # leaked icon classes
    txt = _HEADING_RE.sub("", txt)                           # leading "KOGO analysis" label
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    txt = re.sub(r"[ \t]{2,}", " ", txt)
    return txt.strip()


def _num(v, default=0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


# ── evidence pack (the ONLY facts the model may use) ────────────────────────
def evidence_pack(risk: dict, facts: dict) -> dict:
    """A compact, closed set of live facts for one risk."""
    r = dict(risk)
    r.pop("extra", None)
    pack = {
        "risk_key": r.get("key") or r.get("risk_key"),
        "risk_type": r.get("risk_type"),
        "severity": r.get("severity"),
        "finding": r.get("title"),
        "record": r.get("record"),
        "detail": {k: v for k, v in r.items()
                   if k not in ("key", "risk_key", "extra", "status") and v not in (None, "", [])},
        "context": {
            "open_orders": len(facts.get("open_sos", [])),
            "total_orders": len(facts.get("sos", [])),
            "styles_in_demand": len(facts.get("so_styles", {})),
            "boms": len(facts.get("boms", [])),
            "migration_gaps_open": len([g for g in facts.get("mdg", [])
                                        if (g.get("status") or "").lower() != "resolved"]),
            # real reference data so cross-references (e.g. a sibling invoice) stay sourced
            "outstanding_invoices": [i.get("name") for i in facts.get("invoices", [])
                                     if _num(i.get("outstanding_amount")) > 0],
            "deposit_note": "figures above are the only facts; do not derive new totals",
        },
    }
    return pack


def _evidence_text(pack: dict) -> str:
    return json.dumps(pack, ensure_ascii=False, default=str).lower().replace(",", "")


def _num_tokens(text: str) -> list:
    """Numbers that carry real information (>=3 digits, or a percentage)."""
    out = []
    for m in re.finditer(r"\d[\d,]*\.?\d*\s?%?", str(text)):
        tok = m.group(0).replace(",", "").strip().rstrip(".")
        digits = tok.replace("%", "").replace(".", "")
        if len(digits) >= 3 or tok.endswith("%"):
            out.append(tok)
    return out


def _validate(item: dict, evidence: str) -> tuple:
    """Every meaningful number in the NARRATIVE must appear in the evidence pack.

    Numeric-only fields (``confidence``) and structural fields (``owner``,
    ``priority``, ``risk_key``, ``action`` labels) are not factual claims and are
    excluded — only the reasoning / why / impact / watch-out prose is checked.
    """
    parts = [item.get("reasoning") or "", item.get("predicted_impact") or "",
             item.get("watch_outs") or ""]
    for a in (item.get("actions") or []):
        if isinstance(a, dict):
            parts.append(str(a.get("action") or ""))
            parts.append(str(a.get("why") or ""))
    text = " ".join(parts)
    unsourced = [t for t in _num_tokens(text) if t and t not in evidence]
    seen = set()
    unsourced = [u for u in unsourced if not (u in seen or seen.add(u))]
    return (len(unsourced) == 0), unsourced


# ── prompt ──────────────────────────────────────────────────────────────────
_SYS = (
    "You are the Cortex Operations Advisor for an apparel manufacturer. "
    "You reason ONLY from the FACTS supplied — never invent numbers, dates, names or orders. "
    "Every number you output must already appear in the FACTS. Do NOT compute new totals, "
    "sums, averages or deltas — cite only the figures present in FACTS. "
    "Output STRICT JSON only (no markdown, no prose outside JSON)."
)
_SCHEMA = (
    '{"summary": string, "items": [ {"risk_key": string, "reasoning": string, '
    '"actions": [ {"action": string, "why": string, "owner": string, '
    '"priority": "high"|"medium"|"low", "confidence": number} ], '
    '"predicted_impact": string, "watch_outs": string } ]}'
)


def _build_prompt(packs: list) -> str:
    return (
        _SYS
        + "\n\nFACTS (one evidence pack per risk):\n"
        + json.dumps(packs, ensure_ascii=False, default=str, indent=1)
        + "\n\nTASK: For EACH risk above, give a short reasoning and 1-3 concrete, "
          "specific next actions (with owner team, priority and a 0-1 confidence), "
          "plus the predicted impact and what to watch out for. Keep it operational and "
          "do not restate the whole fact sheet.\n"
        + "\nOUTPUT JSON schema:\n" + _SCHEMA
    )


def _parse_json(text: str) -> Optional[dict]:
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    # first {...} block
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(t[start:end + 1])
    except Exception:
        return None


# ── public API ──────────────────────────────────────────────────────────────
def _fallback(risk: dict) -> dict:
    extra = risk.get("extra") or {}
    return {
        "risk_key": risk.get("key") or risk.get("risk_key"),
        "reasoning": risk.get("title"),
        "actions": ([{"action": extra.get("action"), "why": extra.get("expected_impact"),
                      "owner": extra.get("responsible_team"), "priority": extra.get("priority", "medium"),
                      "confidence": None}] if extra else []),
        "predicted_impact": extra.get("expected_impact"),
        "watch_outs": "",
        "source": "fallback",
        "grounded": True,
        "unsourced": [],
    }


def generate(db, risk_keys: Optional[list] = None, limit: int = 8, refresh: bool = False) -> dict:
    """Generate (and cache) grounded AI suggestions for the top risks.

    ``risk_keys`` — target specific risks; else the ``limit`` most severe.
    """
    facts = rulebook.live_facts()
    risks = rulebook.build_risks()
    rank = {"critical": 0, "warning": 1, "info": 2}
    risks.sort(key=lambda r: rank.get(r.get("severity"), 9))

    if risk_keys:
        targets = [r for r in risks if (r.get("key") or r.get("risk_key")) in set(risk_keys)]
    else:
        targets = risks[:max(0, int(limit))]

    from models import AISuggestionModel
    results = {}
    to_generate = []
    for r in targets:
        rk = r.get("key") or r.get("risk_key")
        pack = evidence_pack(r, facts)
        h = hashlib.sha1(_evidence_text(pack).encode()).hexdigest()[:16]
        row = db.query(AISuggestionModel).filter(AISuggestionModel.risk_key == rk).first()
        if row and not refresh and row.evidence_hash == h:
            results[rk] = row.to_dict()
        else:
            to_generate.append((r, pack, h))

    if to_generate:
        packs = [p for _, p, _ in to_generate]
        reply = _llm(db, _build_prompt(packs)) if packs else None
        parsed = _parse_json(reply) if reply else None
        items = {}
        if parsed and isinstance(parsed.get("items"), list):
            for it in parsed["items"]:
                if isinstance(it, dict) and it.get("risk_key"):
                    items[it["risk_key"]] = it
        summary = (parsed or {}).get("summary") if parsed else None

        for r, pack, h in to_generate:
            rk = r.get("key") or r.get("risk_key")
            it = items.get(rk)
            if it:
                ok, unsourced = _validate(it, _evidence_text(pack))
                suggestion = {
                    "risk_key": rk,
                    "reasoning": it.get("reasoning") or r.get("title"),
                    "actions": it.get("actions") or [],
                    "predicted_impact": it.get("predicted_impact"),
                    "watch_outs": it.get("watch_outs"),
                    "summary": summary,
                    "source": "ai",
                    "grounded": ok,
                    "unsourced": unsourced,
                }
            else:
                suggestion = _fallback(r)
                suggestion["summary"] = summary

            row = db.query(AISuggestionModel).filter(AISuggestionModel.risk_key == rk).first()
            if not row:
                row = AISuggestionModel(risk_key=rk)
                db.add(row)
            row.evidence_hash = h
            row.payload = json.dumps(suggestion, ensure_ascii=False, default=str)
            row.grounded = 1 if suggestion.get("grounded") else 0
            row.unsourced = json.dumps(suggestion.get("unsourced") or [])
            row.source = suggestion.get("source") or "ai"
            row.note = "grounded" if suggestion.get("grounded") else "contains unsourced numbers"
            db.commit()
            results[rk] = suggestion

    return {"suggestions": list(results.values()),
            "count": len(results),
            "ai_available": _chat_api_path() != "",
            "generated_for": [r for r in (risk_keys or [])] or "top-%d" % limit}


def cached(db, risk_keys: Optional[list] = None) -> dict:
    """Return cached suggestions only (never calls the model)."""
    from models import AISuggestionModel
    q = db.query(AISuggestionModel)
    if risk_keys:
        q = q.filter(AISuggestionModel.risk_key.in_(list(risk_keys)))
    return {row.risk_key: row.to_dict() for row in q.all()}


def attach_to_dashboard(db, risks: list) -> None:
    """Attach any CACHED AI suggestion onto each risk (mutates in place). No LLM call."""
    try:
        cache = cached(db)
    except Exception:
        return
    for r in risks or []:
        rk = r.get("risk_key") or r.get("key")
        if rk in cache:
            r["ai"] = cache[rk]
