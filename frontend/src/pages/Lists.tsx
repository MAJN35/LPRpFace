import { FormEvent, useState } from "react";
import { ApiError, LISTS, ListPage, ListStatus, PersonEntry, PlateEntry, Unregistered, api, json, query } from "../api";
import { CarFront, Plus, Search, Trash2, UserPlus, UserRound, X } from "lucide-react";
import { ActionState, Btn, useActions } from "../components/Button";
import { LIST_ICON, ListBadge, ListSwitch, Plate, StateView, fmtTime, useApi, useListLabel } from "../components/ui";
import { useI18n } from "../i18n";

type Kind = "plate" | "person";

export function Lists({ role }: { role: string }) {
  const { t, num } = useI18n();
  const listLabel = useListLabel();
  const canEdit = role === "admin" || role === "operator";
  const [kind, setKind] = useState<Kind>("plate");
  const [list, setList] = useState<ListStatus>("blocklist");
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const path = kind === "plate" ? "/plates" : "/persons";
  const page = useApi<ListPage<PlateEntry | PersonEntry>>(`${path}${query({ list_status: list, q, limit: 200 })}`);
  const counts = {
    whitelist: useApi<ListPage<unknown>>(`${path}${query({ list_status: "whitelist", limit: 1 })}`),
    blocklist: useApi<ListPage<unknown>>(`${path}${query({ list_status: "blocklist", limit: 1 })}`),
    unknown: useApi<ListPage<unknown>>(`${path}${query({ list_status: "unknown", limit: 1 })}`),
  };
  const persons = useApi<ListPage<PersonEntry>>(`/persons${query({ limit: 500 })}`);
  const unreg = useApi<Unregistered[]>(kind === "plate" && list === "unknown" ? "/plates/unregistered?days=7" : null);

  const refresh = () => { page.reload(); LISTS.forEach((s) => counts[s].reload()); unreg.reload(); persons.reload(); setSelected([]); };
  const actions = useActions();
  // One run per key; the message and the success mark appear only after the backend confirmed the change.
  const run: Run = async (key, fn, ok) => {
    setMsg(null);
    try { await actions.run(key, fn); setMsg({ text: ok }); refresh(); }
    catch (e) { setMsg({ text: t("set.failed", { m: e instanceof ApiError ? e.message : "" }), bad: true }); }
  };
  const move = (id: number, name: string, to: ListStatus) =>
    run(`mv-${kind}-${id}-${to}`, () => api(`${path}/${id}`, json({ list_status: to }, "PATCH")), t("lists.moved", { name, list: listLabel(to) }));
  const bulk = (to: ListStatus) =>
    run(`bulk-${to}`, () => api("/lists/move", json({ kind, ids: selected, list_status: to })), t("lists.movedN", { n: selected.length, list: listLabel(to) }));
  // The list a row is being moved to (spinner on that button) and the state of that move.
  const rowMove = (prefix: string): { pending: ListStatus | null; state: ActionState } => {
    const to = LISTS.find((s) => actions.state(`${prefix}-${s}`) !== "idle") ?? null;
    return { pending: to, state: to ? actions.state(`${prefix}-${to}`) : "idle" };
  };
  const toggle = (id: number) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const items = page.data?.items ?? [];

  return (
    <>
      <h1>{t("lists.title")}</h1>
      <p className="sub">{t("lists.sub")}</p>
      {msg && <div className="banner inset" role="status"><span className={msg.bad ? "bad" : "ok"}>{msg.text}</span></div>}
      <div className="row" role="tablist" aria-label={t("lists.kind")} style={{ marginBottom: 14 }}>
        {(["plate", "person"] as Kind[]).map((k) => (
          <Btn key={k} role="tab" icon={k === "plate" ? CarFront : UserRound} aria-selected={kind === k} className={kind === k ? "inset" : ""}
            onClick={() => { setKind(k); setSelected([]); }}>{k === "plate" ? t("lists.plates") : t("lists.persons")}</Btn>
        ))}
      </div>
      <div className="row" role="tablist" aria-label={t("lists.list")} style={{ marginBottom: 14 }}>
        {LISTS.map((s) => (
          <Btn key={s} role="tab" icon={LIST_ICON[s]} aria-selected={list === s} className={list === s ? "inset" : ""}
            onClick={() => { setList(s); setSelected([]); }}>
            {listLabel(s)} <span className="muted">({counts[s].data ? num(counts[s].data!.total) : "…"})</span></Btn>
        ))}
        <label className="input-icon" style={{ marginInlineStart: "auto" }}><span className="sr-only">{t("lists.search")}</span>
          <Search size={16} aria-hidden="true" />
          <input className="inset" dir="auto" placeholder={kind === "plate" ? t("lists.searchPlate") : t("lists.searchName")}
            value={q} onChange={(e) => setQ(e.target.value)} /></label>
      </div>

      {canEdit && selected.length > 0 && (
        <div className="banner inset row" role="region" aria-label={t("lists.bulk")}>
          <span>{t("lists.selected", { n: selected.length })}</span>
          {LISTS.filter((s) => s !== list).map((s) => <Btn key={s} icon={LIST_ICON[s]} state={actions.state(`bulk-${s}`)} onClick={() => bulk(s)}>{listLabel(s)}</Btn>)}
          <Btn icon={X} variant="ghost" onClick={() => setSelected([])}>{t("lists.clear")}</Btn>
        </div>
      )}

      <section className="card raised" aria-label={`${listLabel(list)} · ${kind === "plate" ? t("lists.plates") : t("lists.persons")}`}>
        <StateView hasData={!!page.data} loading={page.loading} error={page.error} empty={!items.length} onRetry={page.reload}
          emptyText={t("lists.empty", { list: listLabel(list) })}>
          <div className="table-wrap"><table>
            <thead><tr>{canEdit && <th><span className="sr-only">{t("lists.select", { name: "" })}</span></th>}
              {kind === "plate" ? <><th>{t("col.plate")}</th><th>{t("lists.person")}</th><th>{t("lists.effective")}</th><th>{t("lists.lastSeen")}</th></> : <><th>{t("lists.name")}</th><th>{t("lists.plates")}</th><th>{t("lists.notes")}</th></>}
              <th>{t("col.list")}</th>{canEdit && <th><span className="sr-only">{t("lists.delete")}</span></th>}</tr></thead>
            <tbody>
              {items.map((it) => {
                const name = kind === "plate" ? (it as PlateEntry).plate_string_latin : (it as PersonEntry).full_name;
                return (
                  <tr key={it.id}>
                    {canEdit && <td><input type="checkbox" aria-label={t("lists.select", { name })} checked={selected.includes(it.id)} onChange={() => toggle(it.id)} /></td>}
                    {kind === "plate" ? (() => { const p = it as PlateEntry; return <>
                      <td><Plate e={{ ...p, zone: null }} /></td>
                      <td>{canEdit ? (
                        <select className="inset" aria-label={t("lists.personFor", { plate: p.plate_string_latin })} value={p.person_id ?? 0}
                          onChange={(e) => run(`link-${p.id}`, () => api(`/plates/${p.id}`, json({ person_id: Number(e.target.value) }, "PATCH")), t("lists.linkUpdated"))}>
                          <option value={0}>—</option>
                          {persons.data?.items.map((pe) => <option key={pe.id} value={pe.id}>{pe.full_name}</option>)}
                        </select>) : (p.person_name ?? "—")}</td>
                      <td><ListBadge status={p.effective_status} /></td>
                      <td className="muted">{p.last_seen ? fmtTime(p.last_seen) : t("lists.never")}</td></>; })()
                      : (() => { const pe = it as PersonEntry; return <>
                        <td>{pe.full_name}</td><td>{num(pe.plates)}</td><td className="muted">{pe.notes}</td></>; })()}
                    <td><ListSwitch value={it.list_status} disabled={!canEdit} label={name} onChange={(to) => move(it.id, name, to)} {...rowMove(`mv-${kind}-${it.id}`)} /></td>
                    {canEdit && <td><Btn icon={Trash2} variant="danger" className="btn-sm" aria-label={t("lists.deleteName", { name })} state={actions.state(`del-${kind}-${it.id}`)}
                      onClick={() => run(`del-${kind}-${it.id}`, () => api(`${path}/${it.id}`, { method: "DELETE" }), t("lists.deleted", { name }))}>{t("lists.delete")}</Btn></td>}
                  </tr>
                );
              })}
            </tbody>
          </table></div>
        </StateView>
      </section>

      {kind === "plate" && list === "unknown" && (
        <section className="card raised" aria-labelledby="unreg-h"><h2 id="unreg-h">{t("lists.unreg")}</h2>
          <StateView hasData={!!unreg.data} loading={unreg.loading} error={unreg.error} empty={!unreg.data?.length} emptyText={t("lists.unregEmpty")} onRetry={unreg.reload}>
            <div className="table-wrap"><table><thead><tr><th>{t("col.plate")}</th><th>{t("lists.sightings")}</th><th>{t("lists.lastSeen")}</th><th>{t("lists.putOn")}</th></tr></thead><tbody>
              {unreg.data?.map((u) => (
                <tr key={u.plate_key}>
                  <td><Plate e={{ ...u, zone: null }} /></td>
                  <td>{num(u.sightings)}</td><td className="muted">{fmtTime(u.last_seen)}</td>
                  <td>{canEdit && <ListSwitch value={"unknown"} label={u.plate_string_latin} {...rowMove(`unreg-${u.plate_key}`)} onChange={(to) =>
                    run(`unreg-${u.plate_key}-${to}`, () => api("/plates", json({ plate: u.plate_string_latin, list_status: to, upsert: true })), t("lists.addedTo", { name: u.plate_string_latin, list: listLabel(to) }))} />}</td>
                </tr>
              ))}
            </tbody></table></div>
          </StateView>
        </section>
      )}

      {canEdit && (kind === "plate" ? <AddPlate list={list} persons={persons.data?.items ?? []} run={run} state={actions.state("add-plate")} />
        : <AddPerson list={list} run={run} state={actions.state("add-person")} />)}
    </>
  );
}

