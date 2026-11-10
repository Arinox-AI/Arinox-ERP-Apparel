import { Info } from "lucide-react";
import type { Kpi } from "../types";
import { toneColor } from "../types";

export function MetricTile({ kpi, hero }: { kpi: Kpi; hero?: boolean }) {
  const color = toneColor[kpi.tone] || "var(--text-secondary)";
  const tip = kpi.tooltip || kpi.hint || kpi.label;
  return (
    <div className={`metric${hero ? " metric--hero" : ""}`}>
      <span className="metric__rail" style={{ background: color }} />
      <div className="metric__label">
        {kpi.label}
        <span className="metric__info" aria-label={tip}><Info size={11} /></span>
      </div>
      <div className="metric__value" style={{ color: kpi.tone === "neutral" ? "var(--text)" : color }}>
        {kpi.value}
        {kpi.unit && <span className="metric__unit">{kpi.unit}</span>}
      </div>
      {kpi.hint && <div className="metric__foot">{kpi.hint}</div>}
      {/* Real CSS tooltip (native title is unreliable inside the embedded app). */}
      <div className="metric__tip" role="tooltip">{tip}</div>
    </div>
  );
}
