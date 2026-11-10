import { callBridge } from "../services/api";

export type R = Record<string, any>;

/** One call path for the whole new UI: always the middleware, always returns an object with `ok`. */
export async function call(name: string, params: R = {}): Promise<R> {
  try {
    const res = await callBridge(name, params);
    if (res && res.data && typeof res.data === "object") return res.data as R;
    return { ok: false, error: res?.message || "The server gave no answer. Try again." };
  } catch {
    return { ok: false, error: "Can't reach the server. Check your connection and try again." };
  }
}

export const TOKEN_KEY = "cx_token";
export const setToken = (t: string | null) => {
  try { if (t) localStorage.setItem(TOKEN_KEY, t); else localStorage.removeItem(TOKEN_KEY); }
  catch { /* storage blocked: the token then lives for this page only */ }
};

export const uid = () => (crypto?.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));

export function ago(iso?: string | null): string {
  if (!iso) return "";
  const t = new Date(iso.replace(" ", "T")).getTime();
  if (isNaN(t)) return iso;
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 7 * 86400) return `${Math.round(s / 86400)} d ago`;
  return new Date(t).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function fmtVal(v: any): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 3 });
  if (typeof v === "boolean") return v ? "Yes" : "No";
  return String(v);
}

export const slugTitle = (s: string) => s.replace(/^arinox_/, "").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
