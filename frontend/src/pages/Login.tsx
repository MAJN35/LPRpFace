import { FormEvent, useState } from "react";
import { LogIn } from "lucide-react";
import { ApiError, Session, login } from "../api";
import { Btn } from "../components/Button";
import { Logo } from "../components/Logo";
import { LangSwitch } from "../components/LangSwitch";
import { useI18n } from "../i18n";

export function Login({ onDone }: { onDone: (s: Session) => void }) {
  const { t } = useI18n();
  const [user, setUser] = useState(""); const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  async function submit(ev: FormEvent) {
    ev.preventDefault(); setBusy(true); setErr(null);
    try { onDone(await login(user, pw)); }
    catch (e) { setErr(e instanceof ApiError && e.status === 401 ? t("login.wrong") : t("login.down")); }
    finally { setBusy(false); }
  }
  return (
    <main style={{ display: "grid", placeItems: "center", minHeight: "100vh", padding: 16 }}>
      <form className="card raised" onSubmit={submit} style={{ width: "min(360px, 100%)", display: "grid", gap: 14 }}>
        <div className="login-logo"><Logo size={44} /></div>
        <h1>{t("login.title")}</h1>
        <label>{t("login.user")}<input className="inset" autoComplete="username" value={user} onChange={(e) => setUser(e.target.value)} required /></label>
        <label>{t("login.password")}<input className="inset" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} required /></label>
        {err && <p role="alert" className="bad" style={{ margin: 0 }}>{err}</p>}
        <Btn type="submit" variant="primary" icon={LogIn} flipRtl state={busy ? "busy" : err ? "error" : "idle"}>{busy ? t("login.busy") : t("login.submit")}</Btn>
        <LangSwitch />
      </form>
    </main>
  );
}
