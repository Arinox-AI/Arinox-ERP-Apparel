import { IntakePanel } from "../components/IntakePanel";

/* Order intake — a buyer's own document, read, proved field by field, and turned
   into ERP drafts at a human gate. */
export function IntakeView({ notify, initialRunId }: {
  notify: (msg: string, opts?: { sticky?: boolean; link?: { url: string; label: string } }) => void;
  initialRunId?: number;
}) {
  return <IntakePanel notify={notify} initialRunId={initialRunId} />;
}
