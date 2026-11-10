// MANDATORY api service (core-builder template). This is the ONLY place the app
// performs network I/O. Every request goes to the KOGO middleware at API_BASE —
// there is no other URL, ever.
import { API_BASE, API_HEALTH, PROJECT, USER_ID, AGENT_ID, DEPLOYMENT_ID, SWARM_ID, ORIGIN_ID } from "../config";

let _jwt: string | null = null;
// _jwtReady resolves as soon as the parent posts the JWT (or after a short timeout).
// The FIRST api call awaits it — WITHOUT this, the call fires on mount BEFORE the
// KOGO_AUTH postMessage arrives, the middleware falls back to a default user, and the
// project is looked up in the WRONG workspace → "Project 'x' not found. Available: []".
let _resolveJwtReady: (() => void) | null = null;
const _jwtReady: Promise<void> = new Promise((resolve) => { _resolveJwtReady = resolve; });
if (typeof window !== "undefined") {
  window.addEventListener("message", (event) => {
    if (event.data?.type === "KOGO_AUTH" && event.data?.jwt) {
      _jwt = event.data.jwt;
      _resolveJwtReady?.();
    }
  });
  // Safety net: never block longer than 4s waiting for the token.
  setTimeout(() => _resolveJwtReady?.(), 4000);
}

export function getJwt(): string | null { return _jwt; }
// Await before the first authenticated request so the JWT (→ correct user) is present.
async function ensureJwt(): Promise<void> { if (!_jwt) await _jwtReady; }

export interface ApiResponse {
  success: boolean;
  project: string | null;
  function_called: string | null;
  data: any;
  message: string | null;
  diagnosis: any | null;
}

export async function callApi(functionName: string, params: Record<string, any> = {}): Promise<ApiResponse> {
  await ensureJwt();  // wait for the JWT so the very first call hits the correct user's workspace
  const response = await fetch(API_BASE, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${_jwt ?? "null"}`,
    },
    // Send all 3 identity ids VERBATIM — middleware injects them into the backend env as-is.
    body: JSON.stringify({ project: PROJECT, function: functionName, params, agentId: AGENT_ID, deploymentId: DEPLOYMENT_ID, swarmId: SWARM_ID, originId: ORIGIN_ID }),
    signal: AbortSignal.timeout(30000),
  });
  if (!response.ok) throw new Error(`API error: ${response.status}`);
  return response.json();
}

export async function callApiWithFile(functionName: string, file: File, params: Record<string, any> = {}): Promise<ApiResponse> {
  await ensureJwt();
  const formData = new FormData();
  formData.append("file", file);
  formData.append("project", PROJECT);
  formData.append("function", functionName);
  formData.append("params", JSON.stringify(params));
  formData.append("agentId", AGENT_ID);
  formData.append("deploymentId", DEPLOYMENT_ID);
  formData.append("swarmId", SWARM_ID);
  formData.append("originId", ORIGIN_ID);
  const response = await fetch(API_BASE, {
    method: "POST",
    headers: { "Authorization": `Bearer ${_jwt ?? "null"}` },
    body: formData,
    signal: AbortSignal.timeout(120000),
  });
  if (!response.ok) throw new Error(`API error: ${response.status}`);
  return response.json();
}

export async function checkApiHealth(): Promise<boolean> {
  try {
    await ensureJwt();
    // Include project= so the health endpoint's installation lookup finds this app.
    const r = await fetch(`${API_HEALTH}?userId=${USER_ID}&originId=${ORIGIN_ID}&project=${PROJECT}`, {
      signal: AbortSignal.timeout(5000),
      headers: { "Authorization": `Bearer ${_jwt ?? "null"}` },
    });
    if (!r.ok) return false;
    const data = await r.json();
    return Array.isArray(data.projects) && data.projects.includes(PROJECT);
  } catch { return false; }
}
