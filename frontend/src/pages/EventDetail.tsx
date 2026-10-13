import { useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError, EventDetail as Detail, ListStatus, PlateEntry, api, cropUrl, json } from "../api";
import { ListBadge, ListSwitch, Plate, StateView, Validity, fmtTime, listLabel, useApi } from "../components/ui";

export function EventDetail({ role = "viewer" }: { role?: string }) {
  const { id } = useParams();
  const ev = useApi<Detail>(id ? `/events/${id}` : null);
  const e = ev.data;
  const canEdit = role === "admin" || role === "operator";
  const [current, setCurrent] = useState<ListStatus | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  async function putOnList(to: ListStatus) {
    if (!e) return;
    try {
      const p = await api<PlateEntry>("/plates", json({ plate: e.plate_string_latin, list_status: to, upsert: true }));
      setCurrent(p.list_status); setMsg(`Plate is now on the ${listLabel(p.list_status).toLowerCase()}.`);
    } catch (err) { setMsg(err instanceof ApiError ? `Failed: ${err.message}` : "Failed"); }
  }
  return (
    <>
      <h1>Event</h1><p className="sub">Viewing this event is recorded in the audit log.</p>
      <StateView hasData={!!ev.data} loading={ev.loading} error={ev.error} onRetry={ev.reload}>
        {e && (
          <div className="grid2">
            <section className="card raised" aria-labelledby="ev-h"><h2 id="ev-h"><Plate e={e} /></h2>
              <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "6px 16px", margin: 0 }}>
                <dt className="muted">Time (UTC capture)</dt><dd>{fmtTime(e.timestamp)}</dd>
                <dt className="muted">Camera / source</dt><dd>{e.camera_id} ({e.source_type}){e.source_file ? ` · ${e.source_file}` : ""}</dd>
                <dt className="muted">Type</dt><dd>{e.plate_type}{e.markers.length ? ` · ${e.markers.join(", ")}` : ""}{e.expiry ? ` · expiry ${e.expiry}` : ""}</dd>
                <dt className="muted">Status</dt><dd><Validity e={e} /></dd>
                <dt className="muted">Confidence</dt><dd>{(e.confidence * 100).toFixed(1)} % · {e.frames_voted} frame(s) voted{e.track_id != null ? ` · track ${e.track_id}` : ""}</dd>
                <dt className="muted">List at event time</dt><dd><ListBadge status={e.list_status} />{e.person ? ` · ${e.person.full_name}` : ""}</dd>
                <dt className="muted">Model</dt><dd>{e.model_version} · {e.precision} · <code title={e.model_sha256}>{e.model_sha256.slice(0, 12)}…</code></dd>
              </dl>
              {canEdit && e.is_valid && e.plate_string_latin && (<>
                <h2 style={{ marginTop: 20 }}>Put this plate on a list</h2>
                <ListSwitch value={current ?? e.list_status} label={e.plate_string_latin} onChange={putOnList} />
                {msg && <p role="status" className="muted">{msg}</p>}
              </>)}
              <h2 style={{ marginTop: 20 }}>Characters</h2>
              <div className="table-wrap"><table><thead><tr><th>#</th><th>Class</th><th>Confidence</th><th>Margin</th></tr></thead><tbody>
                {e.characters.map((c, i) => <tr key={i}><td>{i + 1}</td><td>{c.name}</td><td>{(c.confidence * 100).toFixed(1)} %</td><td>{c.margin != null ? (c.margin * 100).toFixed(1) + " %" : "–"}</td></tr>)}
              </tbody></table></div>
            </section>
            <section className="card raised" aria-labelledby="crop-h"><h2 id="crop-h">Evidence</h2>
              {e.has_crop ? <img className="crop" src={cropUrl(e.event_id)} alt={`Plate crop ${e.plate_string_latin}`} /> : <div className="state">No crop stored.</div>}
            </section>
          </div>
        )}
      </StateView>
    </>
  );
}
