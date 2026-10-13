// One person: name (editable), list, faces (move a wrongly matched face to another or a new person, delete it),
// linked plates, merge into another person, delete. Every change is confirmed by the backend before it shows.
import { ArrowLeft, GitMerge, ImagePlus, Trash2, UserPlus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, FaceSummary, ListPage, ListStatus, PersonEntry, PlateEntry, api, json, query } from "../api";
import { Btn, useActions } from "../components/Button";
import { ListBadge, ListSwitch, Plate, StateView, fmtTime, useApi } from "../components/ui";
import { Key, useI18n } from "../i18n";
import { FaceThumb, RenameField, personName } from "./People";

type Detail = { person: PersonEntry; plates: PlateEntry[] };

// Two-step destructive button: the first press asks, the second (within 4 s) does it.
export function ConfirmBtn({ label, confirm, onConfirm, state, iconOnly }: {
  label: string; confirm: string; onConfirm: () => void; state?: "idle" | "busy" | "done" | "error"; iconOnly?: boolean;
}) {
  const [armed, setArmed] = useState(false);
  return (
    <Btn icon={Trash2} variant="danger" className={`btn-sm${armed ? " armed" : ""}`} state={state} iconOnly={iconOnly && !armed}
      label={label} aria-label={armed ? confirm : label}
      onClick={() => { if (armed) { setArmed(false); onConfirm(); } else { setArmed(true); window.setTimeout(() => setArmed(false), 4000); } }}
      onBlur={() => setArmed(false)}>{armed ? confirm : label}</Btn>
  );
}

