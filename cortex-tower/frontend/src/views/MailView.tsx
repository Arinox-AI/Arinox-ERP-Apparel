import { MailPanel } from "../components/MailPanel";

/* Outbound Mail — approve, edit or reject grounded emails before they are sent. */
export function MailView({ notify }: { notify: (msg: string) => void }) {
  return <MailPanel notify={notify} />;
}
