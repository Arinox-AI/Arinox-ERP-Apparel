import StatusBadge from "./StatusBadge";
import { fmtDate } from "../lib/format";
import type { TnaMilestone } from "../types";

/**
 * DependencyChain — upstream (what this milestone waits on) and downstream (what
 * waits on it), status-coloured. Dependencies come from the template.
 */
export default function DependencyChain({ code, milestones }: { code: string; milestones: TnaMilestone[] }) {
  const byCode = new Map(milestones.map((m) => [m.code, m]));
  const current = byCode.get(code);

  const upstream: TnaMilestone[] = [];
  const seen = new Set<string>();
  const walk = (c: string) => {
    const m = byCode.get(c);
    if (!m) return;
    (m.depends_on || []).forEach((d) => {
      if (seen.has(d)) return;
      seen.add(d);
      upstream.push(byCode.get(d) || ({ code: d, name: d, status: "Not recorded", planned_finish: null } as any));
      walk(d);
    });
  };
  walk(code);

  const downstream = milestones.filter((m) => (m.depends_on || []).includes(code));

  const Chip = ({ m }: { m: TnaMilestone }) => (
    <div className="row" style={{ gap: 8, padding: "5px 0", borderBottom: "1px dashed var(--border)" }}>
      <span className="mono" style={{ fontSize: 12, minWidth: 120, color: "var(--text-secondary)" }}>{m.code}</span>
      <span style={{ flex: 1, fontSize: 13 }}>{m.name}</span>
      <span className="muted mono" style={{ fontSize: 11 }}>{fmtDate(m.planned_finish)}</span>
      <StatusBadge status={m.status} showDot={false} />
    </div>
  );

  return (
    <div className="stack-sm">
      <div>
        <div className="field-hint" style={{ marginBottom: 4 }}>Upstream — this milestone depends on ({upstream.length})</div>
        {upstream.length === 0
          ? <div className="muted" style={{ fontSize: 12 }}>None — it can start immediately.</div>
          : upstream.map((m) => <Chip key={m.code} m={m} />)}
      </div>
      <div style={{ marginTop: 8 }}>
        <div className="field-hint" style={{ marginBottom: 4 }}>Downstream — depends on this ({downstream.length})</div>
        {downstream.length === 0
          ? <div className="muted" style={{ fontSize: 12 }}>None — the ship date is driven by it directly.</div>
          : downstream.map((m) => <Chip key={m.code} m={m} />)}
      </div>
      {current && current.is_blocked && current.blocked_by.length > 0 && (
        <div className="banner banner-error" style={{ marginTop: 8 }}>
          <span className="banner-icon">⛔</span>
          <div>
            <div className="banner-title">Blocked</div>
            <div>Waiting on incomplete predecessor{current.blocked_by.length > 1 ? "s" : ""}: <span className="mono">{current.blocked_by.join(", ")}</span></div>
          </div>
        </div>
      )}
    </div>
  );
}
