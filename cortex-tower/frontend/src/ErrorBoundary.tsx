import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

/**
 * One screen failing must never blank the whole Tower (2026-11-07). A render error is caught here,
 * shown in plain words, and the person can go back to Today or reload — the rest of the app is intact.
 * `scope` lets a single screen be wrapped too, so only that screen shows the message.
 */
export class ErrorBoundary extends Component<{ children: ReactNode; scope?: string; resetKey?: string }, { err: Error | null }> {
  state = { err: null as Error | null };

  static getDerivedStateFromError(err: Error) { return { err }; }

  componentDidCatch(err: Error, info: ErrorInfo) {
    // the console is the only place a stack belongs; the person gets a sentence
    console.error("Cortex Tower screen error", this.props.scope || "app", err, info?.componentStack);
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (this.state.err && prev.resetKey !== this.props.resetKey) this.setState({ err: null });
  }

  render() {
    if (!this.state.err) return this.props.children;
    const whole = !this.props.scope;
    return (
      <div style={{ minHeight: whole ? "100dvh" : 0, display: "grid", placeItems: "center", padding: 24,
                    background: whole ? "var(--cx-bg, #f6f7f9)" : "transparent", color: "var(--cx-ink, #111827)",
                    fontFamily: "Inter, system-ui, sans-serif" }}>
        <div style={{ maxWidth: 460, textAlign: "center", background: "var(--cx-card, #ffffff)", border: "1px solid var(--cx-line, #e7eaf0)",
                      borderRadius: 14, padding: "28px 24px" }}>
          <div style={{ fontSize: 30, marginBottom: 8 }} aria-hidden="true">⚠︎</div>
          <h2 style={{ fontSize: 17, margin: "0 0 6px" }}>{whole ? "Something went wrong" : `The ${this.props.scope} screen hit a problem`}</h2>
          <p style={{ fontSize: 14, color: "var(--cx-ink-2, #4b5563)", margin: "0 0 18px" }}>
            {whole ? "The Tower could not draw this page." : "Other screens still work."} Nothing was changed in the ERP.
          </p>
          <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
            {!whole && <button className="cx-btn cx-btn--gray" onClick={() => { location.hash = "#/today"; this.setState({ err: null }); }}>Go to Today</button>}
            <button className="cx-btn" onClick={() => location.reload()}>Reload</button>
          </div>
          <details style={{ marginTop: 14, fontSize: 12, color: "var(--cx-ink-3, #6b7280)", textAlign: "left" }}>
            <summary style={{ cursor: "pointer" }}>Technical detail</summary>
            <code style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{String(this.state.err?.message || this.state.err)}</code>
          </details>
        </div>
      </div>
    );
  }
}
