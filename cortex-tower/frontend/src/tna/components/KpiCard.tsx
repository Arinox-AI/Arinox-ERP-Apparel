import type { ReactNode } from "react";

export type KpiTone = "red" | "amber" | "green" | "navy" | "teal";

export default function KpiCard({
  label, value, sub, tone = "navy", small,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: KpiTone;
  small?: boolean;
}) {
  return (
    <div className={`kpi kpi-${tone}`}>
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value${small ? " sm" : ""}`}>{value}</div>
      {sub !== undefined && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}
