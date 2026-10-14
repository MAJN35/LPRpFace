import { ChevronLeft, ChevronRight, Download, Eraser, RefreshCw, Search } from "lucide-react";
import { FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Page, auth, query } from "../api";
import { Btn } from "../components/Button";
import { ListBadge, Plate, PlateType, StateView, Validity, fmtTime, useApi } from "../components/ui";
import { useI18n } from "../i18n";
import { PlateDraft, PlateSearch, emptyDraft } from "../plate/PlateSearch";
import { FORMATS, PlateFormat, formatById, isComplete, plateQuery, valuesFromTokens } from "../plate/formats";

const LIMIT = 25;
type F = { q: string; camera_id: string; from: string; to: string; is_valid: string; model_version: string; list_status: string };
const EMPTY: F = { q: "", camera_id: "", from: "", to: "", is_valid: "", model_version: "", list_status: "" };
const iso = (local: string) => (local ? new Date(local).toISOString() : "");

// The applied search lives in the URL (?type=standard&slots=1,2,Be,,,,,&match=partial&...), so a result opened and
// closed comes back to the same search and a search can be bookmarked.
function fromUrl(p: URLSearchParams): { f: F; plate: PlateDraft; offset: number } {
  const f = Object.fromEntries(Object.keys(EMPTY).map((k) => [k, p.get(k) ?? ""])) as F;
  const type = (FORMATS.find((x) => x.id === p.get("type"))?.id ?? "standard") as PlateFormat["id"];
  const fmt = formatById(type);
  const plate: PlateDraft = {
    type, values: valuesFromTokens(fmt, (p.get("slots") ?? "").split(",")),
    match: p.get("match") === "exact" ? "exact" : "partial", zone: fmt.zone ? p.get("zone") ?? "" : "",
  };
  return { f, plate, offset: Math.max(0, Number(p.get("offset")) || 0) };
}

function toUrl(f: F, plate: PlateDraft, offset: number) {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(f)) if (v) out[k] = v;
  if (plate.type !== "standard") out.type = plate.type;
  if (plate.values.some(Boolean)) out.slots = plate.values.map((v) => v?.name ?? "").join(",");
  if (plate.match === "exact") out.match = "exact";
  if (plate.zone) out.zone = plate.zone;
  if (offset) out.offset = String(offset);
  return out;
}

