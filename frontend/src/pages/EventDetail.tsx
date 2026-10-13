import { useParams } from "react-router-dom";
import { EventDetail as Detail, cropUrl } from "../api";
import { Plate, StateView, Validity, fmtTime, useApi } from "../components/ui";

export function EventDetail() {
  const { id } = useParams();
  const ev = useApi<Detail>(id ? `/events/${id}` : null);
  const e = ev.data;
  return (
    <>
      <h1>Event</h1><p className="sub">Viewing this event is recorded in the audit log.</p>
      <StateView loading={ev.loading} error={ev.error} onRetry={ev.reload}>
        {e && (
          <div className="grid2">
            <section className="card raised" aria-labelledby="ev-h"><h2 id="ev-h"><Plate e={e} /></h2>
              <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "6px 16px", margin: 0 }}>
                <dt className="muted">Time (UTC capture)</dt><dd>{fmtTime(e.timestamp)}</dd>
                <dt className="muted">Camera / source</dt><dd>{e.camera_id} ({e.source_type}){e.source_file ? ` · ${e.source_file}` : ""}</dd>
                <dt className="muted">Type</dt><dd>{e.plate_type}{e.markers.length ? ` · ${e.markers.join(", ")}` : ""}{e.expiry ? ` · expiry ${e.expiry}` : ""}</dd>
                <dt className="muted">Status</dt><dd><Validity e={e} /></dd>
                <dt className="muted">Confidence</dt><dd>{(e.confidence * 100).toFixed(1)} % · {e.frames_voted} frame(s) voted{e.track_id != null ? ` · track ${e.track_id}` : ""}</dd>
                <dt className="muted">Model</dt><dd>{e.model_version} · {e.precision} · <code title={e.model_sha256}>{e.model_sha256.slice(0, 12)}…</code></dd>
              </dl>
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
