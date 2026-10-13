// People search: persons recognized by face (or linked to plates), searchable by name; every name can be changed
// in place. Unnamed persons were started by the face matcher and show as "Unknown #id" until someone names them.
import { Check, Eye, Pencil, Search, UserPlus, UserRound, X } from "lucide-react";
import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, ListPage, ListStatus, PersonEntry, api, faceUrl, json, query } from "../api";
import { Btn, useActions } from "../components/Button";
import { ListSwitch, StateView, fmtTime, useApi } from "../components/ui";
import { Key, useI18n } from "../i18n";

export function personName(p: { id: number; full_name: string; auto_named?: boolean },
  t: (k: Key, v?: Record<string, string | number>) => string) {
  return p.auto_named || !p.full_name ? t("people.unnamedName", { id: p.id }) : p.full_name;
}

export function FaceThumb({ id, size = 72, alt }: { id?: string | null; size?: number; alt: string }) {
  const [failed, setFailed] = useState(false);       // image deleted or not readable: show the placeholder
  return id && !failed ? <img className="face-thumb" src={faceUrl(id)} alt={alt} width={size} height={size} loading="lazy" onError={() => setFailed(true)} />
    : <span className="face-thumb empty" style={{ width: size, height: size }} aria-hidden="true"><UserRound size={size / 2} /></span>;
}

// Inline rename: the name becomes an input; Enter saves (only after the server confirmed), Escape cancels.
export function RenameField({ p, canEdit, onSaved }: { p: PersonEntry; canEdit: boolean; onSaved: (p: PersonEntry) => void }) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(p.auto_named ? "" : p.full_name);
  const [err, setErr] = useState<string | null>(null);
  const actions = useActions();
  const shown = personName(p, t);
  async function save(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setErr(null);
    try {
      const out = await actions.run("save", () => api<PersonEntry>(`/persons/${p.id}`, json({ full_name: name.trim() }, "PATCH")));
      if (out) { onSaved(out); setEditing(false); }
    } catch (x) { setErr(x instanceof ApiError ? x.message : "error"); }
  }
  if (!editing) return (
    <span className="row person-name">
      <strong className={p.auto_named ? "muted" : undefined}>{shown}</strong>
      {canEdit && <Btn icon={Pencil} iconOnly variant="ghost" className="btn-sm" label={t("people.rename")}
        onClick={() => { setName(p.auto_named ? "" : p.full_name); setEditing(true); }} />}
    </span>
  );
  return (
    <form className="row rename" onSubmit={save} onKeyDown={(e) => e.key === "Escape" && setEditing(false)}>
      <label className="sr-only" htmlFor={`name-${p.id}`}>{t("people.nameFor", { name: shown })}</label>
      <input id={`name-${p.id}`} className="inset" autoFocus dir="auto" maxLength={128} value={name}
        onChange={(e) => setName(e.target.value)} placeholder={shown} />
      <Btn type="submit" icon={Check} iconOnly className="btn-sm" variant="primary" label={t("people.save")} state={actions.state("save")} />
      <Btn icon={X} iconOnly className="btn-sm" variant="ghost" label={t("people.cancel")} onClick={() => setEditing(false)} />
      {err && <span className="bad" role="alert">{err}</span>}
    </form>
  );
}

export function People({ role }: { role: string }) {
  const { t } = useI18n();
  const canEdit = role === "admin" || role === "operator";
  const [q, setQ] = useState("");
  const [applied, setApplied] = useState("");
  const [named, setNamed] = useState<"" | "true" | "false">("");
  const [sort, setSort] = useState<"recent" | "name">("recent");
  const [msg, setMsg] = useState<string | null>(null);
  const page = useApi<ListPage<PersonEntry>>(`/persons${query({ q: applied, named, sort, limit: 120 })}`);
  const [patched, setPatched] = useState<Record<number, PersonEntry>>({});
  const actions = useActions();
  const [moving, setMoving] = useState<Record<number, ListStatus>>({});
  const items = (page.data?.items ?? []).map((p) => patched[p.id] ?? p);

  async function move(p: PersonEntry, to: ListStatus) {
    setMoving((m) => ({ ...m, [p.id]: to }));
    try {
      const out = await actions.run(`l-${p.id}`, () => api<PersonEntry>(`/persons/${p.id}`, json({ list_status: to }, "PATCH")));
      if (out) setPatched((m) => ({ ...m, [p.id]: { ...p, ...out } }));
    } catch (x) { setMsg(x instanceof ApiError ? x.message : "error"); }
  }
  return (
    <>
      <div className="title-row"><h1>{t("people.title")}</h1>
        {canEdit && <Link className="btn btn-x v-primary icon-link" to="/people/register"><UserPlus size={18} aria-hidden="true" />{t("reg.title")}</Link>}</div>
      <p className="sub">{t("people.sub")}</p>
      <form className="card raised row people-filters" role="search" onSubmit={(e) => { e.preventDefault(); setApplied(q); }}>
        <label className="input-icon grow"><span className="sr-only">{t("people.search")}</span>
          <Search size={16} aria-hidden="true" />
          <input className="inset" dir="auto" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("people.search")} />
        </label>
        <Btn type="submit" variant="primary" icon={Search} state={page.loading && !!applied ? "busy" : "idle"}>{t("hist.search")}</Btn>
        <div role="radiogroup" aria-label={t("people.named")} className="row seg">
          {([["", "people.all"], ["true", "people.named"], ["false", "people.unnamed"]] as const).map(([v, k]) => (
            <Btn key={v} role="radio" aria-checked={named === v} className={named === v ? "inset" : ""} onClick={() => setNamed(v)}>{t(k)}</Btn>
          ))}
        </div>
        <label>{t("people.sort")}
          <select className="inset" value={sort} onChange={(e) => setSort(e.target.value as "recent" | "name")}>
            <option value="recent">{t("people.sortRecent")}</option><option value="name">{t("people.sortName")}</option>
          </select>
        </label>
      </form>
      {msg && <div className="banner inset" role="status">{msg}</div>}
      <StateView hasData={!!page.data} loading={page.loading} error={page.error} empty={!items.length} emptyText={t("people.none")} onRetry={page.reload}>
        <div className="person-grid">
          {items.map((p) => (
            <article key={p.id} className="card raised person-card">
              <Link to={`/people/${p.id}`} className="person-face" aria-label={`${t("people.open")}: ${personName(p, t)}`}>
                <FaceThumb id={p.cover_face} size={88} alt="" />
              </Link>
              <div className="person-info">
                <RenameField p={p} canEdit={canEdit} onSaved={(out) => { setPatched((m) => ({ ...m, [p.id]: { ...p, ...out } })); setMsg(t("people.renamed", { name: out.full_name })); }} />
                <span className="muted small">{t("people.faces", { n: p.faces ?? 0 })} · {t("people.plates", { n: p.plates })}</span>
                <span className="muted small">{p.last_seen ? t("people.lastSeen", { time: fmtTime(p.last_seen) }) : t("people.never")}</span>
                <ListSwitch value={p.list_status} label={personName(p, t)} disabled={!canEdit} onChange={(to) => move(p, to)}
                  state={actions.state(`l-${p.id}`)} pending={moving[p.id] ?? null} />
              </div>
              <Link className="icon-link person-open" to={`/people/${p.id}`}><Eye size={16} aria-hidden="true" />{t("people.open")}</Link>
            </article>
          ))}
        </div>
      </StateView>
    </>
  );
}
