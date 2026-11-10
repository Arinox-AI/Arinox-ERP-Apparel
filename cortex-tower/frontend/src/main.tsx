import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { ErrorBoundary } from "./ErrorBoundary";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
/* Order matters. shadcn/Tailwind first (tokens + utilities), then the two older sheets so the
   operations screens and the tower shell keep their own rules where they speak. */
import "./shadcn.css";
import "./index.css";
import "./tna/index.css";
import "./cx/cx.css";
import "./app/theme.css";   /* last: the workspace design system, also re-points the older tokens */

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
