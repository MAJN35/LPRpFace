import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Camera, EventSummary, LiveState, connectLive } from "../api";
import { LiveVideo } from "../components/LiveVideo";
import { ListBadge, Plate, PlateType, StateView, Validity, fmtTime, useApi } from "../components/ui";
import { useI18n } from "../i18n";

const RAW_TYPES = ["rtsp", "rtmp", "http", "hls"];

// One live view at a time: the board can encode one detection stream (memory), so the page shows the selected
// camera with detections (OSD) or its raw stream.
function LiveView({ cams }: { cams: Camera[] }) {
  const { t } = useI18n();
  const [camId, setCamId] = useState<string>(cams[0]?.id ?? "");
  const [view, setView] = useState<"osd" | "raw">("osd");
  const cam = cams.find((c) => c.id === camId) ?? cams[0];
  if (!cam) return null;
  const canRaw = RAW_TYPES.includes(cam.type);
  const shown = view === "raw" && canRaw ? "raw" : "osd";
  const path = shown === "osd" ? `${cam.id}-osd` : cam.id;
  return (
    <section className="card raised" aria-label={t("live.title")}>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
        <label className="row" style={{ display: "flex", alignItems: "center", gap: 8 }}>{t("live.camera")}
          <select className="inset" value={cam.id} onChange={(e) => setCamId(e.target.value)}>
            {cams.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <div className="row" role="group" aria-label={t("live.view")} style={{ gap: 6 }}>
          <button type="button" aria-pressed={shown === "osd"} onClick={() => setView("osd")}>{t("live.osd")}</button>
          <button type="button" aria-pressed={shown === "raw"} disabled={!canRaw}
            title={canRaw ? "" : t("live.rawOnlyNet")} onClick={() => setView("raw")}>{t("live.raw")}</button>
        </div>
      </div>
      <LiveVideo key={path} path={path} label={`${cam.name} ${shown === "osd" ? t("video.withOsd") : t("video.raw")}`} />
      <p className="muted" style={{ margin: "8px 0 0", fontSize: 13 }}>
        {shown === "osd" ? t("live.osdNote") : t("live.rawNote")}
      </p>
    </section>
  );
}

export function Live({ connect = connectLive }: { connect?: typeof connectLive }) {
  const { t } = useI18n();
  const [events, setEvents] = useState<EventSummary[]>([]);
  const [state, setState] = useState<LiveState>("connecting");
  const cams = useApi<Camera[]>("/cameras", 15000);
  const videoCams = (cams.data ?? []).filter((c) => c.enabled && !["image", "image_folder", "image_job"].includes(c.type));
  const [alert, setAlert] = useState<EventSummary | null>(null);
  const [arrived, setArrived] = useState<Set<string>>(new Set());   // rows that arrived live get a brief highlight
  useEffect(() => connect((e) => {
    setEvents((xs) => [e, ...xs.filter((x) => x.event_id !== e.event_id)].slice(0, 50));
    setArrived((a) => new Set(a).add(e.event_id));
  }, setState, setAlert), [connect]);
  return (
    <>
      <h1>{t("live.title")}</h1>
      <p className="sub">{t("live.sub")}</p>
      <StateView hasData={!!cams.data} loading={cams.loading} error={null} empty={!videoCams.length}
        emptyText={t("live.noCams")}>
        <LiveView cams={videoCams} />
      </StateView>
      {state !== "open" && (
        <div className="banner inset" role="status">
          <span className="dot pulse" aria-hidden="true" style={{ background: state === "connecting" ? "var(--warn)" : "var(--bad)" }} />
          <span>{state === "connecting" ? t("live.connecting") : <><strong className="bad">{t("live.disconnected")}</strong> {t("live.reconnecting")}</>}</span>
        </div>
      )}
      {alert && (
        <div className="banner raised alert-pulse" role="alert">
          <span className="dot" aria-hidden="true" style={{ background: "var(--bad)" }} />
          <span><strong className="bad">{t("live.alert")}</strong> {t("live.alertOn", { camera: alert.camera_id, time: fmtTime(alert.timestamp) })} </span>
          <Plate e={alert} /> <Link to={`/events/${alert.event_id}`}>{t("live.details")}</Link>
          <button type="button" onClick={() => setAlert(null)} style={{ marginInlineStart: "auto" }}>{t("live.dismiss")}</button>
        </div>
      )}
      <section className="card raised" aria-live="polite" aria-label={t("live.feed")}>
        {events.length === 0 ? <div className="state">{state === "open" ? t("live.waiting") : t("live.noData")}</div> : (
          <div className="table-wrap"><table><thead><tr><th>{t("col.time")}</th><th>{t("col.camera")}</th><th>{t("col.plate")}</th><th>{t("col.type")}</th><th>{t("col.list")}</th><th>{t("col.status")}</th></tr></thead><tbody>
            {events.map((e) => (
              <tr key={e.event_id} className={arrived.has(e.event_id) ? "arrived" : undefined}><td><Link to={`/events/${e.event_id}`}>{fmtTime(e.timestamp)}</Link></td><td>{e.camera_id}</td><td><Plate e={e} /></td><td><PlateType type={e.plate_type} /></td><td><ListBadge status={e.list_status} /></td><td><Validity e={e} /></td></tr>
            ))}
          </tbody></table></div>
        )}
      </section>
    </>
  );
}
