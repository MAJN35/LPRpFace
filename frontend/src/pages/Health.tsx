import { Status } from "../api";
import { StaleBanner, StateView, useApi } from "../components/ui";

export function Health() {
  const st = useApi<Status>("/status", 3000);
  const inf = st.data?.inference;
  return (
    <>
      <h1>System health</h1><p className="sub">Refreshes every 3 s.</p>
      <StaleBanner updatedAt={st.updatedAt} maxAgeMs={10000} what="Health data" />
      <StateView loading={st.loading} error={st.error} onRetry={st.reload}>
        {st.data && inf && (<>
          <section className="kpis" aria-label="Service status">
            <div className="kpi raised"><div className="label">Inference</div><div className={`value ${inf.reachable ? "ok" : "bad"}`}>{inf.reachable ? "up" : "down"}</div></div>
            <div className="kpi raised"><div className="label">Events stored</div><div className="value">{st.data.database.events}</div></div>
            <div className="kpi raised"><div className="label">Max cameras (measured)</div><div className="value">{inf.max_cameras ?? "–"}</div></div>
            <div className="kpi raised"><div className="label">Retention</div><div className="value">{st.data.retention_days} d</div></div>
          </section>
          {!inf.reachable && <div className="banner inset" role="alert"><strong className="bad">Inference unreachable:</strong> {inf.error}</div>}
          {inf.reachable && (<>
            <section className="card raised" aria-labelledby="src-h"><h2 id="src-h">Sources</h2>
              <div className="table-wrap"><table><thead><tr><th>Source</th><th>Status</th><th>fps in</th><th>Last frame</th><th>Reconnects</th><th>Last error</th></tr></thead><tbody>
                {Object.entries(inf.sources ?? {}).map(([id, s]) => (
                  <tr key={id}><td>{id}</td><td>{s.status}</td><td>{s.fps_in?.toFixed(1) ?? "–"}</td><td>{s.last_frame_age_s != null ? `${s.last_frame_age_s} s ago` : "–"}</td><td>{s.reconnects ?? 0}</td><td className="muted">{s.last_error ?? ""}</td></tr>
                ))}
              </tbody></table></div>
            </section>
            <section className="card raised" aria-labelledby="pipe-h"><h2 id="pipe-h">Pipeline</h2>
              <p>Model {inf.model?.version} · {inf.model?.precision} · batch profile {inf.model?.batch_profile.join("/")} · <code>{inf.engine}</code></p>
              <pre className="inset" style={{ padding: 12, overflowX: "auto", margin: 0 }}>{JSON.stringify({ pipeline: inf.pipeline, worker: inf.worker }, null, 2)}</pre>
            </section>
          </>)}
        </>)}
      </StateView>
    </>
  );
}
