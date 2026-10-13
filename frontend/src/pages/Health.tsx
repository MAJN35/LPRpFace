import { Status } from "../api";
import { StaleBanner, StateView, useApi } from "../components/ui";
import { useI18n } from "../i18n";

export function Health() {
  const { t, num } = useI18n();
  const st = useApi<Status>("/status", 3000);
  const inf = st.data?.inference;
  return (
    <>
      <h1>{t("health.title")}</h1><p className="sub">{t("health.sub")}</p>
      <StaleBanner updatedAt={st.updatedAt} maxAgeMs={10000} what={t("health.title")} />
      <StateView hasData={!!st.data} loading={st.loading} error={st.error} onRetry={st.reload}>
        {st.data && inf && (<>
          <section className="kpis" aria-label={t("health.title")}>
            <div className="kpi raised"><div className="label">{t("health.inference")}</div><div className={`value ${inf.reachable ? "ok" : "bad"}`}>{inf.reachable ? t("health.up") : t("health.down")}</div></div>
            <div className="kpi raised"><div className="label">{t("health.events")}</div><div className="value">{num(st.data.database.events)}</div></div>
            <div className="kpi raised"><div className="label">{t("health.cams")}</div><div className="value">{num(inf.capacity?.max_cameras_memory_safe ?? inf.max_cameras ?? "–")}</div>
              {inf.capacity && <div className="muted" style={{ fontSize: 13 }}>{t("health.camsAt", { n: inf.capacity.max_cameras_at_target_fps, fps: inf.capacity.target_fps_per_camera })}</div>}</div>
            <div className="kpi raised"><div className="label">{t("health.retention")}</div><div className="value">{t("health.days", { n: st.data.retention_days })}</div></div>
          </section>
          {!inf.reachable && <div className="banner inset" role="alert"><strong className="bad">{t("health.unreachable")}</strong> {inf.error}</div>}
          {inf.reachable && (<>
            <section className="card raised" aria-labelledby="src-h"><h2 id="src-h">{t("health.sources")}</h2>
              <div className="table-wrap"><table><thead><tr><th>{t("health.source")}</th><th>{t("col.status")}</th><th>{t("health.fpsIn")}</th><th>{t("health.lastFrame")}</th><th>{t("health.reconnects")}</th><th>{t("health.lastError")}</th></tr></thead><tbody>
                {Object.entries(inf.sources ?? {}).map(([id, s]) => (
                  <tr key={id}><td>{id}</td><td>{s.status}</td><td>{s.fps_in != null ? num(s.fps_in.toFixed(1)) : "–"}</td><td>{s.last_frame_age_s != null ? t("health.ago", { s: s.last_frame_age_s }) : "–"}</td><td>{num(s.reconnects ?? 0)}</td><td className="muted">{s.last_error ?? ""}</td></tr>
                ))}
              </tbody></table></div>
            </section>
            <section className="card raised" aria-labelledby="pipe-h"><h2 id="pipe-h">{t("health.pipeline")}</h2>
              <p>{t("health.modelLine", { v: inf.model?.version ?? "", p: inf.model?.precision ?? "", b: inf.model?.batch_profile.join("/") ?? "" })} · <code dir="ltr">{inf.engine}</code></p>
              <pre dir="ltr" className="inset" style={{ padding: 12, overflowX: "auto", margin: 0 }}>{JSON.stringify({ pipeline: inf.pipeline, worker: inf.worker }, null, 2)}</pre>
            </section>
          </>)}
        </>)}
      </StateView>
    </>
  );
}
