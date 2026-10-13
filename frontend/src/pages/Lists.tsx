import { FormEvent, useState } from "react";
import { ApiError, LISTS, ListPage, ListStatus, PersonEntry, PlateEntry, Unregistered, api, json, query } from "../api";
import { ListBadge, ListSwitch, StateView, fmtTime, listLabel, useApi } from "../components/ui";

type Kind = "plate" | "person";

export function Lists({ role }: { role: string }) {
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
  async function run(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try { await fn(); setMsg({ text: ok }); refresh(); }
    catch (e) { setMsg({ text: e instanceof ApiError ? e.message : "Failed", bad: true }); }
  }
  const move = (id: number, name: string, to: ListStatus) =>
    run(() => api(`${path}/${id}`, json({ list_status: to }, "PATCH")), `${name} moved to ${listLabel(to)}.`);
  const bulk = (to: ListStatus) =>
    run(() => api("/lists/move", json({ kind, ids: selected, list_status: to })), `${selected.length} moved to ${listLabel(to)}.`);
  const toggle = (id: number) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const items = page.data?.items ?? [];

  return (
    <>
      <h1>Lists</h1>
      <p className="sub">Whitelist, blocklist and unknown for plates and persons. Persons are records linked to plates; nobody is identified by face.</p>
      {msg && <div className="banner inset" role="status"><span className={msg.bad ? "bad" : "ok"}>{msg.text}</span></div>}
      <div className="row" role="tablist" aria-label="Kind" style={{ marginBottom: 14 }}>
        {(["plate", "person"] as Kind[]).map((k) => (
          <button key={k} role="tab" type="button" aria-selected={kind === k} className={kind === k ? "inset" : ""}
            onClick={() => { setKind(k); setSelected([]); }}>{k === "plate" ? "Plates" : "Persons"}</button>
        ))}
      </div>
      <div className="row" role="tablist" aria-label="List" style={{ marginBottom: 14 }}>
        {LISTS.map((s) => (
          <button key={s} role="tab" type="button" aria-selected={list === s} className={list === s ? "inset" : ""}
            onClick={() => { setList(s); setSelected([]); }}>
            {listLabel(s)} <span className="muted">({counts[s].data?.total ?? "…"})</span></button>
        ))}
        <label style={{ marginLeft: "auto" }}><span className="sr-only">Search</span>
          <input className="inset" placeholder={kind === "plate" ? "Search plate (Persian or Latin)" : "Search name"}
            value={q} onChange={(e) => setQ(e.target.value)} /></label>
      </div>

      {canEdit && selected.length > 0 && (
        <div className="banner inset row" role="region" aria-label="Bulk move">
          <span>{selected.length} selected — move to:</span>
          {LISTS.filter((s) => s !== list).map((s) => <button key={s} type="button" onClick={() => bulk(s)}>{listLabel(s)}</button>)}
          <button type="button" onClick={() => setSelected([])}>Clear</button>
        </div>
      )}

      <section className="card raised" aria-label={`${listLabel(list)} ${kind}s`}>
        <StateView loading={page.loading} error={page.error} empty={!items.length} onRetry={page.reload}
          emptyText={`No ${kind}s on the ${listLabel(list).toLowerCase()}.`}>
          <div className="table-wrap"><table>
            <thead><tr>{canEdit && <th><span className="sr-only">Select</span></th>}
              {kind === "plate" ? <><th>Plate</th><th>Person</th><th>Effective</th><th>Last seen</th></> : <><th>Name</th><th>Plates</th><th>Notes</th></>}
              <th>List</th>{canEdit && <th><span className="sr-only">Delete</span></th>}</tr></thead>
            <tbody>
              {items.map((it) => {
                const name = kind === "plate" ? (it as PlateEntry).plate_string_latin : (it as PersonEntry).full_name;
                return (
                  <tr key={it.id}>
                    {canEdit && <td><input type="checkbox" aria-label={`Select ${name}`} checked={selected.includes(it.id)} onChange={() => toggle(it.id)} /></td>}
                    {kind === "plate" ? (() => { const p = it as PlateEntry; return <>
                      <td><span className="plate"><span className="fa inset" lang="fa" dir="rtl">{p.plate_string_fa}</span><span className="lat">{p.plate_string_latin}</span></span></td>
                      <td>{canEdit ? (
                        <select className="inset" aria-label={`Person for ${p.plate_string_latin}`} value={p.person_id ?? 0}
                          onChange={(e) => run(() => api(`/plates/${p.id}`, json({ person_id: Number(e.target.value) }, "PATCH")), "Person link updated.")}>
                          <option value={0}>—</option>
                          {persons.data?.items.map((pe) => <option key={pe.id} value={pe.id}>{pe.full_name}</option>)}
                        </select>) : (p.person_name ?? "—")}</td>
                      <td><ListBadge status={p.effective_status} /></td>
                      <td className="muted">{p.last_seen ? fmtTime(p.last_seen) : "never"}</td></>; })()
                      : (() => { const pe = it as PersonEntry; return <>
                        <td>{pe.full_name}</td><td>{pe.plates}</td><td className="muted">{pe.notes}</td></>; })()}
                    <td><ListSwitch value={it.list_status} disabled={!canEdit} label={name} onChange={(to) => move(it.id, name, to)} /></td>
                    {canEdit && <td><button type="button" aria-label={`Delete ${name}`} onClick={() => run(() => api(`${path}/${it.id}`, { method: "DELETE" }), `${name} deleted.`)}>Delete</button></td>}
                  </tr>
                );
              })}
            </tbody>
          </table></div>
        </StateView>
      </section>

      {kind === "plate" && list === "unknown" && (
        <section className="card raised" aria-labelledby="unreg-h"><h2 id="unreg-h">Seen in the last 7 days, not on any list</h2>
          <StateView loading={unreg.loading} error={unreg.error} empty={!unreg.data?.length} emptyText="Every recently seen plate is on a list." onRetry={unreg.reload}>
            <div className="table-wrap"><table><thead><tr><th>Plate</th><th>Sightings</th><th>Last seen</th><th>Put on list</th></tr></thead><tbody>
              {unreg.data?.map((u) => (
                <tr key={u.plate_key}>
                  <td><span className="plate"><span className="fa inset" lang="fa" dir="rtl">{u.plate_string_fa}</span><span className="lat">{u.plate_string_latin}</span></span></td>
                  <td>{u.sightings}</td><td className="muted">{fmtTime(u.last_seen)}</td>
                  <td>{canEdit && <ListSwitch value={"unknown"} label={u.plate_string_latin} onChange={(to) =>
                    run(() => api("/plates", json({ plate: u.plate_string_latin, list_status: to, upsert: true })), `${u.plate_string_latin} added to ${listLabel(to)}.`)} />}</td>
                </tr>
              ))}
            </tbody></table></div>
          </StateView>
        </section>
      )}

      {canEdit && (kind === "plate" ? <AddPlate list={list} persons={persons.data?.items ?? []} run={run} />
        : <AddPerson list={list} run={run} />)}
    </>
  );
}

