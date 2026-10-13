import { Link } from "react-router-dom";
import { Page, Stats, Status, query } from "../api";
import { ListBadge, Plate, StaleBanner, StateView, Validity, fmtTime, useApi } from "../components/ui";

export function Overview() {
  const stats = useApi<Stats>("/stats?hours=24", 15000);
  const status = useApi<Status>("/status", 5000);
  const recent = useApi<Page>(`/events${query({ limit: 8 })}`, 5000);
  const sources = status.data?.inference.sources ?? {};
  const online = Object.values(sources).filter((s) => s.status === "live" || s.status === "running").length;
  const fps = Object.values(sources).reduce((a, s) => a + (s.fps_in ?? 0), 0);
  return (
    <>
      <h1>Overview</h1>
      <p className="sub">Last 24 hours{status.data?.inference.model ? ` · model ${status.data.inference.model.version} · ${status.data.inference.model.precision.toUpperCase()}` : ""}</p>
      <StaleBanner updatedAt={status.updatedAt} maxAgeMs={20000} what="System status" />
      {status.data && !status.data.inference.reachable && (
        <div className="banner inset" role="alert"><span className="dot" style={{ background: "var(--bad)" }} aria-hidden="true" />
          <span><strong className="bad">Inference service unreachable.</strong> {status.data.inference.error}</span></div>
      )}
      <section className="kpis" aria-label="Key figures">
        <div className="kpi raised"><div className="label">Plates read (24 h)</div><div className="value">{stats.data?.total ?? "–"}</div></div>
        <div className="kpi raised"><div className="label">Valid format</div><div className="value">{stats.data?.valid_rate != null ? `${(stats.data.valid_rate * 100).toFixed(1)} %` : "–"}</div></div>
        <div className="kpi raised"><div className="label">Sources online</div><div className="value">{status.data?.inference.reachable ? `${online} / ${Object.keys(sources).length}` : "–"}</div></div>
        <div className="kpi raised"><div className="label">Frames in</div><div className="value">{status.data?.inference.reachable ? `${fps.toFixed(1)} fps` : "–"}</div></div>
      </section>
      <div className="grid2">
        <section className="card raised" aria-labelledby="recent-h"><h2 id="recent-h">Recent plates</h2>
          <StateView hasData={!!recent.data} loading={recent.loading} error={recent.error} empty={!recent.data?.items.length} emptyText="No plates recorded yet." onRetry={recent.reload}>
            <div className="table-wrap"><table><thead><tr><th>Time</th><th>Camera</th><th>Plate</th><th>List</th><th>Status</th></tr></thead><tbody>
              {recent.data?.items.map((e) => (
                <tr key={e.event_id}><td><Link to={`/events/${e.event_id}`}>{fmtTime(e.timestamp)}</Link></td><td>{e.camera_id}</td><td><Plate e={e} /></td><td><ListBadge status={e.list_status} /></td><td><Validity e={e} /></td></tr>
              ))}
            </tbody></table></div>
          </StateView>
        </section>
        <section className="card raised" aria-labelledby="src-h"><h2 id="src-h">Sources</h2>
          <StateView hasData={!!status.data} loading={status.loading} error={status.error} empty={!Object.keys(sources).length} emptyText="No sources configured." onRetry={status.reload}>
            {Object.entries(sources).map(([id, s]) => (
              <div key={id} className="inset row" style={{ justifyContent: "space-between", padding: "10px 12px", marginBottom: 10 }}>
                <span className="row"><span className={`dot${["connecting", "reconnecting", "no_signal"].includes(s.status) ? " pulse" : ""}`} aria-hidden="true" style={{ background: s.status === "live" || s.status === "running" ? "var(--ok)" : s.status === "disabled" || s.status === "finished" ? "var(--muted)" : "var(--warn)" }} />{id}</span>
                <span>{s.status === "live" ? `${(s.fps_in ?? 0).toFixed(1)} fps` : s.status}</span>
              </div>
            ))}
          </StateView>
          {stats.data?.last_event_at && <p className="muted">Last event {fmtTime(stats.data.last_event_at)}</p>}
        </section>
      </div>
    </>
  );
}
