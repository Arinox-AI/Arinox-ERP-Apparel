import { useMemo, useState } from "react";
import { ShieldCheck } from "lucide-react";
import type { Risk } from "../types";
import { sevRank } from "../types";
import { Card, Empty } from "../ui";
import { RiskRow } from "../components/RiskRow";

type Filter = "all" | "critical" | "warning";

export function RisksView(props: { risks: Risk[]; onOpenRisk: (r: Risk) => void }) {
  const { risks, onOpenRisk } = props;
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");

  const open = useMemo(() => risks.filter((r) => r.status === "open"), [risks]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return open
      .filter((r) => (filter === "all" ? true : r.severity === filter))
      .filter((r) => (needle ? JSON.stringify(r).toLowerCase().includes(needle) : true))
      .sort((a, b) => sevRank(a.severity) - sevRank(b.severity));
  }, [open, filter, q]);

  const critical = open.filter((r) => r.severity === "critical");
  const warning = open.filter((r) => r.severity === "warning");

  const counts: Record<Filter, number> = { all: open.length, critical: critical.length, warning: warning.length };

  return (
    <>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 14 }}>
        <div className="tabs">
          {(["all", "critical", "warning"] as Filter[]).map((f) => (
            <button key={f} className={`tab${filter === f ? " is-active" : ""}`} onClick={() => setFilter(f)}>
              {f === "all" ? "All" : f === "critical" ? "Critical" : "Warning"}
              <span style={{ marginLeft: 6, color: "var(--text-muted)", fontWeight: 700 }}>{counts[f]}</span>
            </button>
          ))}
        </div>
        <input
          className="input"
          style={{ marginLeft: "auto", minWidth: 220 }}
          placeholder="Search risks…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      {filtered.length === 0 ? (
        <Card>
          <Empty good icon={<ShieldCheck size={18} />} title="No risks match" hint="Try a different filter or clear the search." />
        </Card>
      ) : filter === "all" ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {critical.length > 0 && (
            <Card flush title={`Critical (${critical.length})`} sub="Blocks production, cash or shipment now">
              {critical.map((r) => <RiskRow key={r.id} risk={r} onOpen={() => onOpenRisk(r)} />)}
            </Card>
          )}
          {warning.length > 0 && (
            <Card flush title={`Warning (${warning.length})`} sub="Needs attention before it becomes critical">
              {warning.map((r) => <RiskRow key={r.id} risk={r} onOpen={() => onOpenRisk(r)} />)}
            </Card>
          )}
        </div>
      ) : (
        <Card flush title={`${filter === "critical" ? "Critical" : "Warning"} (${filtered.length})`}>
          {filtered.map((r) => <RiskRow key={r.id} risk={r} onOpen={() => onOpenRisk(r)} />)}
        </Card>
      )}
    </>
  );
}
