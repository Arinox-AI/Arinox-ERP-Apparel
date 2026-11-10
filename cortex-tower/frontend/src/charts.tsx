import React from "react";

const SERIES_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
  "var(--chart-6)",
];

function niceMax(v: number) {
  if (v <= 0) return 1;
  const pow = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / pow;
  const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
  return step * pow;
}

function Grid({ ticks = 4 }: { ticks?: number }) {
  return (
    <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", justifyContent: "space-between", pointerEvents: "none" }}>
      {Array.from({ length: ticks + 1 }).map((_, i) => (
        <div key={i} style={{ borderTop: `1px solid var(--chart-grid)`, height: 0 }} />
      ))}
    </div>
  );
}

/* ── single-series vertical bars ──────────────────────────────────────────── */
export function BarChart(props: {
  data: { x: string; y: number }[];
  color?: string;
  label?: (d: { x: string; y: number }) => string;
  format?: (x: string) => string;
  height?: number;
}) {
  const { data, color = "var(--chart-1)", label, format, height = 168 } = props;
  if (!data.length) return <div className="empty" style={{ padding: 24 }}>No data</div>;
  const max = niceMax(Math.max(...data.map((d) => Number(d.y) || 0)));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ position: "relative", height }}>
        <Grid />
        <div style={{ position: "relative", display: "flex", alignItems: "flex-end", gap: 8, height: "100%" }}>
          {data.map((d, i) => {
            const v = Number(d.y) || 0;
            const pct = (v / max) * 100;
            return (
              <div
                key={i}
                title={`${format ? format(d.x) : d.x}: ${v.toLocaleString()}`}
                style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 4, height: "100%", justifyContent: "flex-end", minWidth: 0 }}
              >
                <div style={{ fontSize: 10.5, fontWeight: 600, color: "var(--text-secondary)", whiteSpace: "nowrap" }}>
                  {label ? label(d) : v.toLocaleString()}
                </div>
                <div
                  style={{
                    width: "100%", maxWidth: 46, height: `${Math.max(3, pct)}%`,
                    background: color, borderRadius: "5px 5px 0 0",
                    transition: "height 0.3s var(--ease)",
                  }}
                />
              </div>
            );
          })}
        </div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        {data.map((d, i) => (
          <div key={i} style={{ flex: 1, textAlign: "center", fontSize: 10.5, color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {format ? format(d.x) : d.x}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── grouped bars (2–3 series) ────────────────────────────────────────────── */
export function GroupedBar(props: {
  data: Record<string, any>[];
  series: string[];
  colors?: string[];
  height?: number;
  format?: (x: string) => string;
  valueFmt?: (v: number) => string;
}) {
  const { data, series, colors = SERIES_COLORS, height = 168, format, valueFmt = (v) => v.toLocaleString() } = props;
  if (!data.length) return <div className="empty" style={{ padding: 24 }}>No data</div>;
  const max = niceMax(Math.max(...data.flatMap((d) => series.map((s) => Number(d[s]) || 0))));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ position: "relative", height }}>
        <Grid />
        <div style={{ position: "relative", display: "flex", alignItems: "flex-end", gap: 10, height: "100%" }}>
          {data.map((d, i) => (
            <div key={i} style={{ flex: 1, display: "flex", alignItems: "flex-end", justifyContent: "center", gap: 3, height: "100%", minWidth: 0 }}>
              {series.map((s, j) => {
                const v = Number(d[s]) || 0;
                const pct = (v / max) * 100;
                return (
                  <div
                    key={s}
                    title={`${d.x} · ${s.replace(/_/g, " ")}: ${valueFmt(v)}`}
                    style={{
                      width: "100%", maxWidth: 18, height: `${Math.max(2.5, pct)}%`,
                      background: colors[j % colors.length], borderRadius: "4px 4px 0 0",
                      transition: "height 0.3s var(--ease)",
                    }}
                  />
                );
              })}
            </div>
          ))}
        </div>
      </div>
      <div style={{ display: "flex", gap: 10 }}>
        {data.map((d, i) => (
          <div key={i} style={{ flex: 1, textAlign: "center", fontSize: 10.5, color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {format ? format(d.x) : d.x}
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 14, marginTop: 4, flexWrap: "wrap" }}>
        {series.map((s, j) => (
          <div key={s} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 10.5, color: "var(--text-secondary)" }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: colors[j % colors.length] }} />
            {s.replace(/_/g, " ")}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── donut ────────────────────────────────────────────────────────────────── */
export function Donut({ data, size = 176 }: { data: { x: string; y: number }[]; size?: number }) {
  const rows = (data || []).filter((d) => (Number(d?.y) || 0) > 0);
  const total = rows.reduce((s, d) => s + (Number(d.y) || 0), 0);
  if (!total) return <div className="empty" style={{ padding: 24 }}>No data</div>;
  const r = size / 2 - 16;
  const C = 2 * Math.PI * r;
  let acc = 0;
  const segs = rows.map((d, i) => {
    const v = Number(d.y) || 0;
    const start = acc;
    acc += v;
    return { ...d, v, start, end: acc, color: SERIES_COLORS[i % SERIES_COLORS.length] };
  });
  return (
    <div style={{ display: "flex", gap: 18, alignItems: "center", flexWrap: "wrap" }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ flex: "0 0 auto" }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-sunken)" strokeWidth={16} />
        {segs.map((s, i) => {
          const frac = (s.end - s.start) / total;
          const offset = (s.start / total) * C;
          return (
            <circle
              key={i}
              cx={size / 2} cy={size / 2} r={r} fill="none"
              stroke={s.color} strokeWidth={16}
              strokeDasharray={`${frac * C} ${C}`} strokeDashoffset={-offset}
              transform={`rotate(-90 ${size / 2} ${size / 2})`}
            >
              <title>{`${s.x}: ${s.v.toLocaleString()}`}</title>
            </circle>
          );
        })}
        <text x="50%" y="47%" textAnchor="middle" fontSize="22" fontWeight="700" fill="var(--text)">{total.toLocaleString()}</text>
        <text x="50%" y="60%" textAnchor="middle" fontSize="10" fill="var(--text-muted)">total</text>
      </svg>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 0, flex: 1 }}>
        {segs.map((s, i) => (
          <div key={i} style={{ display: "flex", alignItems: "baseline", gap: 8, fontSize: 12, color: "var(--text-secondary)" }}>
            <span style={{ width: 9, height: 9, borderRadius: 3, background: s.color, flex: "0 0 9px", transform: "translateY(1px)" }} />
            <span style={{ minWidth: 0, lineHeight: 1.35 }}>{s.x}</span>
            <b style={{ marginLeft: "auto", color: "var(--text)", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
              {s.v.toLocaleString()}
              <span style={{ color: "var(--text-muted)", fontWeight: 500, marginLeft: 5 }}>
                {Math.round((s.v / total) * 100)}%
              </span>
            </b>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   Horizontal charts — built for long category names.
   A vertical bar chart inside a ~340px card gives each category ~30px, so the
   axis labels get ellipsised. Rotating them sideways is worse to read. Laying
   the categories down the left and growing the bars to the right keeps every
   label and every value fully legible at any width.
   ══════════════════════════════════════════════════════════════════════════ */

function Legend({ series }: { series: { key: string; label: string; color: string }[] }) {
  if (series.length < 2) return null;
  return (
    <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginBottom: 12 }}>
      {series.map((s) => (
        <span key={s.key} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11.5, color: "var(--text-secondary)" }}>
          <span style={{ width: 10, height: 10, borderRadius: 3, background: s.color, flex: "0 0 10px" }} />
          {s.label}
        </span>
      ))}
    </div>
  );
}

/* ── horizontal, grouped (2–4 series per category) ────────────────────────── */
export function HGroupedBar(props: {
  data: Record<string, any>[];
  series: { key: string; label: string; color: string }[];
  rowLabel: (d: Record<string, any>) => string;
  valueFmt?: (v: number) => string;
  labelWidth?: number;
  barHeight?: number;
}) {
  const { data, series, rowLabel, valueFmt = (v) => v.toLocaleString(), labelWidth = 140, barHeight = 9 } = props;
  if (!data.length) return <div className="empty" style={{ padding: 24 }}>No data</div>;
  const max = niceMax(Math.max(...data.flatMap((d) => series.map((s) => Number(d[s.key]) || 0))));

  return (
    <div>
      <Legend series={series} />
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {data.map((d, i) => (
          <div key={i} style={{ display: "flex", alignItems: "stretch", gap: 12 }}>
            <div
              title={rowLabel(d)}
              style={{
                flex: `0 0 ${labelWidth}px`, maxWidth: labelWidth, fontSize: 11.5, fontWeight: 600,
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", color: "var(--text-secondary)",
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", paddingTop: 1,
              }}
            >
              {rowLabel(d)}
            </div>
            <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 5 }}>
              {series.map((s) => {
                const v = Number(d[s.key]) || 0;
                const w = max ? (v / max) * 100 : 0;
                return (
                  <div key={s.key} style={{ display: "flex", alignItems: "center", gap: 8 }} title={`${rowLabel(d)} · ${s.label}: ${valueFmt(v)}`}>
                    <div style={{ flex: 1, minWidth: 0, height: barHeight, background: "var(--surface-sunken)", borderRadius: barHeight / 2, overflow: "hidden" }}>
                      <div style={{ width: `${Math.max(v > 0 ? 2 : 0, w)}%`, height: "100%", background: s.color, borderRadius: barHeight / 2, transition: "width .3s var(--ease)" }} />
                    </div>
                    <div style={{ flex: "0 0 70px", textAlign: "right", fontSize: 11, color: v ? "var(--text)" : "var(--text-muted)", fontVariantNumeric: "tabular-nums", fontWeight: v ? 600 : 400 }}>
                      {v ? valueFmt(v) : "—"}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── horizontal, single series ───────────────────────────────────────────── */
export function HBar(props: {
  data: { x: string; y: number }[];
  color?: string;
  valueFmt?: (v: number) => string;
  labelWidth?: number;
  barHeight?: number;
  colorFor?: (d: { x: string; y: number }) => string;
}) {
  const { data, color = "var(--chart-1)", valueFmt = (v) => v.toLocaleString(), labelWidth = 140, barHeight = 11, colorFor } = props;
  if (!data.length) return <div className="empty" style={{ padding: 24 }}>No data</div>;
  const max = niceMax(Math.max(...data.map((d) => Number(d.y) || 0)));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
      {data.map((d, i) => {
        const v = Number(d.y) || 0;
        const w = max ? (v / max) * 100 : 0;
        return (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 12 }} title={`${d.x}: ${valueFmt(v)}`}>
            <div style={{ flex: `0 0 ${labelWidth}px`, maxWidth: labelWidth, fontSize: 11.5, fontWeight: 600,
                          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", color: "var(--text-secondary)",
                          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {d.x}
            </div>
            <div style={{ flex: 1, minWidth: 0, height: barHeight, background: "var(--surface-sunken)", borderRadius: barHeight / 2, overflow: "hidden" }}>
              <div style={{ width: `${Math.max(v > 0 ? 2 : 0, w)}%`, height: "100%", background: colorFor ? colorFor(d) : color, borderRadius: barHeight / 2, transition: "width .3s var(--ease)" }} />
            </div>
            <div style={{ flex: "0 0 76px", textAlign: "right", fontSize: 11, fontWeight: 600, color: v ? "var(--text)" : "var(--text-muted)", fontVariantNumeric: "tabular-nums" }}>
              {v ? valueFmt(v) : "—"}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── Ordered vs actual — fulfilment board ──────────────────────────────────
 * Replaces the twin-grouped horizontal bars with a single overlaid track per
 * row: the pale band is the ordered quantity, the solid fill is what actually
 * happened, and a tick marks the ordered line. Under = fill stops short,
 * over = fill runs past the tick in amber. Rows sort worst-first by default.
 */
export function OrderedVsActual(props: {
  data: Record<string, any>[];
  orderedLabel?: string;
  actualLabel?: string;
  color?: string;
  valueFmt?: (v: number) => string;
  labelWidth?: number;
  topN?: number;
}) {
  const {
    data,
    orderedLabel = "Ordered",
    actualLabel = "Actual",
    color = "var(--chart-2)",
    valueFmt = (v: number) => Math.round(v).toLocaleString(),
    labelWidth = 132,
    topN = 0,
  } = props;

  const [sort, setSort] = React.useState<"gap" | "under" | "over" | "name">("gap");
  const [showAll, setShowAll] = React.useState(false);

  const rows = React.useMemo(() => {
    const out = data.map((d) => {
      const ordered = Number(d.planned) || 0;
      const actual = Number(d.actual) || 0;
      const pct = ordered > 0 ? Math.round((actual / ordered) * 100) : 0;
      return { x: String(d.x), ordered, actual, pct, variance: actual - ordered };
    });
    const cmp: Record<string, (a: any, b: any) => number> = {
      gap: (a, b) => Math.abs(b.variance) - Math.abs(a.variance),
      under: (a, b) => a.pct - b.pct,
      over: (a, b) => b.pct - a.pct,
      name: (a, b) => a.x.localeCompare(b.x),
    };
    return out.sort(cmp[sort]);
  }, [data, sort]);

  if (!rows.length) return <div className="empty" style={{ padding: 24 }}>No data</div>;

  const totalOrdered = rows.reduce((s, r) => s + r.ordered, 0);
  const totalActual = rows.reduce((s, r) => s + r.actual, 0);
  const overall = totalOrdered ? Math.round((totalActual / totalOrdered) * 100) : 0;
  const short = rows.filter((r) => r.pct < 95).length;
  const over = rows.filter((r) => r.pct > 105).length;
  const max = niceMax(Math.max(...rows.flatMap((r) => [r.ordered, r.actual]), 1));
  const visible = showAll || !topN ? rows : rows.slice(0, topN);

  const pctTone = (pct: number) =>
    pct < 95 ? "var(--warning-ink)" : pct > 105 ? "var(--warning-ink)" : "var(--positive-ink)";
  const chipCls = (pct: number) =>
    pct < 95 ? "badge--warning" : pct > 105 ? "badge--warning" : "badge--positive";

  return (
    <div>
      {/* summary */}
      <div
        style={{
          display: "flex", gap: 18, flexWrap: "wrap", alignItems: "center",
          padding: "10px 12px", marginBottom: 14, background: "var(--surface-sunken)", borderRadius: 10,
        }}
      >
        <div>
          <div style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", color: "var(--text-muted)" }}>{orderedLabel}</div>
          <div style={{ fontSize: 17, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{valueFmt(totalOrdered)}</div>
        </div>
        <div>
          <div style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", color: "var(--text-muted)" }}>{actualLabel}</div>
          <div style={{ fontSize: 17, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{valueFmt(totalActual)}</div>
        </div>
        <div>
          <div style={{ fontSize: 10.5, fontWeight: 700, letterSpacing: 0.5, textTransform: "uppercase", color: "var(--text-muted)" }}>Overall</div>
          <div style={{ fontSize: 17, fontWeight: 700, color: pctTone(overall) }}>{overall}%</div>
        </div>
        <div style={{ display: "flex", gap: 6, marginLeft: "auto", flexWrap: "wrap" }}>
          {short > 0 && <span className="badge badge--warning">{short} short of plan</span>}
          {over > 0 && <span className="badge badge--warning">{over} over plan</span>}
          {short === 0 && over === 0 && <span className="badge badge--positive">all on plan</span>}
        </div>
      </div>

      {/* controls + legend */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--text-muted)" }}>
          <span style={{ width: 18, height: 9, borderRadius: 3, background: "var(--chart-1)", opacity: 0.22, border: "1px solid var(--border)" }} />
          {orderedLabel}
          <span style={{ width: 18, height: 9, borderRadius: 3, background: color, marginLeft: 8 }} />
          {actualLabel}
        </span>
        {(["gap", "under", "over", "name"] as const).map((k) => (
          <button
            key={k}
            className={`btn btn--sm${sort === k ? " btn--brand" : ""}`}
            onClick={() => setSort(k)}
          >
            {k === "gap" ? "Biggest gap" : k === "under" ? "Most short" : k === "over" ? "Most over" : "A–Z"}
          </button>
        ))}
      </div>

      {/* rows */}
      <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
        {visible.map((r) => {
          const isOver = r.actual > r.ordered;
          const wOrd = (r.ordered / max) * 100;
          const wAct = (r.actual / max) * 100;
          return (
            <div
              key={r.x}
              title={`${r.x} · ${orderedLabel} ${valueFmt(r.ordered)} · ${actualLabel} ${valueFmt(r.actual)} · ${r.pct}%`}
              style={{ display: "flex", alignItems: "center", gap: 10 }}
            >
              <div
                style={{
                  flex: `0 0 ${labelWidth}px`, maxWidth: labelWidth, fontSize: 11.5, fontWeight: 600,
                  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", color: "var(--text-secondary)",
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                }}
              >
                {r.x}
              </div>

              <div style={{ flex: 1, minWidth: 0, position: "relative", height: 16 }}>
                <div style={{ position: "absolute", inset: 0, background: "var(--surface-sunken)", borderRadius: 4 }} />
                {/* ordered band */}
                <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${wOrd}%`, background: "var(--chart-1)", opacity: 0.22, borderRadius: 4 }} />
                {/* actual fill */}
                <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${wAct}%`, background: isOver ? "var(--warning)" : color, borderRadius: 4 }} />
                {/* ordered tick */}
                <div style={{ position: "absolute", left: `${wOrd}%`, top: -2, bottom: -2, width: 2, background: "var(--text-muted)", transform: "translateX(-1px)" }} />
              </div>

              <div style={{ flex: "0 0 108px", textAlign: "right", fontSize: 11.5, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>
                <b>{valueFmt(r.actual)}</b>
                <span style={{ color: "var(--text-muted)" }}> / {valueFmt(r.ordered)}</span>
              </div>
              <span className={`badge ${chipCls(r.pct)}`} style={{ flex: "0 0 58px", justifyContent: "center" }}>
                {r.pct}%
              </span>
            </div>
          );
        })}
      </div>

      {topN > 0 && rows.length > topN && (
        <button className="btn btn--sm btn--ghost" style={{ marginTop: 10 }} onClick={() => setShowAll((v) => !v)}>
          {showAll ? "Show top only" : `Show all ${rows.length}`}
        </button>
      )}
    </div>
  );
}
