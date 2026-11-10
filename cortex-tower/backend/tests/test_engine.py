"""Regression / guardrail tests for the Cortex Control Tower engine.

Dependency-free: run with ``python3 tests/test_engine.py`` from the ``backend``
directory (exit code 0 = all pass). Pairs with ``test_email_engine.py`` but
covers the *engine* layers: config discipline, the rulebook severity maths and
config-driven thresholds, the forecast helpers, and the Ask-KOGO LLM plumbing
(prompt cleaning + grounding tokens + retrieval routing).

Added 2026-10-05 during the appster Edit-Flow cleanup. These are pure-function
checks — they make NO network calls and never touch the live ERP.
"""

import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

import re                # noqa: E402
import config            # noqa: E402
import rulebook          # noqa: E402
import forecast          # noqa: E402
import ai_nextsteps      # noqa: E402
import copilot           # noqa: E402
import writes            # noqa: E402
import functions         # noqa: E402

_FAILURES = []


def check(name, cond):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}")
        _FAILURES.append(name)


# ── 1. Config discipline (appster core-builder rule: only config.py reads env) ──
BUSINESS_MODULES = [
    "erp.py", "rulebook.py", "forecast.py", "monitor.py", "copilot.py",
    "ai_nextsteps.py", "writes.py", "email_engine.py", "mailer.py", "inbound.py",
    "models.py", "functions.py", "seed.py",
]
for mod in BUSINESS_MODULES:
    src = open(os.path.join(BACKEND, mod), encoding="utf-8").read()
    if mod == "functions.py":
        # Chat-module HARD RULE: the JWT is read from USER_JWT_TOKEN at RUNTIME
        # (never persisted, never read at import). So functions.py is the one
        # business module allowed to import os and read exactly that env var —
        # every os.environ read must be the runtime JWT, nothing else.
        env_reads = re.findall(r"os\.environ[.\[]", src)
        jwt_reads = re.findall(r'os\.environ\.get\("USER_JWT_TOKEN"', src)
        check("config discipline: functions.py imports os (chat runtime JWT)", "\nimport os\n" in src)
        check("config discipline: functions.py env reads are only USER_JWT_TOKEN",
              len(env_reads) == len(jwt_reads) == 2)
        continue
    check(f"config discipline: {mod} has no os.environ", "os.environ" not in src)
    check(f"config discipline: {mod} does not import os", "\nimport os\n" not in src)

check("config: ERP_WRITE_MODE is valid", config.ERP_WRITE_MODE in ("off", "safe", "draft", "all"))
check("config: DEFAULT_CURRENCY set", bool(config.DEFAULT_CURRENCY))
check("config: SELLING_PRICE_LIST set", bool(config.SELLING_PRICE_LIST))
check("config: SMTP_PORT is int", isinstance(config.SMTP_PORT, int))
check("config: ERP_APP_ID set", bool(config.ERP_APP_ID))


# ── 2. Rulebook severity maths ───────────────────────────────────────────────
check("sev_by_days crit", rulebook._sev_by_days(3, 7, 30) == "critical")
check("sev_by_days warn", rulebook._sev_by_days(10, 7, 30) == "warning")
check("sev_by_days info", rulebook._sev_by_days(90, 7, 30) == "info")
check("sev_by_days None", rulebook._sev_by_days(None, 7, 30) == "warning")
check("sev_by_pct crit", rulebook._sev_by_pct(60, 5, 50) == "critical")
check("sev_by_pct warn", rulebook._sev_by_pct(10, 5, 50) == "warning")
check("sev_by_pct info", rulebook._sev_by_pct(1, 5, 50) == "info")


# ── 3. Thresholds come from rulebook.json (single source of truth) ───────────
cfg = rulebook._cfg()
check("cfg: trim thresholds present", cfg["trim"]["unmapped_critical_at"] == 10
      and cfg["trim"]["mr_draft_critical_at"] == 10)
check("cfg: bom warning threshold present", cfg["bom"]["coverage_warning_below_pct"] == 100)
check("cfg: delivery warning threshold present", "overdue_warning_days" in cfg["delivery"])
check("cfg: payment outstanding threshold present", "outstanding_warning_usd" in cfg["payment"])
check("cfg: all sections merged", all(k in cfg for k in
      ("delivery", "bom", "fabric", "payment", "shipment", "production", "supplier", "trim", "limits")))


# ── 4. Trim severity is config-driven (not hardcoded n<10) ───────────────────
tr = rulebook._r_trim_unmapped({"trim_exceptions": [{}] * 5}, cfg)
check("trim unmapped: few -> warning", tr and tr[0]["severity"] == "warning")
tr = rulebook._r_trim_unmapped({"trim_exceptions": [{}] * 50}, cfg)
check("trim unmapped: many -> critical", tr and tr[0]["severity"] == "critical")

drafts = [{"docstatus": 0}] * 5
mrd = rulebook._r_trim_mr_draft({"material_requests": drafts}, cfg)
check("trim MR draft: few -> warning", mrd and mrd[0]["severity"] == "warning")
drafts = [{"docstatus": 0}] * 50
mrd = rulebook._r_trim_mr_draft({"material_requests": drafts}, cfg)
check("trim MR draft: many -> critical", mrd and mrd[0]["severity"] == "critical")


