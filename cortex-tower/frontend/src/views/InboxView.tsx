import { InboxPanel } from "../components/InboxPanel";

/* Inbox — the raw mailbox: read, understood and flagged.
   The document-level decision (approve / reject / roll back) lives in Order intake;
   this screen links straight there and offers the same buttons on a mail. */
export function InboxView({ notify, onOpenIntake }: {
  notify: (msg: string, opts?: { sticky?: boolean; link?: { url: string; label: string } }) => void;
  onOpenIntake?: (runId?: number) => void;
}) {
  return <InboxPanel notify={notify} onOpenIntake={onOpenIntake} />;
}
