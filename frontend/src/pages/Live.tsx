import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Camera, EventSummary, LiveState, connectLive } from "../api";
import { LiveVideo } from "../components/LiveVideo";
import { ListBadge, Plate, StateView, Validity, fmtTime, useApi } from "../components/ui";

const RAW_TYPES = ["rtsp", "rtmp", "http", "hls"];

// One live view at a time: the board can encode one detection stream (memory), so the page shows the selected
// camera with detections (OSD) or its raw stream.
function LiveView({ cams }: { cams: Camera[] }) {
  const [camId, setCamId] = useState<string>(cams[0]?.id ?? "");
  const [view, setView] = useState<"osd" | "raw">("osd");
  const cam = cams.find((c) => c.id === camId) ?? cams[0];
  if (!cam) return null;
  const canRaw = RAW_TYPES.includes(cam.type);
  const shown = view === "raw" && canRaw ? "raw" : "osd";
  const path = shown === "osd" ? `${cam.id}-osd` : cam.id;
  return (
    <section className="card raised" aria-label="Live view">
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
        <label className="row" style={{ display: "flex", alignItems: "center", gap: 8 }}>Camera
          <select className="inset" value={cam.id} onChange={(e) => setCamId(e.target.value)}>
            {cams.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <div className="row" role="group" aria-label="View" style={{ gap: 6 }}>
          <button type="button" aria-pressed={shown === "osd"} onClick={() => setView("osd")}>Detections</button>
          <button type="button" aria-pressed={shown === "raw"} disabled={!canRaw}
            title={canRaw ? "" : "Raw view is available for network cameras"} onClick={() => setView("raw")}>Raw</button>
        </div>
      </div>
      <LiveVideo key={path} path={path} label={`${cam.name} ${shown === "osd" ? "with detections" : "raw"}`} />
      <p className="muted" style={{ margin: "8px 0 0", fontSize: 13 }}>
        {shown === "osd" ? "Detections are drawn on the frames the model processed (about 3.5 per second in total on this device). One detection view at a time."
          : "Original camera stream (H.265 cameras play only in browsers with HEVC support)."}
      </p>
    </section>
  );
}

export function Live({ connect = connectLive }: { connect?: typeof connectLive }) {
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
      <h1>Live</h1>
      <p className="sub">Live camera views and plates as they are recognized.</p>
      <StateView hasData={!!cams.data} loading={cams.loading} error={null} empty={!videoCams.length}
        emptyText="No enabled video sources. Add or enable a camera in Settings.">
        <LiveView cams={videoCams} />
      </StateView>
      {state !== "open" && (
        <div className="banner inset" role="status">
          <span className="dot pulse" aria-hidden="true" style={{ background: state === "connecting" ? "var(--warn)" : "var(--bad)" }} />
          <span>{state === "connecting" ? "Connecting to live updates…" : <><strong className="bad">Disconnected.</strong> Reconnecting automatically.</>}</span>
        </div>
      )}
      {alert && (
        <div className="banner raised alert-pulse" role="alert">
          <span className="dot" aria-hidden="true" style={{ background: "var(--bad)" }} />
          <span><strong className="bad">Blocklisted plate</strong> on {alert.camera_id} at {fmtTime(alert.timestamp)}: </span>
          <Plate e={alert} /> <Link to={`/events/${alert.event_id}`}>Details</Link>
          <button type="button" onClick={() => setAlert(null)} style={{ marginLeft: "auto" }}>Dismiss</button>
        </div>
      )}
      <section className="card raised" aria-live="polite" aria-label="Live plates">
        {events.length === 0 ? <div className="state">{state === "open" ? "Waiting for the next plate…" : "No live data."}</div> : (
          <div className="table-wrap"><table><thead><tr><th>Time</th><th>Camera</th><th>Plate</th><th>Type</th><th>List</th><th>Status</th></tr></thead><tbody>
            {events.map((e) => (
              <tr key={e.event_id} className={arrived.has(e.event_id) ? "arrived" : undefined}><td><Link to={`/events/${e.event_id}`}>{fmtTime(e.timestamp)}</Link></td><td>{e.camera_id}</td><td><Plate e={e} /></td><td>{e.plate_type}</td><td><ListBadge status={e.list_status} /></td><td><Validity e={e} /></td></tr>
            ))}
          </tbody></table></div>
        )}
      </section>
    </>
  );
}