export function History() {
  const { t, num } = useI18n();
  const [params, setParams] = useSearchParams();
  const applied = fromUrl(params);
  const [draft, setDraft] = useState<F>(applied.f);
  const [plate, setPlate] = useState<PlateDraft>(applied.plate);
  const [plateErr, setPlateErr] = useState<string | null>(null);
  const [moreOpen] = useState(() => Object.values(applied.f).some(Boolean));
  const af = applied.f, ap = applied.plate, offset = applied.offset;
  const plateParams = plateQuery(formatById(ap.type), ap.values, ap.match, ap.zone);
  const filters = { ...af, from: iso(af.from), to: iso(af.to), ...plateParams };
  const page = useApi<Page>(`/events${query({ ...filters, limit: LIMIT, offset })}`);
  const set = (k: keyof F) => (e: { target: { value: string } }) => setDraft({ ...draft, [k]: e.target.value });

  function apply(e: FormEvent) {
    e.preventDefault();
    if (plate.match === "exact" && !isComplete(plate.values)) { setPlateErr(t("plate.exactNeedsAll")); return; }
    setPlateErr(null);
    setParams(toUrl(draft, plate, 0));
  }
  function clear() { setDraft(EMPTY); setPlate(emptyDraft()); setPlateErr(null); setParams({}); }
  const goto = (o: number) => setParams(toUrl(af, ap, o));
  const total = page.data?.total ?? 0;
  const csv = `/api/v1/events/export.csv${query({ q: af.q, camera_id: af.camera_id, from: iso(af.from), to: iso(af.to), ...plateParams, token: auth.token })}`;
  return (
    <>
      <h1>{t("hist.title")}</h1><p className="sub">{t("hist.sub")}</p>
      <form className="card raised" onSubmit={apply} role="search" aria-label={t("hist.title")} noValidate>
        <PlateSearch draft={plate} onChange={setPlate} error={plateErr} onError={setPlateErr} />
        <details className="more-filters" open={moreOpen}>
          <summary>{t("hist.filters")}</summary>
          <div className="filters">
            <label>{t("hist.freeText")}<input className="inset" dir="auto" value={draft.q} onChange={set("q")} placeholder="۳۴۵" /></label>
            <label>{t("hist.camera")}<input className="inset" dir="ltr" value={draft.camera_id} onChange={set("camera_id")} /></label>
            <label>{t("hist.from")}<input className="inset" type="datetime-local" value={draft.from} onChange={set("from")} /></label>
            <label>{t("hist.to")}<input className="inset" type="datetime-local" value={draft.to} onChange={set("to")} /></label>
            <label>{t("hist.validity")}<select className="inset" value={draft.is_valid} onChange={set("is_valid")}><option value="">{t("hist.any")}</option><option value="true">{t("hist.valid")}</option><option value="false">{t("hist.invalid")}</option></select></label>
            <label>{t("hist.list")}<select className="inset" value={draft.list_status} onChange={set("list_status")}><option value="">{t("hist.any")}</option><option value="whitelist">{t("list.whitelist")}</option><option value="blocklist">{t("list.blocklist")}</option><option value="unknown">{t("list.unknown")}</option></select></label>
            <label>{t("hist.model")}<select className="inset" value={draft.model_version} onChange={set("model_version")}><option value="">{t("hist.any")}</option><option>v1</option><option>v2</option><option>v3m</option></select></label>
          </div>
        </details>
        <div className="row form-actions"><Btn type="submit" variant="primary" icon={Search} state={page.loading ? "busy" : "idle"}>{t("hist.search")}</Btn><Btn icon={Eraser} onClick={clear}>{t("hist.clear")}</Btn></div>
      </form>
      <section className="card raised" aria-label={t("hist.results")}>
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
          <span className="muted" aria-live="polite">{page.data ? t("hist.count", { n: total }) : ""}</span>
          <span className="row" style={{ gap: 8 }}>
            <Btn icon={RefreshCw} iconOnly variant="ghost" spin={page.loading} label={t("common.refresh")} onClick={page.reload} />
            <a className="btn icon-link" href={csv}><Download size={18} aria-hidden="true" />{t("hist.export")}</a>
          </span>
        </div>
        <StateView hasData={!!page.data} loading={page.loading} error={page.error} empty={!page.data?.items.length} emptyText={t("hist.noMatch")} onRetry={page.reload}>
          <div className="table-wrap"><table><thead><tr><th>{t("col.time")}</th><th>{t("col.camera")}</th><th>{t("col.plate")}</th><th>{t("col.type")}</th><th>{t("col.list")}</th><th>{t("col.model")}</th><th>{t("col.confidence")}</th><th>{t("col.status")}</th></tr></thead><tbody>
            {page.data?.items.map((e) => (
              <tr key={e.event_id}><td><Link to={`/events/${e.event_id}`}>{fmtTime(e.timestamp)}</Link></td><td>{e.camera_id}</td><td><Plate e={e} /></td>
                <td><PlateType type={e.plate_type} /></td><td><ListBadge status={e.list_status} /></td><td>{e.model_version}</td><td>{num((e.confidence * 100).toFixed(0))} %</td><td><Validity e={e} /></td></tr>
            ))}
          </tbody></table></div>
          <nav className="row" aria-label={t("hist.pages")} style={{ marginTop: 12 }}>
            <Btn icon={ChevronLeft} flipRtl disabled={offset === 0} onClick={() => goto(Math.max(0, offset - LIMIT))}>{t("hist.prev")}</Btn>
            <span className="muted">{t("hist.range", { from: offset + 1, to: Math.min(offset + LIMIT, total), total })}</span>
            <Btn icon={ChevronRight} flipRtl className="icon-end" disabled={offset + LIMIT >= total} onClick={() => goto(offset + LIMIT)}>{t("hist.next")}</Btn>
          </nav>
        </StateView>
      </section>
    </>
  );
}
