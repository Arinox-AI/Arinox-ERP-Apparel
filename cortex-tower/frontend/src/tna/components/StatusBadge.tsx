import { statusTone } from "../lib/format";

const TONE_CLASS: Record<string, string> = {
  green: "badge badge-success",
  amber: "badge badge-warning",
  red: "badge badge-error",
  navy: "badge badge-primary",
  teal: "badge badge-teal",
  muted: "badge",
};

const DOT_CLASS: Record<string, string> = {
  green: "dot dot-green",
  amber: "dot dot-amber",
  red: "dot dot-red",
  navy: "dot dot-teal",
  teal: "dot dot-teal",
  muted: "dot dot-muted",
};

export default function StatusBadge({ status, showDot = true }: { status: string; showDot?: boolean }) {
  const tone = statusTone(status);
  return (
    <span className={TONE_CLASS[tone] || "badge"} title={status}>
      {showDot && <span className={DOT_CLASS[tone] || "dot dot-muted"} />}
      {status}
    </span>
  );
}
