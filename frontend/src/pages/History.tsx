import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { Page, auth, query } from "../api";
import { ListBadge, Plate, StateView, Validity, fmtTime, useApi } from "../components/ui";

const LIMIT = 25;
type F = { q: string; camera_id: string; from: string; to: string; plate_type: string; is_valid: string; model_version: string; list_status: string };
const EMPTY: F = { q: "", camera_id: "", from: "", to: "", plate_type: "", is_valid: "", model_version: "", list_status: "" };
const iso = (local: string) => (local ? new Date(local).toISOString() : "");

export function History() {
  const [draft, setDraft] = useState<F>(EMPTY);
  const [f, setF] = useState<F>(EMPTY);
  const [offset, setOffset] = useState(0);
  const params = { ...f, from: iso(f.from), to: iso(f.to), limit: LIMIT, offset };
  const page = useApi<Page>(`/events${query(params)}`);
  const set = (k: keyof F) => (e: { target: { value: string } }) => setDraft({ ...draft, [k]: e.target.value });
  function apply(e: FormEvent) { e.preventDefault(); setOffset(0); setF(draft); }
  const total = page.data?.total ?? 0;
  const csv = `/api/v1/events/export.csv${query({ q: f.q, camera_id: f.camera_id, from: iso(f.from), to: iso(f.to), token: auth.token })}`;
  return (
    <>
      <h1>History</h1><p className="sub">Search by Persian or Latin plate, any digit style or spacing.</p>
      <form className="card raised filters" onSubmit={apply} role="search">
        <label>Plate<input className="inset" value={draft.q} onChange={set("q")} placeholder="۱۲ب۳۴۵ or 12 Be 345" /></label>
        <label>Camera<input className="inset" value={draft.camera_id} onChange={set("camera_id")} /></label>
        <label>From<input className="inset" type="datetime-local" value={draft.from} onChange={set("from")} /></label>
        <label>To<input className="inset" type="datetime-local" value={draft.to} onChange={set("to")} /></label>
        <label>Type<select className="inset" value={draft.plate_type} onChange={set("plate_type")}>
          <option value="">any</option>{["standard", "disabled", "diplomatic", "transit", "freezone", "protocol", "unknown"].map((t) => <option key={t}>{t}</option>)}</select></label>
        <label>Validity<select className="inset" value={draft.is_valid} onChange={set("is_valid")}><option value="">any</option><option value="true">valid</option><option value="false">invalid</option></select></label>
        <label>List<select className="inset" value={draft.list_status} onChange={set("list_status")}><option value="">any</option><option value="whitelist">whitelist</option><option value="blocklist">blocklist</option><option value="unknown">unknown</option></select></label>
        <label>Model<select className="inset" value={draft.model_version} onChange={set("model_version")}><option value="">any</option><option>v1</option><option>v2</option></select></label>
        <div className="row"><button type="submit">Search</button><button type="button" onClick={() => { setDraft(EMPTY); setF(EMPTY); setOffset(0); }}>Clear</button></div>
      </form>
      <section className="card raised" aria-label="Results">
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
          <span className="muted" aria-live="polite">{page.data ? `${total} events` : ""}</span>
          <a className="btn" href={csv}>Export CSV</a>
        </div>
        <StateView loading={page.loading} error={page.error} empty={!page.data?.items.length} emptyText="No events match these filters." onRetry={page.reload}>
          <div className="table-wrap"><table><thead><tr><th>Time</th><th>Camera</th><th>Plate</th><th>Type</th><th>List</th><th>Model</th><th>Confidence</th><th>Status</th></tr></thead><tbody>
            {page.data?.items.map((e) => (
              <tr key={e.event_id}><td><Link to={`/events/${e.event_id}`}>{fmtTime(e.timestamp)}</Link></td><td>{e.camera_id}</td><td><Plate e={e} /></td>
                <td>{e.plate_type}</td><td><ListBadge status={e.list_status} /></td><td>{e.model_version}</td><td>{(e.confidence * 100).toFixed(0)} %</td><td><Validity e={e} /></td></tr>
            ))}
          </tbody></table></div>
          <nav className="row" aria-label="Pages" style={{ marginTop: 12 }}>
            <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>Previous</button>
            <span className="muted">{offset + 1}–{Math.min(offset + LIMIT, total)} of {total}</span>
            <button type="button" disabled={offset + LIMIT >= total} onClick={() => setOffset(offset + LIMIT)}>Next</button>
          </nav>
        </StateView>
      </section>
    </>
  );
}
