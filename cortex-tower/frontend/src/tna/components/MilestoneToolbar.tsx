import { Search } from "lucide-react";
import { STATUS_VOCAB } from "../types";

export interface MilestoneFilters {
  q: string;
  category: string;
  status: string;
  criticalOnly: boolean;
  onlyIssues: boolean;
}

export const EMPTY_FILTERS: MilestoneFilters = {
  q: "", category: "all", status: "all", criticalOnly: false, onlyIssues: false,
};

export default function MilestoneToolbar({
  filters, onChange, categories, shown, total,
}: {
  filters: MilestoneFilters;
  onChange: (f: MilestoneFilters) => void;
  categories: string[];
  shown: number;
  total: number;
}) {
  const set = (patch: Partial<MilestoneFilters>) => onChange({ ...filters, ...patch });
  return (
    <div className="toolbar">
      <div className="search-wrap grow">
        <Search size={15} />
        <input
          className="input"
          placeholder="Search code, milestone, owner…"
          value={filters.q}
          onChange={(e) => set({ q: e.target.value })}
        />
      </div>
      <select className="input" value={filters.category} onChange={(e) => set({ category: e.target.value })}>
        <option value="all">All categories</option>
        {categories.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      <select className="input" value={filters.status} onChange={(e) => set({ status: e.target.value })}>
        <option value="all">All statuses</option>
        {STATUS_VOCAB.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
      <button
        className={`chip clickable${filters.criticalOnly ? " on" : ""}`}
        onClick={() => set({ criticalOnly: !filters.criticalOnly })}
        title="Show only critical-path milestones"
      >
        ◆ Critical only
      </button>
      <button
        className={`chip clickable${filters.onlyIssues ? " on" : ""}`}
        onClick={() => set({ onlyIssues: !filters.onlyIssues })}
        title="Show only Overdue / At risk / Blocked"
      >
        ⚠ Issues only
      </button>
      <span className="muted mono" style={{ fontSize: 12 }}>{shown}/{total}</span>
      {(filters.q || filters.category !== "all" || filters.status !== "all" || filters.criticalOnly || filters.onlyIssues) && (
        <button className="btn btn-ghost btn-sm" onClick={() => onChange(EMPTY_FILTERS)}>Reset</button>
      )}
    </div>
  );
}
