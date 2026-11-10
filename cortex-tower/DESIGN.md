---
version: alpha
name: Cortex Tower — Professional Slate
description: Professional Slate is a conservative, high-trust theme on a light gray background ({colors.background}) with dark navy ({colors.primary}) as the dominant color. The design communicates formality and authority — appropriate for legal, finance, healthcare, and government-adjacent software where trust and legibility are paramount. Typography uses Source Serif 4 for headings and Inter for body — the serif creates gravitas without going old-fashioned. Cards are clean white panels. Palette is strictly neutral with no decorative color. Inspired by legal tech (Clio, Harvey), finance (Bloomberg, Refinitiv), healthcare portals.

colors:
  primary: "#1e293b"
  primary-hover: "#0f172a"
  primary-light: "#e8edf3"
  on-primary: "#ffffff"
  secondary: "#334155"
  background: "#f1f5f9"
  surface: "#ffffff"
  surface-secondary: "#f8fafc"
  border: "#e2e8f0"
  border-strong: "#cbd5e1"
  text: "#0f172a"
  text-secondary: "#334155"
  text-muted: "#64748b"
  text-placeholder: "#94a3b8"
  link: "#2563eb"
  accent-action: "#2563eb"
  accent-action-light: "#dbeafe"
  semantic-success: "#166534"
  semantic-success-light: "#dcfce7"
  semantic-error: "#991b1b"
  semantic-error-light: "#fee2e2"
  semantic-warning: "#92400e"
  semantic-warning-light: "#fef3c7"
  semantic-pending: "#1e40af"
  semantic-pending-light: "#dbeafe"
  status-active: "#166534"
  status-inactive: "#64748b"
  status-pending: "#92400e"

typography:
  display:
    fontFamily: Source Serif 4
    fontSize: 44px
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: -0.5px
  heading-1:
    fontFamily: Source Serif 4
    fontSize: 34px
    fontWeight: 600
    lineHeight: 1.15
  heading-2:
    fontFamily: Source Serif 4
    fontSize: 26px
    fontWeight: 600
    lineHeight: 1.2
  heading-3:
    fontFamily: Source Serif 4
    fontSize: 20px
    fontWeight: 600
    lineHeight: 1.3
  heading-4:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: 600
    lineHeight: 1.4
  body-lg:
    fontFamily: Inter
    fontSize: 17px
    fontWeight: 400
    lineHeight: 1.75
  body:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: 400
    lineHeight: 1.7
  body-medium:
    fontFamily: Inter
    fontSize: 15px
    fontWeight: 500
    lineHeight: 1.7
  body-sm:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.6
  caption:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.5
  button:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: 500
    lineHeight: 1.2
  label:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: 0.3px
  legal:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.7
    color: "{colors.text-muted}"

rounded:
  xs: 2px
  sm: 4px
  md: 6px
  lg: 8px
  xl: 12px
  full: 9999px

spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 20px
  xxl: 28px
  xxxl: 40px
  section: 56px

