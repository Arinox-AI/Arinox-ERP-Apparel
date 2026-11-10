// ─────────────────────────────────────────────────────────────────────────────
// TnA Calendar — rendered as a single tab inside the Cortex Operations Control
// Tower. The whole standalone TnA application (Plan · Board · Calendar ·
// Program + the new-order intake inbox) now lives here.
//
//  • Its backend functions are registered in THIS project (backend/tna_app/),
//    so the embedded UI calls the same middleware project as the rest of the app.
//  • Its entire stylesheet is scoped under `.tna-root` (see tna/index.css), so
//    the two design systems cannot collide.
// ─────────────────────────────────────────────────────────────────────────────
import TnaApp from "../tna/App";

export function TnaView() {
  return (
    <div className="tna-root">
      <TnaApp />
    </div>
  );
}

export default TnaView;
