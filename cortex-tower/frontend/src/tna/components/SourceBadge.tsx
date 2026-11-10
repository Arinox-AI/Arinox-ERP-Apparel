import type { Source } from "../types";

/**
 * SourceBadge — every plan-bearing view must disclose whether the plan came from
 * the LIVE ERP or the bundled SNAPSHOT (SPEC §13.5, NFR-8).
 */
export default function SourceBadge({ source }: { source: Source | string | null | undefined }) {
  if (source === "live") {
    return (
      <span className="badge badge-primary badge-mono" title="Read live from the ERP at request time">
        <span className="dot dot-teal" />
        LIVE ERP
      </span>
    );
  }
  if (source === "sample") {
    return (
      <span className="badge badge-warning badge-mono" title="The ERP has no Sales Orders yet, so a bundled example order is shown. It disappears when the first real order is in the ERP.">
        <span className="dot dot-amber" />
        SAMPLE ORDER
      </span>
    );
  }
  if (source === "snapshot") {
    return (
      <span className="badge badge-warning badge-mono" title="Offline snapshot (TNA_OFFLINE is on). Nothing here is being read from the ERP.">
        <span className="dot dot-amber" />
        OFFLINE SNAPSHOT
      </span>
    );
  }
  return (
    <span className="badge badge-mono" title="The ERP did not answer, so no plan can be read">
      <span className="dot dot-amber" />
      ERP NOT REACHABLE
    </span>
  );
}
