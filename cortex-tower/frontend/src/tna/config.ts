// Cortex TnA Calendar — frontend config.
//
// The TnA experience now ships INSIDE the Cortex Operations Control Tower app,
// so it reads the SAME window.APP_CONFIG (set by the host app's config.js) and
// therefore calls the merged Control Tower project, where the TnA backend
// functions are registered (see backend/tna_app/).
const _cfg = (window as any).APP_CONFIG || {};

export const API_BASE      = _cfg.API_BASE      || "";
export const API_HEALTH    = _cfg.API_HEALTH    || "";
export const PROJECT: string = _cfg.PROJECT     || "cortex_operations_control_tower";
export const USER_ID: string = _cfg.USER_ID     || "";
export const AGENT_ID: string      = _cfg.AGENT_ID      || "";
export const DEPLOYMENT_ID: string = _cfg.DEPLOYMENT_ID || "";
export const SWARM_ID: string      = _cfg.SWARM_ID      || "";
export const ORIGIN_ID: string     = _cfg.ORIGIN_ID     || "";
