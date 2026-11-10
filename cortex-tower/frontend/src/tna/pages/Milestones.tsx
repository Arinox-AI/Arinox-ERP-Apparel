import { useMemo, useState } from "react";
import MilestoneToolbar, { EMPTY_FILTERS, type MilestoneFilters } from "../components/MilestoneToolbar";
import MilestoneTable from "../components/MilestoneTable";
import type { TnaMilestone } from "../types";

const ISSUE_STATUSES = new Set(["Overdue", "At risk", "Blocked", "Waiting for approval", "Waiting for material", "Not recorded"]);

export default function Milestones({
  milestones, categories, selectedCode, onSelect,
}: {
  milestones: TnaMilestone[];
  categories: string[];
  selectedCode: string | null;
  onSelect: (code: string) => void;
}) {
  const [filters, setFilters] = useState<MilestoneFilters>(EMPTY_FILTERS);

  const filtered = useMemo(() => {
    const q = filters.q.trim().toLowerCase();
    return milestones.filter((m) => {
      if (filters.category !== "all" && m.category !== filters.category) return false;
      if (filters.status !== "all" && m.status !== filters.status) return false;
      if (filters.criticalOnly && !m.is_critical) return false;
      if (filters.onlyIssues && !ISSUE_STATUSES.has(m.status)) return false;
      if (q) {
        const hay = `${m.code} ${m.name} ${m.owner} ${m.owner_role} ${m.category}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [milestones, filters]);

  return (
    <div className="stack">
      <MilestoneToolbar
        filters={filters}
        onChange={setFilters}
        categories={categories}
        shown={filtered.length}
        total={milestones.length}
      />
      <MilestoneTable milestones={filtered} selectedCode={selectedCode} onSelect={onSelect} />
    </div>
  );
}
