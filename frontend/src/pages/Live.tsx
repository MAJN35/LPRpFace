import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { EventSummary, LiveState, connectLive } from "../api";
import { ListBadge, Plate, Validity, fmtTime } from "../components/ui";

export function Live({ connect = connectLive }: { connect?: typeof connectLive }) {
  const [events, setEvents] = useState<EventSummary[]>([]);
  const [state, setState] = useState<LiveState>("connecting");
  const [alert, setAlert] = useState<EventSummary | null>(null);
  const [arrived, setArrived] = useState<Set<string>>(new Set());   // rows that arrived live get a brief highlight
  useEffect(() => connect((e) => {
    setEvents((xs) => [e, ...xs.filter((x) => x.event_id !== e.event_id)].slice(0, 50));
    setArrived((a) => new Set(a).add(e.event_id));
  }, setState, setAlert), [connect]);
  return (
    <>
      <h1>Live</h1>
      <p className="sub">Plates as they are recognized. Live video needs an approved WebRTC/HLS gateway (not enabled).</p>
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
