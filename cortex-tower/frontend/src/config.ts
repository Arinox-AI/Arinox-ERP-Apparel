// Cortex Operations Control Tower — Frontend configuration (reads from window.APP_CONFIG)
const _cfg: Record<string, string> =
  (typeof window !== "undefined" && (window as any).APP_CONFIG) || {};

export const API_BASE:      string = _cfg.API_BASE      || "";
export const API_HEALTH:    string = _cfg.API_HEALTH    || "";
export const PROJECT:       string = _cfg.PROJECT       || "cortex_operations_control_tower";
export const AGENT_ID:      string = _cfg.AGENT_ID      || "";
export const DEPLOYMENT_ID: string = _cfg.DEPLOYMENT_ID || "";
export const SWARM_ID:      string = _cfg.SWARM_ID      || "";
export const ORIGIN_ID:     string = _cfg.ORIGIN_ID     || "";
export const USER_ID:       string = _cfg.USER_ID       || "";
