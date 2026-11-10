import { ChevronRight } from "lucide-react";
import type { Risk } from "../types";
import { RISK_TYPE_META, fmtDate } from "../types";

/** Compact, scannable risk row. Full evidence lives in the drawer. */
export function RiskRow({ risk, onOpen }: { risk: Risk; onOpen: () => void }) {
  const meta = RISK_TYPE_META[risk.risk_type] || { label: risk.risk_type, hint: "" };
  const critical = risk.severity === "critical";

  const chips: { k: string; v: string }[] = [];
  if (risk.material) chips.push({ k: "Material", v: risk.material });
  if (risk.affected_orders?.length) chips.push({ k: "Orders", v: `${risk.affected_orders.length}` });
  else if (risk.affected_order) chips.push({ k: "Order", v: risk.affected_order });
  if (risk.required_date) chips.push({ k: "Required", v: fmtDate(risk.required_date) });
  if (!risk.required_date && risk.shipment_date) chips.push({ k: "Ship", v: fmtDate(risk.shipment_date) });
  if (risk.style) chips.push({ k: "Style", v: risk.style });

  return (
    <div className="row row--click" onClick={onOpen} role="button" tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter") onOpen(); }}>
      <span className="row__rail" style={{ background: critical ? "var(--negative)" : "var(--warning)" }} />
      <div className="row__main">
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span className={`badge badge--${critical ? "critical" : "warning"}`}>
            <span className="badge__dot" />
            {critical ? "Critical" : "Warning"}
          </span>
          <span className="badge badge--outline">{meta.label}</span>
        </div>
        <div className="row__title" style={{ marginTop: 6 }}>{risk.title}</div>
        {chips.length > 0 && (
          <div className="row__meta">
            {chips.slice(0, 4).map((c) => (
              <span key={c.k}>{c.k}: <b>{c.v}</b></span>
            ))}
          </div>
        )}
      </div>
      <span className="row__chev"><ChevronRight size={16} /></span>
    </div>
  );
}