type Run = (key: string, fn: () => Promise<unknown>, ok: string) => Promise<void>;

function AddPlate({ list, persons, run, state }: { list: ListStatus; persons: PersonEntry[]; run: Run; state: ActionState }) {
  const { t } = useI18n();
  const listLabel = useListLabel();
  const [plate, setPlate] = useState(""); const [person, setPerson] = useState(0); const [notes, setNotes] = useState("");
  function submit(e: FormEvent) {
    e.preventDefault();
    run("add-plate", () => api("/plates", json({ plate, list_status: list, person_id: person || null, notes })), t("lists.addedTo", { name: plate, list: listLabel(list) }))
      .then(() => { setPlate(""); setNotes(""); });
  }
  return (
    <form className="card raised filters" onSubmit={submit} aria-label={t("lists.addPlate")}>
      <label>{t("lists.plateInput")}<input className="inset" dir="auto" required value={plate} onChange={(e) => setPlate(e.target.value)} placeholder="e.g. 12B34567" /></label>
      <label>{t("lists.person")}<select className="inset" value={person} onChange={(e) => setPerson(Number(e.target.value))}>
        <option value={0}>—</option>{persons.map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}</select></label>
      <label>{t("lists.notes")}<input className="inset" value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
      <Btn type="submit" variant="primary" icon={Plus} state={state}>{t("lists.addTo", { list: listLabel(list) })}</Btn>
    </form>
  );
}

function AddPerson({ list, run, state }: { list: ListStatus; run: Run; state: ActionState }) {
  const { t } = useI18n();
  const listLabel = useListLabel();
  const [name, setName] = useState(""); const [notes, setNotes] = useState("");
  function submit(e: FormEvent) {
    e.preventDefault();
    run("add-person", () => api("/persons", json({ full_name: name, notes, list_status: list })), t("lists.addedTo", { name, list: listLabel(list) }))
      .then(() => { setName(""); setNotes(""); });
  }
  return (
    <form className="card raised filters" onSubmit={submit} aria-label={t("lists.addPerson")}>
      <label>{t("lists.name")}<input className="inset" required value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label>{t("lists.notes")}<input className="inset" value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
      <Btn type="submit" variant="primary" icon={UserPlus} state={state}>{t("lists.addTo", { list: listLabel(list) })}</Btn>
    </form>
  );
}
