import { API_BASE, API_HEALTH, PROJECT, USER_ID, AGENT_ID, DEPLOYMENT_ID, SWARM_ID, ORIGIN_ID } from "../config";

let _jwt: string | null = null;
let _resolveJwtReady: (() => void) | null = null;
const _jwtReady: Promise<void> = new Promise((resolve) => { _resolveJwtReady = resolve; });
if (typeof window !== "undefined") {
  window.addEventListener("message", (event) => {
    if (event.data?.type === "KOGO_AUTH" && event.data?.jwt) {
      _jwt = event.data.jwt;
      _resolveJwtReady?.();
    }
  });
  setTimeout(() => _resolveJwtReady?.(), 4000);
}

export function getJwt(): string | null { return _jwt; }
async function ensureJwt(): Promise<void> { if (!_jwt) await _jwtReady; }

export interface ApiResponse {
  success: boolean;
  project: string | null;
  function_called: string | null;
  data: any;
  message: string | null;
  diagnosis: any | null;
}

/* Outside KOGO the person signs in with a password; the app session token rides along on every call. */
function _withToken(params: Record<string, any>): Record<string, any> {
  try {
    const t = localStorage.getItem("cx_token");
    return t ? { ...params, _app_token: t } : params;
  } catch { return params; }
}

export async function callApi(functionName: string, params: Record<string, any> = {}): Promise<ApiResponse> {
  await ensureJwt();
  const response = await fetch(API_BASE, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${_jwt ?? "null"}`,
    },
    body: JSON.stringify({ project: PROJECT, function: functionName, params: _withToken(params), agentId: AGENT_ID, deploymentId: DEPLOYMENT_ID, swarmId: SWARM_ID, originId: ORIGIN_ID }),
    signal: AbortSignal.timeout(30000),
  });
  if (!response.ok) throw new Error(`API error: ${response.status}`);
  return response.json();
}

// ── One resilient call path (2026-11-04) ────────────────────────────────────
// The middleware used to snapshot the callable list at PUBLISH time, so every function
// added after a publish was reached through `get_dashboard` with a `bridge_action` param.
// That produced a hand-maintained bridge Set that drifted twice (a page called four
// functions that were not in it and came up empty, 2026-11-03).
//
// The allowlist is derived live from `backend/document.md` on this platform, so the
// bridge should not be needed at all — and rather than assert either way, this resolves
// it at runtime: call the function **directly**, and only if the platform says it does
// not exist fall back to `get_dashboard(bridge_action=…)`, once. The answer is remembered
// for the session, so the cost is one extra call per function, not one per request.
//
// Nothing here is a hardcoded list any more: no new function has to be registered twice.
const _direct = new Map<string, boolean>();

function _isUnknownFunction(res: any): boolean {
  if (!res) return true;
  if (res.success === false) return true;
  const msg = String(res.message || res.data?.error || "").toLowerCase();
  return msg.includes("not found") || msg.includes("unknown function") || msg.includes("not allowed");
}

async function callResilient(name: string, params: Record<string, any> = {},
                              bridgeParam: "inbox_action" | "bridge_action" = "bridge_action"): Promise<ApiResponse> {
  const mode = _direct.get(name);
  if (mode === true) return callApi(name, params);
  if (mode === false) return callApi("get_dashboard", { [bridgeParam]: name, ...params });

  try {
    const res = await callApi(name, params);
    if (!_isUnknownFunction(res)) {
      _direct.set(name, true);
      return res;
    }
    const bridged = await callApi("get_dashboard", { [bridgeParam]: name, ...params });
    if (!_isUnknownFunction(bridged)) {
      _direct.set(name, false);
      return bridged;
    }
    _direct.set(name, true);          // report the direct failure honestly
    return res;
  } catch (err) {
    const bridged = await callApi("get_dashboard", { [bridgeParam]: name, ...params });
    _direct.set(name, false);
    return bridged;
  }
}

export function callInbox(name: string, params: Record<string, any> = {}): Promise<ApiResponse> {
  return callResilient(name, params, "inbox_action");
}

export function callBridge(name: string, params: Record<string, any> = {}): Promise<ApiResponse> {
  return callResilient(name, params, "bridge_action");
}

export async function checkApiHealth(): Promise<boolean> {
  try {
    await ensureJwt();
    const r = await fetch(`${API_HEALTH}?userId=${USER_ID}&originId=${ORIGIN_ID}&project=${PROJECT}`, {
      signal: AbortSignal.timeout(5000),
      headers: { "Authorization": `Bearer ${_jwt ?? "null"}` },
    });
    if (!r.ok) return false;
    const data = await r.json();
    return Array.isArray(data.projects) && data.projects.includes(PROJECT);
  } catch { return false; }
}

// ═══════════════════════════════════════════════════════════════════════════
// CHAT MODULE — API additions
// ═══════════════════════════════════════════════════════════════════════════

export interface ChatConfig {
  api_path: string;
  chat_api_path: string;
  user_id: string;
  deployment_id: string;
  swarm_id: string | null;
  agent_id: string;
  token: string;
  agent_name: string;
  agent_icon: string;
}

const ANNOTATION_TAGS = ["starttime", "endtime", "icon", "loader", "summary", "file"];

export function cleanBoatReply(raw: string): string {
  if (!raw) return "";
  let text = raw;
  for (const tag of ANNOTATION_TAGS) {
    text = text.replace(new RegExp(`<${tag}\\b[^>]*>.*?</${tag}>`, "gs"), "");
    text = text.replace(new RegExp(`<${tag}\\b[^>]*>`, "g"), "");
  }
  // Strip the agent's private reasoning — it must NEVER reach the UI (matches the
  // backend clean_boat_reply). 1) paired block; 2) unterminated tail; 3) orphan tags.
  text = text.replace(/<(think|thinking|reasoning)\b[^>]*>.*?<\/\1>/gis, "");
  text = text.replace(/<(think|thinking|reasoning)\b[\s\S]*$/i, "");
  text = text.replace(/<\/?(think|thinking|reasoning)\b[^>]*>/gi, "");
  text = text.replace(/\d{13}/g, "");
  text = text.replace(/fa-(?:regular|solid) fa-[\w-]+/g, "");
  text = text.replace(/\n{3,}/g, "\n\n");
  return text.trim();
}

// FIXED CONTRACT — cardContent is the agent's object shape:
//   { card_data: [ { card_content: { item_info: {...} } } ], file_datas: [...] }
// It is passed through verbatim to onFinal; the component maps it via mapCardContent().
export interface CardContent {
  card_data?: Array<{ card_content?: { item_info?: any } }>;
  file_datas?: any[];
}

export interface SSECallbacks {
  onChunk: (text: string, fullReply: string, repliedAgent: any) => void;
  onFinal: (fullReply: string, repliedAgent: any, cardContent?: CardContent | null) => void;
  onThreadId: (threadId: string) => void;
  onError: (error: string) => void;
}

export async function streamMessage(config: ChatConfig, message: string, threadId: string | null, callbacks: SSECallbacks): Promise<void> {
  // Fail loud — never fetch a hostless URL or POST an empty deployment_id.
  if (!config?.chat_api_path) { callbacks.onError("chat module not configured: missing CHAT_API_PATH"); return; }
  if (!config.deployment_id && !config.swarm_id) { callbacks.onError("chat module not configured: missing DEPLOYMENT_ID and SWARM_ID"); return; }

  const payload = {
    sender: config.user_id, guest_sender: null, guest_name: null,
    thread_id: threadId || null, message,
    deployment_id: config.deployment_id, swarm_id: config.swarm_id,
  };

  let fullReply = "";
  let repliedAgent: any = null;
  let finalCalled = false;

  try {
    // FIXED CONTRACT: endpoint path "deployment_stream_kogo_os_stream" — verbatim.
    const response = await fetch(`${config.chat_api_path}/deployment_stream_kogo_os_stream`, {
      method: "POST",
      headers: { Authorization: config.token, "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) { callbacks.onError(`API error: ${response.status}`); return; }

    const reader = response.body?.getReader();
    if (!reader) { callbacks.onError("No response stream"); return; }

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data:")) continue;
        try {
          const parsed = JSON.parse(trimmed.slice(5).trim());
          const data = parsed.data || {};
          if (data.created_thread_id) callbacks.onThreadId(data.created_thread_id);
          if (data.repliedAgent) repliedAgent = data.repliedAgent;
          if (parsed.type === "streaming" && data.boatReply) {
            fullReply += data.boatReply;
            callbacks.onChunk(data.boatReply, cleanBoatReply(fullReply), repliedAgent);
          } else if (parsed.type === "final") {
            if (data.boatReply) fullReply = data.boatReply;
            finalCalled = true;
            callbacks.onFinal(cleanBoatReply(fullReply), repliedAgent, data.cardContent || null);
          }
        } catch { /* skip unparseable */ }
      }
    }

    if (!finalCalled) callbacks.onFinal(cleanBoatReply(fullReply), repliedAgent, null);
  } catch (err: any) {
    callbacks.onError(err.message || "Connection lost");
  }
}
