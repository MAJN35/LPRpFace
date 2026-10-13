// A notification for every recognized plate, on every page (live WebSocket through nginx). Ordinary detections
// close after a few seconds and can be muted (bell in the sidebar, stored per browser in localStorage
// "lpr.notify"); blocklist hits always appear and stay until dismissed. Nothing leaves the device: these are in-page
// notifications, not browser/OS push.
import { Eye, ShieldBan, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { EventSummary, connectLive } from "../api";
import { useI18n } from "../i18n";
import { PlateView } from "../plate/PlateView";
import { eventPlate } from "../plate/formats";
import { Btn } from "./Button";
import { ListBadge, Plate, fmtTime } from "./ui";

const KEY = "lpr.notify";
const MAX = 4;
const PLATE_MS = 6000;

export function readNotify(): boolean { try { return localStorage.getItem(KEY) !== "off"; } catch { return true; } }
export function storeNotify(on: boolean) { try { localStorage.setItem(KEY, on ? "on" : "off"); } catch { /* storage blocked */ } }

type Toast = { e: EventSummary; alert: boolean };

export function Notifications({ enabled, connect = connectLive }: { enabled: boolean; connect?: typeof connectLive }) {
  const { t } = useI18n();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const on = useRef(enabled);
  on.current = enabled;
  const timers = useRef(new Map<string, number>());

  useEffect(() => {
    const close = (id: string) => setToasts((ts) => ts.filter((x) => x.e.event_id !== id));
    const push = (e: EventSummary, alert: boolean) => {
      if (!alert && !on.current) return;
      setToasts((ts) => {
        const old = ts.find((x) => x.e.event_id === e.event_id);
        const next = { e, alert: alert || !!old?.alert || e.list_status === "blocklist" };
        return [next, ...ts.filter((x) => x.e.event_id !== e.event_id)].slice(0, MAX);
      });
      window.clearTimeout(timers.current.get(e.event_id));
      if (!alert && e.list_status !== "blocklist") timers.current.set(e.event_id, window.setTimeout(() => close(e.event_id), PLATE_MS));
      else timers.current.delete(e.event_id);
    };
    const stop = connect((e) => push(e, false), () => undefined, (e) => push(e, true));
    const all = timers.current;
    return () => { stop(); all.forEach((id) => window.clearTimeout(id)); all.clear(); };
  }, [connect]);

  const dismiss = (id: string) => { window.clearTimeout(timers.current.get(id)); setToasts((ts) => ts.filter((x) => x.e.event_id !== id)); };
  return (
    <div className="toasts" aria-label={t("notify.region")}>
      {toasts.map(({ e, alert }) => {
        const p = eventPlate(e);
        return (
          <div key={e.event_id} className={`toast raised${alert ? " toast-alert" : ""}`} role={alert ? "alert" : "status"}>
            <div className="toast-head">
              {alert ? <ShieldBan size={18} className="bad" aria-hidden="true" /> : <span className="dot" aria-hidden="true" style={{ background: "var(--ok)" }} />}
              <strong className={alert ? "bad" : undefined}>{alert ? t("live.alert") : t("notify.plate")}</strong>
              <span className="muted toast-meta">{e.camera_id} · {fmtTime(e.timestamp)}</span>
              <Btn icon={X} iconOnly variant="ghost" className="btn-sm toast-close" label={t("live.dismiss")} onClick={() => dismiss(e.event_id)} />
            </div>
            <div className="toast-body">
              {p ? <PlateView format={p.format} values={p.values} zone={e.zone} label={`${t("col.plate")} ${e.plate_string_fa}`} /> : <Plate e={e} />}
              <ListBadge status={e.list_status} />
              <Link className="icon-link" to={`/events/${e.event_id}`} onClick={() => dismiss(e.event_id)}><Eye size={16} aria-hidden="true" />{t("live.details")}</Link>
            </div>
          </div>
        );
      })}
    </div>
  );
}
