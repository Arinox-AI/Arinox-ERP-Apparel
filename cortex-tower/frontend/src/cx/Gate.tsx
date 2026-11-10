import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { RefreshCw, WifiOff } from "lucide-react";
import { call, setToken } from "./api";
import type { R } from "./api";
import { Btn, Note } from "./ui";
import { Boot, bootSteps } from "./Boot";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import "./cx.css";

/** Who is this? KOGO signs people in; outside KOGO there is a password sign-in.
 *
 *  Two rules, both learned the hard way:
 *  1. Nothing renders until we know who the caller is — but the app must never sit on the
 *     opening screen forever. If the platform does not answer, say so and offer Retry.
 *  2. The opening screen and the sign-in card are LIGHT. They are the first thing anyone sees.
 */
export function Gate({ children }: { children: (me: R) => ReactNode }) {
  const [me, setMe] = useState<R | null>(null);
  const [err, setErr] = useState("");
  const [slow, setSlow] = useState(false);
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [loginErr, setLoginErr] = useState("");
  const [busy, setBusy] = useState(false);

  const check = useCallback(async () => {
    setErr("");
    setSlow(false);
    try {
      const r = await call("kogo_me");
      if (!r || r.ok === false) {
        setMe(null);
        setErr(r?.error || "The platform did not answer.");
        return;
      }
      setMe(r);
    } catch (e) {
      setMe(null);
      setErr(String((e as Error)?.message || e || "The platform did not answer."));
    }
  }, []);

  useEffect(() => { void check(); }, [check]);

  /* A watchdog: a slow gateway shows the same screen with "still connecting" instead of nothing. */
  useEffect(() => {
    if (me || err) return;
    const t = window.setTimeout(() => setSlow(true), 9000);
    return () => window.clearTimeout(t);
  }, [me, err]);

  const login = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setLoginErr("");
    const r = await call("kogo_login", { email, password: pw });
    setBusy(false);
    if (r.token) { setToken(r.token); void check(); } else setLoginErr(r.error || "Could not sign in.");
  };

  if (err) return <Offline error={err} slows={slow} onRetry={() => void check()} />;
  if (!me) return <Boot steps={bootSteps(0)} status={slow ? "Still connecting to the platform…" : "Checking your session"} />;

  if (me.registered) return <>{children(me)}</>;

  return (
    <div className="cx-auth">
      <Card className="w-[min(420px,100%)] shadow-[0_18px_50px_rgba(16,24,40,0.10)]">
        <CardHeader className="pb-2">
          <div className="mb-4 flex items-center gap-2.5">
            <div className="cx-mark">CT</div>
            <div className="cx-wordmark">
              <span className="cx-wordmark__t">Cortex Tower</span>
              <span className="cx-wordmark__s">ERP command centre</span>
            </div>
          </div>
          <CardTitle className="text-xl">Sign in</CardTitle>
          <CardDescription>The command centre for the live ERP.</CardDescription>
        </CardHeader>
        <CardContent>
          {me.reason === "not_registered" ? (
            <>
              <Note tone="warn">
                You’re signed in as <b>{me.email}</b>, but you haven’t been added to this app yet.
                Ask an administrator to add you.
              </Note>
              <Btn kind="gray" block onClick={() => void check()}>Check again</Btn>
            </>
          ) : (
            <form onSubmit={login} className="grid gap-3.5">
              <div className="grid gap-1.5">
                <Label htmlFor="e" className="text-[12.5px] text-[#4b5563]">Email</Label>
                <Input id="e" type="email" autoComplete="username" value={email}
                  onChange={(x) => setEmail(x.target.value)} required className="h-9" />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="p" className="text-[12.5px] text-[#4b5563]">Password</Label>
                <Input id="p" type="password" autoComplete="current-password" value={pw}
                  onChange={(x) => setPw(x.target.value)} required className="h-9" />
              </div>
              {loginErr && <Note tone="bad">{loginErr}</Note>}
              <Btn type="submit" block busy={busy}>Sign in</Btn>
              <p className="text-center text-[12px] text-[#9aa3af]">Opened from KOGO? You’re signed in automatically.</p>
            </form>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/** The platform did not answer. Say it plainly, offer Retry, and never leave a spinner spinning. */
function Offline({ error, slows, onRetry }: { error: string; slows: boolean; onRetry: () => void }) {
  return (
    <div className="cx-auth">
      <Card className="w-[min(460px,100%)]">
        <CardHeader className="pb-3">
          <div className="mb-3 flex items-center gap-3">
            <div className="grid h-9 w-9 place-items-center rounded-lg bg-amber-50 text-amber-600">
              <WifiOff size={17} />
            </div>
            <CardTitle className="text-base">Can’t reach the platform</CardTitle>
          </div>
          <CardDescription>
            The app could not open a session. Nothing has been written anywhere.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          <pre className="overflow-x-auto rounded-lg border border-[#e7eaf0] bg-[#f8f9fb] px-3 py-2 font-mono text-[11.5px] text-[#4b5563]">
            {error}
          </pre>
          {slows && <p className="text-[12px] text-[#9aa3af]">The gateway is slow to answer. It may still come back.</p>}
          <div className="flex items-center gap-2">
            <Btn onClick={onRetry}><RefreshCw size={14} /> Try again</Btn>
            <span className="text-[12px] text-[#9aa3af]">or reload the page</span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
