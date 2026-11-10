# Agent spikes — answers (2026-11-09)

Source: the user, who works on the KOGO platform (Claude Code cannot see it). These replace the research agent's guesses.

| # | Question | Answer |
|---|---|---|
| 1 | Can a KOGO agent be scheduled to run? | **No.** There is no scheduler. The heartbeat is ours: tick on page open, a 60 s timer while a tab is open, ERP webhook, "Sync now" button, and the person chatting with the agent. The Agent screen must say "last agent run: N ago" and must never imply it runs unattended. |
| 2 | Can the KOGO agent use project functions as tools (Pattern A)? | **Yes.** Every function with a `### name` heading in `backend/document.md` is a tool. |
| 3 | Team Tasks / SWARM_ID | **Workspace only.** Without a workspace (SWARM_ID) the agent cannot create Team Tasks: `agent_kogo_task` returns a clean "needs a workspace" result and the proposal falls back to a Today item. |
| 4 | Agent tools (`_call_agent_tool`) | **Available.** Use them (OCR, web search) from backend functions; keep `tools_used.json` in sync; handle `tool_unavailable`. |
| 5 | Tenant model | **One ERP, one tenant per install.** No multi-tenant tables. |

Consequences for the build: the loop is `agent_tick`, a bounded, idempotent step that any trigger above may call (and two ticks in a row must be safe); there is no per-tenant isolation work; the agent is also driven by chat (Pattern A), where `document.md` tells it how to use the tools safely.