type Run = (fn: () => Promise<unknown>, ok: string) => Promise<void>;

function AddPlate({ list, persons, run }: { list: ListStatus; persons: PersonEntry[]; run: Run }) {
  const [plate, setPlate] = useState(""); const [person, setPerson] = useState(0); const [notes, setNotes] = useState("");
  function submit(e: FormEvent) {
    e.preventDefault();
    run(() => api("/plates", json({ plate, list_status: list, person_id: person || null, notes })), `${plate} added to ${listLabel(list)}.`)
      .then(() => { setPlate(""); setNotes(""); });
  }
  return (
    <form className="card raised filters" onSubmit={submit} aria-label="Add plate">
      <label>Plate (Persian or Latin)<input className="inset" dir="auto" required value={plate} onChange={(e) => setPlate(e.target.value)} placeholder="e.g. 12B34567" /></label>
      <label>Person<select className="inset" value={person} onChange={(e) => setPerson(Number(e.target.value))}>
        <option value={0}>—</option>{persons.map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}</select></label>
      <label>Notes<input className="inset" value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
      <button type="submit">Add to {listLabel(list)}</button>
    </form>
  );
}

function AddPerson({ list, run }: { list: ListStatus; run: Run }) {
  const [name, setName] = useState(""); const [notes, setNotes] = useState("");
  function submit(e: FormEvent) {
    e.preventDefault();
    run(() => api("/persons", json({ full_name: name, notes, list_status: list })), `${name} added to ${listLabel(list)}.`)
      .then(() => { setName(""); setNotes(""); });
  }
  return (
    <form className="card raised filters" onSubmit={submit} aria-label="Add person">
      <label>Name<input className="inset" required value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label>Notes<input className="inset" value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
      <button type="submit">Add to {listLabel(list)}</button>
    </form>
  );
}
