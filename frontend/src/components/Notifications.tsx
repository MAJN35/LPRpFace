// A notification for every recognized plate and face, on every page (live WebSocket through nginx): in-page toasts,
// and OS notifications (systemNotify.ts) while the dashboard is not in front. Ordinary detections close after a few
// seconds and can be muted (bell, localStorage "lpr.notify"); blocklist hits (plate or person) always appear and
// stay until dismissed. Nothing leaves the device: no push service.
import { Eye, ShieldBan, UserRound, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { EventSummary, FaceSummary, connectLive, faceUrl } from "../api";
import { useI18n } from "../i18n";
import { Btn } from "./Button";
import { showSystem } from "./systemNotify";
import { ListBadge, Plate, fmtTime } from "./ui";

const KEY = "lpr.notify";
const MAX = 4;
const PLATE_MS = 6000;

export function readNotify(): boolean { try { return localStorage.getItem(KEY) !== "off"; } catch { return true; } }
export function storeNotify(on: boolean) { try { localStorage.setItem(KEY, on ? "on" : "off"); } catch { /* storage blocked */ } }

type Toast = { id: string; alert: boolean } & ({ kind: "plate"; e: EventSummary } | { kind: "face"; f: FaceSummary });

export function Notifications({ enabled, connect = connectLive }: { enabled: boolean; connect?: typeof connectLive }) {
  const { t } = useI18n();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const on = useRef(enabled);
  on.current = enabled;
  const tr = useRef(t);
  tr.current = t;
  const timers = useRef(new Map<string, number>());

  useEffect(() => {
    const close = (id: string) => setToasts((ts) => ts.filter((x) => x.id !== id));
    const push = (toast: Toast) => {
      if (!toast.alert && !on.current) return;
      setToasts((ts) => {
        const old = ts.find((x) => x.id === toast.id);
        return [{ ...toast, alert: toast.alert || !!old?.alert }, ...ts.filter((x) => x.id !== toast.id)].slice(0, MAX);
      });
      window.clearTimeout(timers.current.get(toast.id));
      if (!toast.alert) timers.current.set(toast.id, window.setTimeout(() => close(toast.id), PLATE_MS));
      else timers.current.delete(toast.id);
      const tt = tr.current;
      if (toast.kind === "plate") {
        showSystem(toast.alert ? tt("live.alert") : tt("notify.plate"),
          `${toast.e.plate_string_fa || toast.e.plate_string_latin} · ${toast.e.camera_id}`, `/events/${toast.e.event_id}`,
          { alert: toast.alert, tag: toast.id });
      } else {
        const who = toast.f.person_id ? (toast.f.person_auto || !toast.f.person_name
          ? tt("people.unnamedName", { id: toast.f.person_id }) : toast.f.person_name) : tt("notify.face");
        showSystem(toast.alert ? tt("notify.faceAlert") : tt("notify.face"), `${who} · ${toast.f.camera_id}`,
          toast.f.person_id ? `/people/${toast.f.person_id}` : "/library",
          { alert: toast.alert, tag: toast.id, image: toast.f.has_snapshot ? faceUrl(toast.f.id) : undefined });
      }
    };
    const stop = connect(
      (e) => push({ kind: "plate", id: e.event_id, e, alert: e.list_status === "blocklist" }), () => undefined,
      (e) => push({ kind: "plate", id: e.event_id, e, alert: true }),
      (f, alert) => push({ kind: "face", id: f.id, f, alert: alert || f.list_status === "blocklist" }));
    const all = timers.current;
    return () => { stop(); all.forEach((id) => window.clearTimeout(id)); all.clear(); };
  }, [connect]);

  const dismiss = (id: string) => { window.clearTimeout(timers.current.get(id)); setToasts((ts) => ts.filter((x) => x.id !== id)); };
  return (
    <div className="toasts" aria-label={t("notify.region")}>
      {toasts.map((x) => {
        const camera = x.kind === "plate" ? x.e.camera_id : x.f.camera_id;
        const time = x.kind === "plate" ? x.e.timestamp : x.f.timestamp;
        const title = x.kind === "plate" ? (x.alert ? t("live.alert") : t("notify.plate")) : (x.alert ? t("notify.faceAlert") : t("notify.face"));
        const href = x.kind === "plate" ? `/events/${x.e.event_id}` : x.f.person_id ? `/people/${x.f.person_id}` : "/library";
        return (
          <div key={x.id} className={`toast raised${x.alert ? " toast-alert" : ""}`} role={x.alert ? "alert" : "status"}>
            <div className="toast-head">
              {x.alert ? <ShieldBan size={18} className="bad" aria-hidden="true" />
                : x.kind === "face" ? <UserRound size={18} className="muted" aria-hidden="true" />
                : <span className="dot" aria-hidden="true" style={{ background: "var(--ok)" }} />}
              <strong className={x.alert ? "bad" : undefined}>{title}</strong>
              <span className="muted toast-meta">{camera} · {fmtTime(time)}</span>
              <Btn icon={X} iconOnly variant="ghost" className="btn-sm toast-close" label={t("live.dismiss")} onClick={() => dismiss(x.id)} />
            </div>
            <div className="toast-body">
              {x.kind === "plate" ? <Plate e={x.e} /> : (
                <span className="row" style={{ gap: 10 }}>
                  {x.f.has_snapshot && <img className="face-thumb" src={faceUrl(x.f.id)} alt="" width={48} height={48} />}
                  <strong>{x.f.person_id ? (x.f.person_auto || !x.f.person_name ? t("people.unnamedName", { id: x.f.person_id }) : x.f.person_name) : t("person.match.none")}</strong>
                </span>
              )}
              <ListBadge status={x.kind === "plate" ? x.e.list_status : x.f.list_status} />
              <Link className="icon-link" to={href} onClick={() => dismiss(x.id)}><Eye size={16} aria-hidden="true" />{t("live.details")}</Link>
            </div>
          </div>
        );
      })}
    </div>
  );
}
