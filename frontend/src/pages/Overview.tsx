import { Link } from "react-router-dom";
import { Page, Stats, Status, query } from "../api";
import { ListBadge, Plate, StaleBanner, StateView, Validity, fmtTime, useApi } from "../components/ui";
import { useI18n } from "../i18n";

export function Overview() {
  const { t, num } = useI18n();
  const stats = useApi<Stats>("/stats?hours=24", 15000);
  const status = useApi<Status>("/status", 5000);
  const recent = useApi<Page>(`/events${query({ limit: 8 })}`, 5000);
  const sources = status.data?.inference.sources ?? {};
  const online = Object.values(sources).filter((s) => s.status === "live" || s.status === "running").length;
  const fps = Object.values(sources).reduce((a, s) => a + (s.fps_in ?? 0), 0);
  const model = status.data?.inference.model;
  return (
    <>
      <h1>{t("ov.title")}</h1>
      <p className="sub">{t("ov.sub")}{model ? ` · ${t("ov.model", { version: model.version, precision: model.precision.toUpperCase() })}` : ""}</p>
      <StaleBanner updatedAt={status.updatedAt} maxAgeMs={20000} what={t("ov.status")} />
      {status.data && !status.data.inference.reachable && (
        <div className="banner inset" role="alert"><span className="dot" style={{ background: "var(--bad)" }} aria-hidden="true" />
          <span><strong className="bad">{t("ov.infDown")}</strong> {status.data.inference.error}</span></div>
      )}
      <section className="kpis" aria-label={t("ov.title")}>
        <div className="kpi raised"><div className="label">{t("ov.read")}</div><div className="value">{stats.data ? num(stats.data.total) : "–"}</div></div>
        <div className="kpi raised"><div className="label">{t("ov.valid")}</div><div className="value">{stats.data?.valid_rate != null ? `${num((stats.data.valid_rate * 100).toFixed(1))} %` : "–"}</div></div>
        <div className="kpi raised"><div className="label">{t("ov.online")}</div><div className="value">{status.data?.inference.reachable ? `${num(online)} / ${num(Object.keys(sources).length)}` : "–"}</div></div>
        <div className="kpi raised"><div className="label">{t("ov.fps")}</div><div className="value">{status.data?.inference.reachable ? `${num(fps.toFixed(1))} fps` : "–"}</div></div>
      </section>
      <div className="grid2">
        <section className="card raised" aria-labelledby="recent-h"><h2 id="recent-h">{t("ov.recent")}</h2>
          <StateView hasData={!!recent.data} loading={recent.loading} error={recent.error} empty={!recent.data?.items.length} emptyText={t("ov.noPlates")} onRetry={recent.reload}>
            <div className="table-wrap"><table><thead><tr><th>{t("col.time")}</th><th>{t("col.camera")}</th><th>{t("col.plate")}</th><th>{t("col.list")}</th><th>{t("col.status")}</th></tr></thead><tbody>
              {recent.data?.items.map((e) => (
                <tr key={e.event_id}><td><Link to={`/events/${e.event_id}`}>{fmtTime(e.timestamp)}</Link></td><td>{e.camera_id}</td><td><Plate e={e} /></td><td><ListBadge status={e.list_status} /></td><td><Validity e={e} /></td></tr>
              ))}
            </tbody></table></div>
          </StateView>
        </section>
        <section className="card raised" aria-labelledby="src-h"><h2 id="src-h">{t("ov.sources")}</h2>
          <StateView hasData={!!status.data} loading={status.loading} error={status.error} empty={!Object.keys(sources).length} emptyText={t("ov.noSources")} onRetry={status.reload}>
            {Object.entries(sources).map(([id, s]) => (
              <div key={id} className="inset row" style={{ justifyContent: "space-between", padding: "10px 12px", marginBottom: 10 }}>
                <span className="row"><span className={`dot${["connecting", "reconnecting", "no_signal"].includes(s.status) ? " pulse" : ""}`} aria-hidden="true" style={{ background: s.status === "live" || s.status === "running" ? "var(--ok)" : s.status === "disabled" || s.status === "finished" ? "var(--muted)" : "var(--warn)" }} />{id}</span>
                <span>{s.status === "live" ? `${num((s.fps_in ?? 0).toFixed(1))} fps` : s.status}</span>
              </div>
            ))}
          </StateView>
          {stats.data?.last_event_at && <p className="muted">{t("ov.lastEvent", { time: fmtTime(stats.data.last_event_at) })}</p>}
        </section>
      </div>
    </>
  );
}
