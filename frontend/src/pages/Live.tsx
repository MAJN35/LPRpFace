import { Cctv, LayoutGrid, ScanLine, Square, Video } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Camera, EventSummary, LiveState, Status, connectLive } from "../api";
import { Btn } from "../components/Button";
import { LiquidGroup } from "../components/LiquidIndicator";
import { LiveVideo } from "../components/LiveVideo";
import { ListBadge, Plate, PlateType, StateView, Validity, fmtTime, useApi } from "../components/ui";
import { useI18n } from "../i18n";

const RAW_TYPES = ["rtsp", "rtmp", "http", "hls"];

type View = "osd" | "raw";

// Grid of all cameras at once. Raw streams can play side by side (the gateway only remuxes them); the detection
// overlay is one encoder on this board (memory), so at most one tile shows detections and the others play raw.
// Cameras without a raw stream (USB, CSI, files) show a placeholder until their detections are selected.
function LiveGrid({ cams }: { cams: Camera[] }) {
  const { t, num } = useI18n();
  const status = useApi<Status>("/status", 4000);       // model rate per camera on each tile
  const fpsOf = (id: string) => status.data?.inference?.sources?.[id]?.fps_out;
  const [osdCam, setOsdCam] = useState<string | null>(() => cams[0]?.id ?? null);
  const [layout, setLayout] = useState<"grid" | "single">("grid");
  const [focus, setFocus] = useState<string>(cams[0]?.id ?? "");
  const shown = layout === "single" ? cams.filter((c) => c.id === focus).slice(0, 1) : cams;
  const list = shown.length ? shown : cams.slice(0, 1);
  return (
    <section className="card raised" aria-label={t("live.title")}>
      <div className="card-head">
        <LiquidGroup selector='[aria-pressed="true"]' activeKey={layout} className="row" role="group" aria-label={t("live.layout")} style={{ gap: 6 }}>
          <Btn icon={LayoutGrid} aria-pressed={layout === "grid"} onClick={() => setLayout("grid")}>{t("live.grid")}</Btn>
          <Btn icon={Square} aria-pressed={layout === "single"} onClick={() => setLayout("single")}>{t("live.single")}</Btn>
        </LiquidGroup>
        {layout === "single" && (
          <label className="row" style={{ display: "flex", alignItems: "center", gap: 8 }}>{t("live.camera")}
            <select className="inset" value={focus} onChange={(e) => setFocus(e.target.value)}>
              {cams.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
        )}
      </div>
      <div className={`video-grid${list.length === 1 ? " one" : ""}`}>
        {list.map((cam) => {
          const canRaw = RAW_TYPES.includes(cam.type);
          const view: View | null = osdCam === cam.id ? "osd" : canRaw ? "raw" : null;
          const path = view === "osd" ? `${cam.id}-osd` : cam.id;
          return (
            <figure key={cam.id} className="video-tile">
              <figcaption className="row video-cap">
                <span className="row" style={{ gap: 6 }}><Cctv size={16} aria-hidden="true" /><strong>{cam.name}</strong>
                  <span className="muted">{view === "osd" ? t("video.withOsd") : view === "raw" ? t("video.raw") : ""}</span>
                  {fpsOf(cam.id) != null && <span className="badge inset fps-badge">{t("live.modelFps", { fps: num(fpsOf(cam.id)!.toFixed(1)) })}</span>}</span>
                <span className="row" role="group" aria-label={t("live.viewOf", { camera: cam.name })} style={{ gap: 6 }}>
                  <Btn icon={ScanLine} className="btn-sm" aria-pressed={view === "osd"} onClick={() => setOsdCam(cam.id)}>{t("live.osd")}</Btn>
                  <Btn icon={Video} className="btn-sm" aria-pressed={view === "raw"} disabled={!canRaw}
                    tip={canRaw ? undefined : t("live.rawOnlyNet")} onClick={() => osdCam === cam.id && setOsdCam(null)}>{t("live.raw")}</Btn>
                </span>
              </figcaption>
              {view ? <LiveVideo key={path} path={path} label={`${cam.name} ${view === "osd" ? t("video.withOsd") : t("video.raw")}`} />
                : <div className="video-box inset"><div className="video-state">{t("live.rawOnlyNet")}</div></div>}
            </figure>
          );
        })}
      </div>
      <p className="muted" style={{ margin: "8px 0 0", fontSize: 13 }}>{t("live.osdNote")} {t("live.rawNote")}</p>
    </section>
  );
}

export function Live({ connect = connectLive }: { connect?: typeof connectLive }) {
  const { t } = useI18n();
  const [events, setEvents] = useState<EventSummary[]>([]);
  const [state, setState] = useState<LiveState>("connecting");
  const cams = useApi<Camera[]>("/cameras", 15000);
  const videoCams = (cams.data ?? []).filter((c) => c.enabled && !["image", "image_folder", "image_job"].includes(c.type));
  const [arrived, setArrived] = useState<Set<string>>(new Set());   // rows that arrived live get a brief highlight
  useEffect(() => connect((e) => {
    setEvents((xs) => [e, ...xs.filter((x) => x.event_id !== e.event_id)].slice(0, 50));
    setArrived((a) => new Set(a).add(e.event_id));
  }, setState), [connect]);
  return (
    <>
      <h1>{t("live.title")}</h1>
      <p className="sub">{t("live.sub")}</p>
      <StateView hasData={!!cams.data} loading={cams.loading} error={null} empty={!videoCams.length}
        emptyText={t("live.noCams")}>
        <LiveGrid cams={videoCams} />
      </StateView>
      {state !== "open" && (
        <div className="banner inset" role="status">
          <span className="dot pulse" aria-hidden="true" style={{ background: state === "connecting" ? "var(--warn)" : "var(--bad)" }} />
          <span>{state === "connecting" ? t("live.connecting") : <><strong className="bad">{t("live.disconnected")}</strong> {t("live.reconnecting")}</>}</span>
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
