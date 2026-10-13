import { FormEvent, useState } from "react";
import { ApiError, Session, login } from "../api";

export function Login({ onDone }: { onDone: (s: Session) => void }) {
  const [user, setUser] = useState(""); const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  async function submit(ev: FormEvent) {
    ev.preventDefault(); setBusy(true); setErr(null);
    try { onDone(await login(user, pw)); }
    catch (e) { setErr(e instanceof ApiError && e.status === 401 ? "Wrong username or password." : "Cannot reach the backend."); }
    finally { setBusy(false); }
  }
  return (
    <main style={{ display: "grid", placeItems: "center", minHeight: "100vh", padding: 16 }}>
      <form className="card raised" onSubmit={submit} style={{ width: "min(360px, 100%)", display: "grid", gap: 14 }}>
        <h1>Sign in</h1>
        <label>Username<input className="inset" autoComplete="username" value={user} onChange={(e) => setUser(e.target.value)} required /></label>
        <label>Password<input className="inset" type="password" autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} required /></label>
        {err && <p role="alert" className="bad" style={{ margin: 0 }}>{err}</p>}
        <button type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </main>
  );
}