export function PersonDetail({ role }: { role: string }) {
  const { id } = useParams();
  const pid = Number(id);
  const { t, num } = useI18n();
  const navigate = useNavigate();
  const canEdit = role === "admin" || role === "operator";
  const detail = useApi<Detail>(`/persons/${pid}`);
  const faces = useApi<ListPage<FaceSummary>>(`/faces${query({ person_id: pid, limit: 96 })}`);
  const others = useApi<ListPage<PersonEntry>>(`/persons${query({ sort: "name", limit: 500 })}`);
  const [person, setPerson] = useState<PersonEntry | null>(null);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [mergeInto, setMergeInto] = useState("");
  const [moving, setMoving] = useState<ListStatus | null>(null);
  const actions = useActions();
  const p = person ?? detail.data?.person ?? null;
  const choices = (others.data?.items ?? []).filter((o) => o.id !== pid);

  async function run<T>(key: string, fn: () => Promise<T>, ok?: string): Promise<T | undefined> {
    setMsg(null);
    try {
      const r = await actions.run(key, fn);
      if (ok) setMsg({ text: ok });
      return r;
    } catch (x) { setMsg({ text: t("set.failed", { m: x instanceof ApiError ? x.message : "" }), bad: true }); return undefined; }
  }
  async function moveFace(f: FaceSummary, to: string) {
    const body = to === "new" ? { new_person: true } : { person_id: Number(to) };
    if (await run(`mv-${f.id}`, () => api(`/faces/${f.id}`, json(body, "PATCH")), t("person.moved"))) { faces.reload(); detail.reload(); }
  }
  return (
    <>
      <div className="page-head"><Btn icon={ArrowLeft} flipRtl variant="ghost" onClick={() => navigate(-1)}>{t("person.back")}</Btn></div>
      <h1>{t("person.title")}</h1><p className="sub">{t("person.viewNote")}</p>
      {msg && <div className="banner inset" role="status"><span className={msg.bad ? "bad" : "ok"}>{msg.text}</span></div>}
      <StateView hasData={!!detail.data} loading={detail.loading} error={detail.error} onRetry={detail.reload}>
        {p && (
          <section className="card raised person-head">
            <FaceThumb id={p.cover_face} size={120} alt={personName(p, t)} />
            <div className="person-info">
              <RenameField p={p} canEdit={canEdit} onSaved={(out) => { setPerson({ ...p, ...out }); setMsg({ text: t("people.renamed", { name: out.full_name }) }); }} />
              <span className="muted small">{t("people.faces", { n: p.faces ?? 0 })} · {t("people.plates", { n: p.plates })} · {p.last_seen ? t("people.lastSeen", { time: fmtTime(p.last_seen) }) : t("people.never")}</span>
              <ListSwitch value={p.list_status} label={personName(p, t)} disabled={!canEdit} pending={moving} state={actions.state("list")}
                onChange={async (to) => { setMoving(to); const out = await run("list", () => api<PersonEntry>(`/persons/${pid}`, json({ list_status: to }, "PATCH"))); if (out) setPerson({ ...p, ...out }); }} />
              {canEdit && (
                <div className="row merge-row">
                  <label>{t("person.mergeInto")}
                    <select className="inset" value={mergeInto} onChange={(e) => setMergeInto(e.target.value)}>
                      <option value="">{t("person.pick")}</option>
                      {choices.map((o) => <option key={o.id} value={o.id}>{personName(o, t)}</option>)}
                    </select>
                  </label>
                  <Btn icon={GitMerge} disabled={!mergeInto} state={actions.state("merge")}
                    onClick={async () => { const into = Number(mergeInto); if (await run("merge", () => api(`/persons/${pid}/merge`, json({ into })), t("person.merged"))) navigate(`/people/${into}`, { replace: true }); }}>
                    {t("person.mergeDo")}</Btn>
                  <ConfirmBtn label={t("person.delete")} confirm={t("person.confirm")} state={actions.state("del")}
                    onConfirm={async () => { if (await run("del", () => api(`/persons/${pid}`, { method: "DELETE" }), t("person.deleted"))) navigate("/people", { replace: true }); }} />
                </div>
              )}
            </div>
          </section>
        )}
      </StateView>
      <section className="card raised" aria-labelledby="faces-h">
        <div className="card-head"><h2 id="faces-h">{t("person.facesTitle")} {faces.data ? `(${num(faces.data.total)})` : ""}</h2>
          {canEdit && (
            <label className={`btn-x file-btn btn-sm${actions.state("photos") === "busy" ? " busy" : ""}`}><ImagePlus size={16} aria-hidden="true" /> {t("reg.addPhotos")}
              <input type="file" accept="image/jpeg,image/png" multiple className="sr-only" onChange={async (e) => {
                const files = Array.from(e.target.files ?? []); e.target.value = "";
                if (!files.length) return;
                const fd = new FormData(); files.forEach((f) => fd.append("photos", f, f.name));
                const r = await run("photos", () => api<{ added: number; photos: { ok: boolean }[] }>(`/persons/${pid}/photos`, { method: "POST", body: fd }));
                if (r) { setMsg({ text: t("reg.saved", { ok: r.added, n: r.photos.length }), bad: r.added === 0 }); faces.reload(); detail.reload(); }
              }} />
            </label>
          )}</div>
        <StateView hasData={!!faces.data} loading={faces.loading} error={faces.error} empty={!faces.data?.items.length} emptyText={t("person.noFaces")} onRetry={faces.reload}>
          <div className="face-grid">
            {faces.data?.items.map((f) => (
              <figure key={f.id} className="face-tile inset">
                <FaceThumb id={f.has_snapshot ? f.id : null} size={112} alt={`${personName(p ?? { id: pid, full_name: "" }, t)} ${fmtTime(f.timestamp)}`} />
                <figcaption>
                  <span className="small">{fmtTime(f.timestamp)}</span>
                  <span className="muted small">{f.camera_id} · {t(`person.match.${f.match}` as Key)}{f.similarity != null ? ` · ${t("person.similarity", { v: `${num(Math.round(f.similarity * 100))}%` })}` : ""}</span>
                  <ListBadge status={f.list_status} />
                  {canEdit && (
                    <span className="row face-actions">
                      <label className="sr-only" htmlFor={`mv-${f.id}`}>{t("person.moveFace")}</label>
                      <select id={`mv-${f.id}`} className="inset btn-sm" value="" disabled={actions.state(`mv-${f.id}`) === "busy"}
                        onChange={(e) => e.target.value && moveFace(f, e.target.value)}>
                        <option value="">{t("person.moveFace")}…</option>
                        <option value="new">{t("person.newPerson")}</option>
                        {choices.map((o) => <option key={o.id} value={o.id}>{personName(o, t)}</option>)}
                      </select>
                      <ConfirmBtn iconOnly label={t("person.deleteFace")} confirm={t("person.confirm")} state={actions.state(`df-${f.id}`)}
                        onConfirm={async () => { if (await run(`df-${f.id}`, () => api(`/faces/${f.id}`, { method: "DELETE" }))) faces.reload(); }} />
                    </span>
                  )}
                </figcaption>
              </figure>
            ))}
          </div>
        </StateView>
      </section>
      <section className="card raised" aria-labelledby="plates-h">
        <h2 id="plates-h">{t("person.platesTitle")}</h2>
        {detail.data && !detail.data.plates.length ? <div className="state">{t("person.noPlates")}</div> : (
          <div className="row" style={{ gap: 14 }}>
            {detail.data?.plates.map((pl) => (
              <Link key={pl.id} to={`/history?q=${encodeURIComponent(pl.plate_string_latin)}`} className="row plate-link">
                <Plate e={{ ...pl, zone: null }} /><ListBadge status={pl.list_status} />
              </Link>
            ))}
          </div>
        )}
        {canEdit && <p className="muted small"><UserPlus size={14} aria-hidden="true" /> <Link to="/lists">{t("nav.lists")}</Link></p>}
      </section>
    </>
  );
}
