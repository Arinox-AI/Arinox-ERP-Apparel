import { useEffect, useState } from "react";

/**
 * The opening screen.
 *
 * A command centre announces itself once: the mark, the name, and an honest line
 * about what it is doing. It is deliberately short (about a second), it never
 * blocks a working screen, and it says exactly which step is running so a slow
 * ERP read is visible instead of looking frozen.
 */
export type BootStep = { label: string; state: "idle" | "on" | "done" | "failed" };

const DEFAULT_STEPS = [
  "Checking who you are",
  "Opening your inbox and deals",
  "Ready",
];

export function Boot({ done = false, steps, status }: { done?: boolean; steps?: BootStep[]; status?: string }) {
  const list: BootStep[] = steps && steps.length
    ? steps
    : DEFAULT_STEPS.map((label, i) => ({ label, state: i === 0 ? "on" : "idle" }));

  const total = list.length || 1;
  const doneCount = list.filter((s) => s.state === "done").length;
  const running = list.filter((s) => s.state === "on").length;
  const progress = Math.round(((doneCount + running * 0.5) / total) * 100);
  const [shown, setShown] = useState(4);

  /* ease the bar forward so it never jumps backwards between calls */
  useEffect(() => {
    setShown((prev) => (progress > prev ? progress : prev));
  }, [progress]);

  const line = status || list.find((s) => s.state === "on")?.label || "Starting";

  return (
    <div className={`cx-boot${done ? " is-out" : ""}`} role="status" aria-live="polite" aria-label="Cortex Tower is starting">
      <div className="cx-boot__inner">
        <div className="cx-boot__mark">CT</div>
        <h1 className="cx-boot__name">Cortex Tower</h1>
        <p className="cx-boot__tag">Apparel operations</p>

        <div className="cx-boot__track" aria-hidden="true">
          <div className="cx-boot__fill" style={{ width: `${Math.min(100, shown)}%` }} />
        </div>
        <div className="cx-boot__status">
          <b>{line}</b>
          <span>{Math.min(100, shown)}%</span>
        </div>

        <ul className="cx-boot__steps">
          {list.map((s, i) => (
            <li key={i} className={s.state === "done" ? "is-done" : s.state === "on" ? "is-on" : ""}>
              <span className="cx-boot__tick" aria-hidden="true" />
              <span>{s.label}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/** Convenience: the three standard steps with the first N marked done. */
export function bootSteps(doneUpTo: number, failed = false): BootStep[] {
  return DEFAULT_STEPS.map((label, i) => ({
    label,
    state: i < doneUpTo ? "done" : i === doneUpTo ? (failed ? "failed" : "on") : "idle",
  }));
}
