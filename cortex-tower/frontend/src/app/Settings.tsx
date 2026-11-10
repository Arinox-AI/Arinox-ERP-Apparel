import { useEffect, useState } from "react";
import { Mail } from "lucide-react";
import { callApi } from "../services/api";
import { AdminView, ApprovalsView, SyncView, TsrView } from "../cx/views/Views";
import { Badge, Btn, Card, Field, Head, Input, Loading, Note, useToast } from "./kit";
import type { R } from "./kit";

const TABS = [{ k: "mail", l: "Mailbox" }, { k: "users", l: "Users & roles" }, { k: "sync", l: "ERP sync" }, { k: "rules", l: "Business rules" }, { k: "approvals", l: "Approvals" }];

async function legacy(name: string, params: R = {}): Promise<R> {
  try {
    const r = await callApi(name, params);
    return (r && r.data && typeof r.data === "object" ? r.data : { ok: false, error: r?.message || "No answer." }) as R;
  } catch {
    return { ok: false, error: "Can't reach the server." };
  }
}

export function Settings({ tab, go }: { tab?: string; go: (p: string) => void }) {
  const t = TABS.some((x) => x.k === tab) ? tab! : "mail";
  return (
    <div className="ws-page">
      <Head title="Settings" sub="The mailbox the inbox reads and sends from, who can do what, and the link to the ERP." />
      <div className="ws-tabs">{TABS.map((x) => <button key={x.k} className={`ws-tab${t === x.k ? " is-on" : ""}`} onClick={() => go(`settings/${x.k}`)}>{x.l}</button>)}</div>
      {t === "mail" && <MailSettings />}
      {t === "users" && <div className="cx-legacy"><AdminView /></div>}
      {t === "sync" && <div className="cx-legacy"><SyncView /></div>}
      {t === "rules" && <div className="cx-legacy"><TsrView /></div>}
      {t === "approvals" && <div className="cx-legacy"><ApprovalsView /></div>}
    </div>
  );
}

function MailSettings() {
  const toast = useToast();
  const [s, setS] = useState<R | null>(null);
  const [state, setState] = useState<R>({});
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState("");
  const load = async () => {
    const r = await legacy("get_mail_settings");
    setS(r.settings || {}); setState(r);
  };
  useEffect(() => { void load(); }, []);
  if (!s) return <Loading rows={3} />;
  const save = async () => {
    setBusy("save");
    const r = await legacy("save_mail_settings", { email_account: s.email_account, from_name: s.from_name, smtp_host: s.smtp_host, smtp_port: Number(s.smtp_port) || 587, use_tls: 1, enabled: 1, ...(pw ? { password: pw } : {}) });
    setBusy("");
    if (r.ok === false || r.error) { toast(r.error || "Not saved.", "bad"); return; }
    setPw(""); toast("Mailbox saved."); void load();
  };
  const test = async () => {
    setBusy("test");
    const r = await legacy("test_mail_settings", {});
    setBusy("");
    toast(r.ok ? `Test mail sent to ${s.email_account}.` : r.error || "The test failed.", r.ok ? "ok" : "bad");
  };
  return (
    <div className="ws-grid ws-grid--side">
      <Card title="Company mailbox" right={state.connected ? <Badge tone="ok">Connected</Badge> : <Badge tone="warn">Not connected</Badge>}>
        {state.problem === "password_unreadable" && <div style={{ marginBottom: 12 }}><Note tone="bad">{state.message}</Note></div>}
        <div className="ws-form" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <Field label="Mailbox (Gmail address)"><Input value={s.email_account} onChange={(v) => setS({ ...s, email_account: v })} placeholder="sales@yourcompany.com" /></Field>
          <Field label="Name shown to buyers"><Input value={s.from_name} onChange={(v) => setS({ ...s, from_name: v })} placeholder="Cortex Textile Limited" /></Field>
          <Field label="App password" hint={s.password_set ? "Saved. Type a new one only to change it." : "Google Account → Security → App passwords."}><Input type="password" value={pw} onChange={setPw} placeholder={s.password_set ? "••••••••" : ""} /></Field>
          <Field label="SMTP server"><Input value={s.smtp_host} onChange={(v) => setS({ ...s, smtp_host: v })} /></Field>
        </div>
        <div className="ws-row ws-mt" style={{ justifyContent: "flex-end" }}>
          <Btn busy={busy === "test"} onClick={test} disabled={!state.connected}><Mail size={14} /> Send a test</Btn>
          <Btn kind="primary" busy={busy === "save"} onClick={save} disabled={!s.email_account}>Save</Btn>
        </div>
      </Card>
      <Card title="How the inbox works">
        <div className="ws-small" style={{ display: "grid", gap: 8 }}>
          <div>The inbox reads this mailbox every two minutes while it is open, and when you press refresh.</div>
          <div>Every reply you send from the tower goes into the same conversation, so the buyer's answer comes back to it.</div>
          <div>On Gmail, replies you send from Gmail itself also appear in the conversation.</div>
          <div>The password is stored encrypted and is never shown again.</div>
        </div>
      </Card>
    </div>
  );
}
