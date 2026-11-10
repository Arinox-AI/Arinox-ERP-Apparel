import { useEffect, useState } from "react";
import { Plus, Search, UserCheck } from "lucide-react";
import { Btn, Field, Input, Note, Select, call, useToast } from "./kit";
import type { R } from "./kit";

/** Pick an ERP customer, or add one when the buyer is new. ``onPicked`` gets the ERP customer name. */
export function CustomerPicker(p: { value?: string; suggestName?: string; email?: string; contactName?: string; dealId?: number; onPicked: (customer: string, name?: string) => void; compact?: boolean }) {
  const toast = useToast();
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<R[]>([]);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ customer_name: p.suggestName || "", email: p.email || "", currency: "USD", country: "", contact_name: p.contactName || "" });
  const [err, setErr] = useState("");

  useEffect(() => {
    const t = window.setTimeout(async () => {
      const r = await call("customer_list", { q, limit: 12 });
      if (r.ok) setRows(r.customers || []);
    }, q ? 250 : 0);
    return () => window.clearTimeout(t);
  }, [q]);
  useEffect(() => { setForm((f) => ({ ...f, customer_name: f.customer_name || p.suggestName || "", email: f.email || p.email || "" })); }, [p.suggestName, p.email]);

  const add = async () => {
    setBusy(true); setErr("");
    const r = await call("customer_create", { ...form, deal_id: p.dealId || 0 });
    setBusy(false);
    if (!r.ok) { setErr(r.error || "Could not add the customer."); return; }
    toast(r.existing ? `${r.customer} already existed and is now linked.` : `Customer ${r.customer} added to the ERP.`);
    setAdding(false);
    p.onPicked(r.customer, form.customer_name);
  };

  if (adding) {
    return (
      <div className="ws-card" style={{ padding: 14 }}>
        <div className="ws-row ws-row--between" style={{ marginBottom: 10 }}><b>New customer</b><Btn kind="plain" sm onClick={() => setAdding(false)}>Cancel</Btn></div>
        <div className="ws-form" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <Field label="Company name" wide><Input value={form.customer_name} onChange={(v) => setForm({ ...form, customer_name: v })} placeholder="e.g. Harbor & Lane Apparel Co." autoFocus /></Field>
          <Field label="Buyer e-mail" hint="Future mail from this address is linked automatically."><Input value={form.email} onChange={(v) => setForm({ ...form, email: v })} /></Field>
          <Field label="Contact name"><Input value={form.contact_name} onChange={(v) => setForm({ ...form, contact_name: v })} /></Field>
          <Field label="Currency"><Select value={form.currency} onChange={(v) => setForm({ ...form, currency: v })} options={["USD", "EUR", "GBP", "INR", "VND", "HKD", "CNY", "AED"]} /></Field>
          <Field label="Country"><Input value={form.country} onChange={(v) => setForm({ ...form, country: v })} placeholder="optional" /></Field>
        </div>
        {err && <div className="ws-mt-s"><Note tone="bad">{err}</Note></div>}
        <div className="ws-row ws-mt" style={{ justifyContent: "flex-end" }}><Btn kind="primary" busy={busy} disabled={form.customer_name.trim().length < 2} onClick={add}><Plus size={14} /> Add to the ERP</Btn></div>
      </div>
    );
  }
  return (
    <div style={{ display: "grid", gap: 8 }}>
      {p.value && <div className="ws-row"><UserCheck size={15} color="var(--ws-ok)" /><b>{p.value}</b></div>}
      <div style={{ position: "relative" }}>
        <Search size={14} style={{ position: "absolute", left: 10, top: 10, color: "var(--ws-faint)" }} />
        <input className="ws-input" style={{ paddingLeft: 30 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder={p.value ? "Change customer…" : "Search ERP customers…"} aria-label="Search customers" />
      </div>
      <div className="ws-card" style={{ maxHeight: p.compact ? 170 : 240, overflowY: "auto" }}>
        {rows.length === 0 && <div className="ws-small ws-muted" style={{ padding: 10 }}>{q ? "No customer by that name." : "No customers in the ERP yet."}</div>}
        {rows.map((c) => (
          <div key={c.name} className="ws-list-row" onClick={() => p.onPicked(c.name, c.customer_name)} style={{ padding: "8px 12px" }}>
            <span className="ws-ellipsis" style={{ flex: 1 }}>{c.customer_name || c.name}</span>
            <span className="ws-small ws-muted">{c.default_currency || ""}</span>
          </div>
        ))}
      </div>
      <Btn kind="ghost" sm onClick={() => { setAdding(true); setForm((f) => ({ ...f, customer_name: f.customer_name || q })); }}><Plus size={14} /> Add a new customer</Btn>
    </div>
  );
}
