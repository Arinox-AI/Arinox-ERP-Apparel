import TemplateSummary from "../components/TemplateSummary";
import TemplateTable from "../components/TemplateTable";
import EmptyState from "../components/EmptyState";
import type { TnaTemplate } from "../types";

export default function Template({ template }: { template: TnaTemplate | null }) {
  if (!template) {
    return <EmptyState title="Template not loaded" message="The product-type template could not be read." />;
  }
  return (
    <div className="stack">
      <TemplateSummary template={template} />
      <div className="card-head">
        <div className="card-title">Template milestones ({template.milestones.length})</div>
        <div className="card-sub">
          Backward-scheduled in working days from the <span className="mono">{template.anchor}</span> anchor. Add a product
          type by dropping in another template file — no code change.
        </div>
      </div>
      <TemplateTable milestones={template.milestones} />
    </div>
  );
}
