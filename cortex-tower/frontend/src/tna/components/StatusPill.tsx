import { statusShort, statusTone, toneBg, toneColor } from "../lib/status";

/** A single status pill — the one place a milestone status becomes a colour. */
export default function StatusPill({
  status, big, dot = true,
}: {
  status: string | null | undefined;
  big?: boolean;
  dot?: boolean;
}) {
  const tone = statusTone(status);
  return (
    <span
      className={`status-pill${big ? " big" : ""}`}
      style={{ background: toneBg(tone), color: toneColor(tone), borderColor: toneColor(tone) }}
      title={status || ""}
    >
      {dot && <span className="status-dot" style={{ background: toneColor(tone) }} />}
      {statusShort(status)}
    </span>
  );
}
