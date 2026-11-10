/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  /* Preflight is OFF on purpose: this project already ships two hand-written style sheets
     (index.css for the operations screens, cx/cx.css for the tower shell) with their own reset.
     Loading Preflight as well would strip their list/heading defaults and silently move the
     layout of ~240 legacy classes. The few Preflight rules shadcn actually needs are restored
     in `@layer base` inside src/shadcn.css. */
  corePlugins: { preflight: false },
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--sh-border))",
        input: "hsl(var(--sh-input))",
        ring: "hsl(var(--sh-ring))",
        background: "hsl(var(--sh-background))",
        foreground: "hsl(var(--sh-foreground))",
        primary: { DEFAULT: "hsl(var(--sh-primary))", foreground: "hsl(var(--sh-primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--sh-secondary))", foreground: "hsl(var(--sh-secondary-foreground))" },
        destructive: { DEFAULT: "hsl(var(--sh-destructive))", foreground: "hsl(var(--sh-destructive-foreground))" },
        muted: { DEFAULT: "hsl(var(--sh-muted))", foreground: "hsl(var(--sh-muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--sh-accent))", foreground: "hsl(var(--sh-accent-foreground))" },
        popover: { DEFAULT: "hsl(var(--sh-popover))", foreground: "hsl(var(--sh-popover-foreground))" },
        card: { DEFAULT: "hsl(var(--sh-card))", foreground: "hsl(var(--sh-card-foreground))" },
        success: { DEFAULT: "hsl(var(--sh-success))", foreground: "hsl(var(--sh-success-foreground))" },
        warning: { DEFAULT: "hsl(var(--sh-warning))", foreground: "hsl(var(--sh-warning-foreground))" },
      },
      borderRadius: {
        lg: "var(--sh-radius)",
        md: "calc(var(--sh-radius) - 2px)",
        sm: "calc(var(--sh-radius) - 4px)",
      },
      fontFamily: {
        sans: ["Inter", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "SF Mono", "Menlo", "Consolas", "Liberation Mono", "monospace"],
      },
      keyframes: {
        "accordion-down": { from: { height: "0" }, to: { height: "var(--radix-accordion-content-height)" } },
        "accordion-up": { from: { height: "var(--radix-accordion-content-height)" }, to: { height: "0" } },
        "fade-in": { from: { opacity: "0", transform: "translateY(4px)" }, to: { opacity: "1", transform: "none" } },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "fade-in": "fade-in 0.18s ease-out",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
