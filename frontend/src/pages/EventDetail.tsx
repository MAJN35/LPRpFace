import { ArrowLeft, Copy } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ApiError, EventDetail as Detail, ListStatus, PlateEntry, api, cropUrl, json } from "../api";
import { Btn, useActions } from "../components/Button";
import { copyText } from "../components/copy";
import { ListBadge, ListSwitch, Plate, PlateType, StateView, Validity, fmtTime, useApi, useListLabel } from "../components/ui";
import { useI18n } from "../i18n";

export function EventDetail({ role = "viewer" }: { role?: string }) {
  const { id } = useParams();
  const { t, num } = useI18n();
  const listLabel = useListLabel();
  const ev = useApi<Detail>(id ? `/events/${id}` : null);
  const e = ev.data;
  const canEdit = role === "admin" || role === "operator";
  const [current, setCurrent] = useState<ListStatus | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [pending, setPending] = useState<ListStatus | null>(null);
  const actions = useActions();
  const navigate = useNavigate();
  async function putOnList(to: ListStatus) {
    if (!e) return;
    setPending(to);
    try {
      const p = await actions.run("list", () => api<PlateEntry>("/plates", json({ plate: e.plate_string_latin, list_status: to, upsert: true })));
      if (p) { setCurrent(p.list_status); setMsg(t("ev.nowOn", { list: listLabel(p.list_status) })); }
    } catch (err) { setMsg(t("ev.failed", { m: err instanceof ApiError ? err.message : "" })); }
  }
  return (
    <>
      <div className="page-head">
        <Btn icon={ArrowLeft} flipRtl variant="ghost" onClick={() => navigate(-1)}>{t("ev.back")}</Btn>
      </div>
      <h1>{t("ev.title")}</h1><p className="sub">{t("ev.sub")}</p>
      <StateView hasData={!!ev.data} loading={ev.loading} error={ev.error} onRetry={ev.reload}>
        {e && (
          <div className="grid2">
            <section className="card raised" aria-labelledby="ev-h">
              <div className="row" style={{ justifyContent: "space-between" }}><h2 id="ev-h"><Plate e={e} /></h2>
                {e.plate_string_latin && <Btn icon={Copy} iconOnly variant="ghost" label={t("ev.copy")} state={actions.state("copy")}
                  onClick={() => actions.run("copy", () => copyText(`${e.plate_string_fa} (${e.plate_string_latin})`)).catch(() => undefined)} />}</div>
              <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "6px 16px", margin: 0 }}>
                <dt className="muted">{t("ev.time")}</dt><dd>{fmtTime(e.timestamp)}</dd>
                <dt className="muted">{t("ev.source")}</dt><dd>{e.camera_id} ({e.source_type}){e.source_file ? ` · ${e.source_file}` : ""}</dd>
                <dt className="muted">{t("ev.type")}</dt><dd><PlateType type={e.plate_type} />{e.zone ? ` · ${e.zone}` : ""}{e.markers.length ? ` · ${e.markers.join(", ")}` : ""}{e.expiry ? ` · ${t("ev.expiry", { v: num(e.expiry) })}` : ""}</dd>
                <dt className="muted">{t("ev.status")}</dt><dd><Validity e={e} /></dd>
                <dt className="muted">{t("ev.conf")}</dt><dd>{t("ev.voted", { conf: `${num((e.confidence * 100).toFixed(1))} %`, n: e.frames_voted })}{e.track_id != null ? t("ev.track", { id: e.track_id }) : ""}</dd>
                <dt className="muted">{t("ev.listAt")}</dt><dd><ListBadge status={e.list_status} />{e.person ? ` · ${e.person.full_name}` : ""}</dd>
                <dt className="muted">{t("ev.model")}</dt><dd dir="ltr">{e.model_version} · {e.precision} · <code title={e.model_sha256}>{e.model_sha256.slice(0, 12)}…</code></dd>
              </dl>
              {canEdit && e.is_valid && e.plate_string_latin && (<>
                <h2 style={{ marginTop: 20 }}>{t("ev.putOnList")}</h2>
                <ListSwitch value={current ?? e.list_status} label={e.plate_string_latin} onChange={putOnList} pending={pending} state={actions.state("list")} />
                {msg && <p role="status" className="muted">{msg}</p>}
              </>)}
              <h2 style={{ marginTop: 20 }}>{t("ev.chars")}</h2>
              <div className="table-wrap"><table><thead><tr><th>#</th><th>{t("ev.class")}</th><th>{t("col.confidence")}</th><th>{t("ev.margin")}</th></tr></thead><tbody>
                {e.characters.map((c, i) => <tr key={i}><td>{num(i + 1)}</td><td>{c.name}</td><td>{num((c.confidence * 100).toFixed(1))} %</td><td>{c.margin != null ? num((c.margin * 100).toFixed(1)) + " %" : "–"}</td></tr>)}
              </tbody></table></div>
            </section>
            <section className="card raised" aria-labelledby="crop-h"><h2 id="crop-h">{t("ev.evidence")}</h2>
              {e.has_crop ? <img className="crop" src={cropUrl(e.event_id)} alt={t("ev.cropAlt", { plate: e.plate_string_latin })} /> : <div className="state">{t("ev.noCrop")}</div>}
            </section>
          </div>
        )}
      </StateView>
    </>
  );
}
