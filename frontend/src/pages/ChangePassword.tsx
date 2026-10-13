import { FormEvent, useState } from "react";
import { KeyRound } from "lucide-react";
import { ApiError, api, json } from "../api";
import { Btn } from "../components/Button";
import { Logo } from "../components/Logo";
import { useI18n } from "../i18n";

// Shown after sign-in while the account must change its password (the default admin before first use).
export function ChangePassword({ onDone }: { onDone: () => void }) {
  const { t } = useI18n();
  const [cur, setCur] = useState(""); const [pw, setPw] = useState(""); const [pw2, setPw2] = useState("");
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  async function submit(ev: FormEvent) {
    ev.preventDefault(); setErr(null);
    if (pw.length < 12) return setErr(t("pw.short"));
    if (pw !== pw2) return setErr(t("pw.mismatch"));
    setBusy(true);
    try { await api("/auth/change-password", json({ current_password: cur, new_password: pw })); onDone(); }
    catch (e) { setErr(e instanceof ApiError ? (e.status === 403 ? t("pw.wrong") : e.message) : "Failed"); }
    finally { setBusy(false); }
  }
  return (
    <main style={{ display: "grid", placeItems: "center", minHeight: "100vh", padding: 16 }}>
      <form className="card raised" onSubmit={submit} aria-label={t("pw.title")} style={{ width: "min(400px, 100%)", display: "grid", gap: 14 }}>
        <div className="login-logo"><Logo size={40} /></div>
        <h1>{t("pw.title")}</h1>
        <p className="muted" style={{ margin: 0 }}>{t("pw.text")}</p>
        <label>{t("pw.current")}<input className="inset" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} required /></label>
        <label>{t("pw.new")}<input className="inset" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} required minLength={12} /></label>
        <label>{t("pw.repeat")}<input className="inset" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} required /></label>
        {err && <p role="alert" className="bad" style={{ margin: 0 }}>{err}</p>}
        <Btn type="submit" variant="primary" icon={KeyRound} state={busy ? "busy" : "idle"}>{busy ? t("pw.busy") : t("pw.submit")}</Btn>
      </form>
    </main>
  );
}
