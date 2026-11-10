import type { TnaTemplate } from "../types";

export default function TemplateSummary({ template }: { template: TnaTemplate }) {
  return (
    <section className="card card-highlighted">
      <div className="row between wrap" style={{ alignItems: "flex-start", gap: 16 }}>
        <div style={{ flex: 1, minWidth: 280 }}>
          <div className="row" style={{ gap: 8 }}>
            <span className="badge badge-primary badge-mono">{template.template_id}</span>
            <span className="badge">{template.source === "file" ? "bundled file" : "snapshot"}</span>
          </div>
          <h2 style={{ fontSize: 22, marginTop: 8 }}>{template.product_type}</h2>
          <p className="secondary" style={{ marginTop: 6, maxWidth: 720 }}>{template.description}</p>
        </div>
        <div className="grid-3" style={{ minWidth: 280, flex: "0 0 auto" }}>
          <div className="hs-fact"><div className="hs-fact-label">Anchor</div><div className="hs-fact-value mono">{template.anchor}</div></div>
          <div className="hs-fact"><div className="hs-fact-label">Direction</div><div className="hs-fact-value">{template.schedule_direction}</div></div>
          <div className="hs-fact"><div className="hs-fact-label">Calendar</div><div className="hs-fact-value mono">{template.calendar}</div></div>
          <div className="hs-fact"><div className="hs-fact-label">Milestones</div><div className="hs-fact-value mono">{template.milestone_count}</div></div>
          <div className="hs-fact"><div className="hs-fact-label">Critical</div><div className="hs-fact-value mono">{template.milestones.filter((m) => m.is_critical).length}</div></div>
          <div className="hs-fact"><div className="hs-fact-label">Categories</div><div className="hs-fact-value mono">{template.categories.length}</div></div>
        </div>
      </div>
      <hr className="divider" />
      <div className="row wrap" style={{ gap: 6 }}>
        <span className="ctl-label" style={{ marginRight: 6 }}>Owner roles</span>
        {template.owner_roles.map((r) => <span key={r} className="chip">{r}</span>)}
      </div>
    </section>
  );
}
