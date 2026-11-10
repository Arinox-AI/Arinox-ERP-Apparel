import { useMemo, useState } from "react";
import { History } from "lucide-react";
import type { Audit } from "../types";
import { fmtTime } from "../types";
import { Card, Empty } from "../ui";

const TYPE_META: Record<string, { color: string; label: string }> = {
  execute: { color: "var(--positive)", label: "Executed" },
  approval: { color: "var(--chart-5)", label: "Approved" },
  decision: { color: "var(--chart-5)", label: "Decision" },
  reject: { color: "var(--negative)", label: "Rejected" },
  modify: { color: "var(--warning)", label: "Modified" },
};

export function ActivityView({ audit }: { audit: Audit[] }) {
  const [type, setType] = useState("all");

  const types = useMemo(() => Array.from(new Set(audit.map((a) => a.action_type).filter(Boolean))), [audit]);
  const rows = useMemo(
    () => (type === "all" ? audit : audit.filter((a) => a.action_type === type)),
    [audit, type]
  );

  return (
    <>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 14 }}>
        <div className="tabs">
          <button className={`tab${type === "all" ? " is-active" : ""}`} onClick={() => setType("all")}>
            All <span style={{ marginLeft: 6, color: "var(--text-muted)", fontWeight: 700 }}>{audit.length}</span>
          </button>
          {types.map((t) => (
            <button key={t} className={`tab${type === t ? " is-active" : ""}`} onClick={() => setType(t)}>
              {TYPE_META[t]?.label || t}
            </button>
          ))}
        </div>
      </div>

      <Card flush>
        {rows.length === 0 ? (
          <Empty
            icon={<History size={18} />}
            title="No activity yet"
            hint="Preview, approve or execute a recommended action to build the audit trail."
          />
        ) : (
          <div className="timeline">
            {rows.map((a) => {
              const meta = TYPE_META[a.action_type] || { color: "var(--text-muted)", label: a.action_type };
              return (
                <div key={a.id} className="tl-item">
                  <span className="tl-dot" style={{ background: meta.color }} />
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                      <span style={{ fontSize: 13, fontWeight: 600 }}>{a.action_name}</span>
                      <span className={`badge badge--outline`} style={{ color: meta.color, borderColor: meta.color }}>{meta.label}</span>
                      <span style={{ fontSize: 11, color: "var(--text-muted)" }}>{a.actor}</span>
                    </div>
                    <div style={{ fontSize: 12.5, color: "var(--text-secondary)", marginTop: 3 }}>{a.description}</div>
                    {a.risk_title && (
                      <div style={{ fontSize: 11.5, color: "var(--text-muted)", marginTop: 3 }}>Risk: {a.risk_title}</div>
                    )}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)", whiteSpace: "nowrap" }}>{fmtTime(a.timestamp)}</div>
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </>
  );
}