components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: "10px 20px"
    border: "none"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.primary}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: "10px 20px"
    border: "1px solid {colors.border-strong}"
  button-secondary-hover:
    backgroundColor: "{colors.surface-secondary}"
  button-action:
    backgroundColor: "{colors.accent-action}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: "10px 20px"
  button-destructive:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.semantic-error}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: "10px 20px"
    border: "1px solid {colors.semantic-error}"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.lg}"
    border: "1px solid {colors.border}"
    padding: "{spacing.xxl}"
  card-section:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.lg}"
    border: "1px solid {colors.border}"
    padding: "{spacing.xl}"
  info-block:
    backgroundColor: "{colors.surface-secondary}"
    rounded: "{rounded.lg}"
    border: "1px solid {colors.border}"
    borderLeft: "3px solid {colors.secondary}"
    padding: "{spacing.xl}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    border: "1px solid {colors.border-strong}"
    padding: "{spacing.md} {spacing.lg}"
    height: 42px
  input-focused:
    border: "1px solid {colors.accent-action}"
    boxShadow: "0 0 0 3px {colors.accent-action-light}"
  textarea:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    border: "1px solid {colors.border-strong}"
    padding: "{spacing.md} {spacing.lg}"
    minHeight: 100px
  badge-active:
    backgroundColor: "{colors.semantic-success-light}"
    textColor: "{colors.semantic-success}"
    typography: "{typography.label}"
    rounded: "{rounded.full}"
    padding: "3px 10px"
  badge-pending:
    backgroundColor: "{colors.semantic-warning-light}"
    textColor: "{colors.semantic-warning}"
    typography: "{typography.label}"
    rounded: "{rounded.full}"
    padding: "3px 10px"
  badge-inactive:
    backgroundColor: "{colors.surface-secondary}"
    textColor: "{colors.text-muted}"
    typography: "{typography.label}"
    rounded: "{rounded.full}"
    padding: "3px 10px"
    border: "1px solid {colors.border}"
  badge-error:
    backgroundColor: "{colors.semantic-error-light}"
    textColor: "{colors.semantic-error}"
    typography: "{typography.label}"
    rounded: "{rounded.full}"
    padding: "3px 10px"
  step-indicator:
    backgroundColor: "{colors.border}"
    textColor: "{colors.text-muted}"
    rounded: "{rounded.full}"
    size: 28px
    typography: "{typography.label}"
  step-indicator-active:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
  step-indicator-complete:
    backgroundColor: "{colors.semantic-success}"
    textColor: "#ffffff"
  sidebar:
    backgroundColor: "{colors.surface}"
    borderRight: "1px solid {colors.border}"
    width: 260px
  sidebar-item:
    backgroundColor: "transparent"
    textColor: "{colors.text-secondary}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "8px 14px"
  sidebar-item-active:
    backgroundColor: "{colors.primary-light}"
    textColor: "{colors.primary}"
  table-header-cell:
    backgroundColor: "{colors.surface-secondary}"
    textColor: "{colors.text-muted}"
    typography: "{typography.label}"
    padding: "12px 16px"
    borderBottom: "2px solid {colors.border-strong}"
  table-row:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.body-sm}"
    padding: "12px 16px"
    borderBottom: "1px solid {colors.border}"
  table-row-hover:
    backgroundColor: "{colors.surface-secondary}"
  divider:
    border: "none"
    borderTop: "1px solid {colors.border}"
    margin: "{spacing.xxl} 0"
---

## Overview

Professional Slate uses the visual language of formal documents: serif headings (Source Serif 4) for gravity, Inter body text for readability, strict neutral palette, and rectangular geometry. The light gray background (`#f1f5f9`) distinguishes it from a blank white document, adding subtle depth. White cards on the gray canvas create natural panel separation without decorative elements. Blue (`{colors.accent-action}`) appears only for interactive actions and links — never as decoration. Status badges (active/pending/inactive/error) are first-class components since legal/finance/healthcare apps rely heavily on workflow state display.

**Key characteristics:**
- Light gray canvas `#f1f5f9` — formal document feel, not blank white
- Dark navy `#1e293b` for primary CTAs — authoritative, not casual blue
- Source Serif 4 for H1–H3 — professional gravitas; Inter for H4 and below
- `info-block` with left border — document callout/note pattern
- Step indicator component for multi-step forms/processes
- Comprehensive status badge system (active/pending/inactive/error)
- Legal text typography style (`{typography.legal}`)

## Typography

**Source Serif 4**: Load from Google Fonts at weight 600.
**Inter**: Load from Google Fonts at weights 400, 500, 600.

The serif/sans hybrid is intentional — headings feel like official document titles; body stays scan-readable.

## Do's and Don'ts

### Do
- Use Source Serif 4 for page and section headings — it establishes the formal register
- Use status badges consistently — these apps always show workflow states
- Use `step-indicator` for multi-step forms (onboarding, case creation, contract review)
- Use `info-block` with left border for important notices, legal disclaimers, warnings
- Reserve blue (`{colors.accent-action}`) for interactive elements only (links, focus, form submit)

### Don't
- Don't use bright colors as decorative elements — only status-semantic usage
- Don't use pill-shaped buttons — rectangular form is intentional
- Don't use Source Serif 4 below H3 — switch to Inter for smaller text
- Don't add visual decoration (gradients, patterns, illustrations) — this theme is document-first

---

## Applied in Cortex Tower (2026-11-07)

* Tokens live in `frontend/src/app/theme.css` (`--ws-*`), loaded last; the older `--cx-*` tokens are re-pointed at them so
  the legacy screens (records, reports, T&A, risks) share one palette.
* Headings use Inter (bundled) instead of Source Serif 4: the workspace is a dense operations tool and the serif was not
  bundled. Everything else (colours, radii, spacing, semantic colours) is the template as written.
* Navy sidebar (`primary`), one blue for actions (`accent-action`), semantic colours only for status: deal stages,
  mail labels, margin below floor, overdue.