# ── 5. Forecast helpers ──────────────────────────────────────────────────────
check("forecast clamp hi", forecast._clamp(5, 0, 1) == 1)
check("forecast clamp lo", forecast._clamp(-1, 0, 1) == 0)
check("forecast clamp mid", forecast._clamp(0.5, 0, 1) == 0.5)
check("forecast margin ratios named", forecast.MARGIN_COST_MIN_RATIO == 0.02
      and forecast.MARGIN_COST_MAX_RATIO == 2.0)


# ── 6. Ask-KOGO LLM plumbing: reasoning stripped, UTF-8-safe, grounding ──────
raw = "<think><starttime>1234567890123</starttime>SECRET REASONING here</think>The answer is 25,612.00 USD"
clean = ai_nextsteps._clean(raw)
check("_clean drops reasoning content", "SECRET REASONING" not in clean)
check("_clean keeps the answer", "25,612.00" in clean)
check("_clean drops timestamps", "1234567890123" not in ai_nextsteps._clean(raw))
check("_clean empty is empty", ai_nextsteps._clean("") == "")
check("_clean handles em-dash (utf-8)", "—" in ai_nextsteps._clean("A — B"))

toks = ai_nextsteps._num_tokens("USD 25,612.00 across 5 orders, 7% short, ref 42")
check("_num_tokens keeps 3+ digits", "25612.00" in toks)
check("_num_tokens keeps percents", "7%" in toks)
check("_num_tokens drops small ints", "42" not in toks)


# ── 7. Copilot retrieval routing ─────────────────────────────────────────────
r = copilot._route_sections("who are my cloth suppliers?")
check("router: suppliers -> procurement", "procurement" in r)

r = copilot._route_sections("where do i get raw materials from?")
check("router: materials pulls procurement (deps)", "materials" in r and "procurement" in r)

r = copilot._route_sections("which invoices are overdue?")
check("router: invoices -> finance", "finance" in r)

r = copilot._route_sections("tell me a story")   # no keyword -> everything
check("router: no hit -> all sections", set(r) == set(copilot._BUILDERS.keys()))


# ── 8. Functions registry + dead-code guard ──────────────────────────────────
# ask_kogo's long-prompt path was RETIRED 2026-10-06 (replaced by the chat module).
check("registry: ask_kogo is a retired shim (no long prompt)",
      functions.ask_kogo(None).get("retired") is True)
check("registry: chat module registered", all(
    k in functions.FUNCTIONS for k in
    ("get_chat_config", "create_room", "send_message", "fetch_threads", "fetch_chat_history")))
check("registry: get_dashboard registered", "get_dashboard" in functions.FUNCTIONS)
check("registry: get_ai_next_steps registered", "get_ai_next_steps" in functions.FUNCTIONS)
_fn_src = open(os.path.join(BACKEND, "functions.py"), encoding="utf-8").read()
check("dead code: 'Da Nang sewing' removed", "Da Nang sewing" not in _fn_src)


# ── 8b. Chat-module reply cleaning (added 2026-10-06 during Phase 6 QA) ───────
# send_message must never leak the model's <think> reasoning to the user, and
# must keep UTF-8 (em-dash/emoji) intact through the SSE decode.
_cbr = functions.clean_boat_reply
check("chat clean: drops <think> reasoning", "SECRET" not in _cbr("<think>SECRET plan</think>Hello"))
check("chat clean: keeps the answer", "Hello" in _cbr("<think>SECRET</think>Hello"))
check("chat clean: drops unterminated <think", "SECRET" not in _cbr("<think>SECRET tail"))
check("chat clean: drops timestamps", "1234567890123" not in _cbr("x<starttime>1234567890123</starttime>y"))
check("chat clean: keeps em-dash and emoji (utf-8)",
      "—" in _cbr("A — B") and "\U0001f44d" in _cbr("A \U0001f44d B"))


# ── 9. Write-path slug coverage (rulebook engine <-> writes.py) ──────────────
# The generic rulebook emits action slugs; writes.py must key its builders under
# the SAME slug or Execute silently becomes a no-op. This exact bug bit us
# (reinspection_s84 vs reinspection_fabric).
check("write slugs: POLICY and BUILDERS mirror each other",
      set(writes.POLICY) == set(writes.BUILDERS))
check("write slugs: reinspection_fabric wired",
      "reinspection_fabric" in writes.POLICY and "reinspection_fabric" in writes.BUILDERS)
check("write slugs: stale reinspection_s84 gone", "reinspection_s84" not in writes.POLICY)

_rb_src = open(os.path.join(BACKEND, "rulebook.py"), encoding="utf-8").read()
_rule_slugs = set(re.findall(r'_act\("([a-z_]+)"', _rb_src))
_writable = _rule_slugs & set(writes.BUILDERS)
check("write slugs: rulebook -> writers resolve",
      _writable and all(s in writes.POLICY for s in _writable))
# every emitted slug must at least be classifiable (builders or advisory/email)
check("rulebook emits the generic reinspection slug", "reinspection_fabric" in _rule_slugs)


# ── report ───────────────────────────────────────────────────────────────────
print()
if _FAILURES:
    print(f"❌ {len(_FAILURES)} FAILED: {_FAILURES}")
    sys.exit(1)
print("✅ All engine regression tests passed.")
