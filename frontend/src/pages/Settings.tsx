import { FormEvent, useState } from "react";
import { ApiError, Camera, api } from "../api";
import { StateView, useApi } from "../components/ui";

type Job = { job_id: string; status?: string; events?: { plate_string_fa: string; plate_string_latin: string; is_valid: boolean | null }[]; error?: string };

export function Settings({ role, onTheme }: { role: string; onTheme: (t: "light" | "dark" | "auto") => void }) {
  const cams = useApi<Camera[]>("/cameras");
  const canEdit = role === "admin" || role === "operator";
  const [msg, setMsg] = useState<string | null>(null);
  const [form, setForm] = useState({ id: "", name: "", type: "rtsp", uri: "", max_fps: "10" });
  const [job, setJob] = useState<Job | null>(null);
  async function act(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try { await fn(); setMsg(ok); window.setTimeout(cams.reload, 800); } catch (e) { setMsg(e instanceof ApiError ? `Failed: ${e.message}` : "Failed"); }
  }
  async function add(e: FormEvent) {
    e.preventDefault();
    await act(() => api("/cameras", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...form, max_fps: Number(form.max_fps) }) }), `Source ${form.id} added.`);
  }
  async function upload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const file = (e.currentTarget.elements.namedItem("img") as HTMLInputElement).files?.[0];
    if (!file) return;
    const fd = new FormData(); fd.append("file", file);
    try {
      const r = await api<Job>("/images", { method: "POST", body: fd });
      setJob(r);
      for (let i = 0; i < 30; i++) {
        await new Promise((res) => setTimeout(res, 1000));
        const s = await api<Job>(`/images/${r.job_id}`);
        if (s.status && s.status !== "queued") { setJob({ ...s, job_id: r.job_id }); return; }
      }
      setJob({ job_id: r.job_id, status: "error", error: "no result after 30 s" });
    } catch (err) { setJob({ job_id: "", status: "error", error: err instanceof ApiError ? err.message : "upload failed" }); }
  }
  return (
    <>
      <h1>Settings</h1><p className="sub">Signed in as {role}. Camera passwords belong in the server environment, never in the URL shown here.</p>
      {msg && <div className="banner inset" role="status">{msg}</div>}
      <section className="card raised" aria-labelledby="cam-h"><h2 id="cam-h">Sources</h2>
        <StateView loading={cams.loading} error={cams.error} empty={!cams.data?.length} emptyText="No sources." onRetry={cams.reload}>
          <div className="table-wrap"><table><thead><tr><th>ID</th><th>Name</th><th>Type</th><th>URI</th><th>Max fps</th><th>Face blur</th><th>Actions</th></tr></thead><tbody>
            {cams.data?.map((c) => (
              <tr key={c.id}><td>{c.id}</td><td>{c.name}</td><td>{c.type}</td><td className="muted">{c.uri}</td><td>{c.max_fps || "–"}</td><td>{c.face_blur ? "on" : "off"}</td>
                <td className="row">{canEdit && <>
                  <button type="button" onClick={() => act(() => api(`/cameras/${c.id}/${c.enabled ? "disable" : "enable"}`, { method: "POST" }), `${c.id} ${c.enabled ? "disabled" : "enabled"}.`)}>{c.enabled ? "Disable" : "Enable"}</button>
                  <button type="button" onClick={() => act(() => api(`/cameras/${c.id}`, { method: "DELETE" }), `${c.id} removed.`)}>Remove</button></>}</td></tr>
            ))}
          </tbody></table></div>
        </StateView>
        {canEdit && (
          <form onSubmit={add} className="filters" style={{ marginTop: 16 }} aria-label="Add source">
            <label>ID<input className="inset" required pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} /></label>
            <label>Name<input className="inset" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <label>Type<select className="inset" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>{["rtsp", "rtmp", "http", "hls", "file", "usb", "csi"].map((t) => <option key={t}>{t}</option>)}</select></label>
            <label>URI<input className="inset" required value={form.uri} onChange={(e) => setForm({ ...form, uri: e.target.value })} /></label>
            <label>Max fps<input className="inset" type="number" min="0" max="60" value={form.max_fps} onChange={(e) => setForm({ ...form, max_fps: e.target.value })} /></label>
            <button type="submit">Add source</button>
          </form>
        )}
      </section>
      {canEdit && (
        <section className="card raised" aria-labelledby="img-h"><h2 id="img-h">Recognize an image</h2>
          <form onSubmit={upload} className="row"><label>JPEG or PNG, max 10 MB<input name="img" type="file" accept="image/jpeg,image/png" required /></label><button type="submit">Upload</button></form>
          {job && <div className="inset" style={{ padding: 12, marginTop: 12 }} role="status">
            {job.status === "error" ? <span className="bad">{job.error}</span> : !job.events ? "Processing…" :
              job.events.map((ev, i) => <div key={i} className="plate"><span className="fa inset" lang="fa" dir="rtl">{ev.plate_string_fa || "—"}</span><span className="lat">{ev.plate_string_latin}</span></div>)}
          </div>}
        </section>
      )}
      <section className="card raised" aria-labelledby="th-h"><h2 id="th-h">Appearance</h2>
        <div className="row">{(["auto", "light", "dark"] as const).map((t) => <button key={t} type="button" onClick={() => onTheme(t)}>{t}</button>)}</div>
      </section>
    </>
  );
}
