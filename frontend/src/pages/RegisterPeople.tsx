// Register several people by hand: one row per person (name, list, face photos), filled one by one or from many
// photos at once whose file names give the names ("Ali Rezaei.jpg", "Ali Rezaei_2.jpg" -> one person, two photos).
// Rows are sent one after another; each row shows its own result (photos without a face, an existing person the
// face already matches, with a one-click merge).
import { ArrowLeft, FolderOpen, GitMerge, ImagePlus, Plus, Trash2, UserPlus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, ListStatus, api, json } from "../api";
import { ActionState, Btn } from "../components/Button";
import { useListLabel } from "../components/ui";
import { useI18n } from "../i18n";
import { personName } from "./People";

type Similar = { id: number; full_name: string; auto_named: boolean; similarity: number };
type Result = { person: { id: number; full_name: string }; photos: { file: string; ok: boolean; error?: string }[]; similar: Similar | null };
type Row = { key: number; name: string; list: ListStatus; files: File[]; state: ActionState; result?: Result; error?: string; merged?: boolean };

const IMAGE = /\.(jpe?g|png)$/i;
let nextKey = 1;
const row = (name = "", files: File[] = [], list: ListStatus = "unknown"): Row => ({ key: nextKey++, name, list, files, state: "idle" });

// "Ali_Rezaei-2.jpg" -> "Ali Rezaei"; "علی رضایی (3).png" -> "علی رضایی"
export function nameFromFile(file: string): string {
  return file.replace(/\.[^.]+$/, "").replace(/\s*[(_-]\s*\d+\s*\)?$/, "").replace(/[_]+/g, " ").replace(/\s+/g, " ").trim();
}

export function groupByName(files: File[]): { name: string; files: File[] }[] {
  const groups = new Map<string, File[]>();
  for (const f of files.filter((x) => IMAGE.test(x.name))) {
    const n = nameFromFile(f.name);
    groups.set(n, [...(groups.get(n) ?? []), f]);
  }
  return [...groups.entries()].map(([name, fs]) => ({ name, files: fs }));
}

function Thumbs({ files }: { files: File[] }) {
  const urls = useMemo(() => files.map((f) => URL.createObjectURL(f)), [files]);
  useEffect(() => () => urls.forEach((u) => URL.revokeObjectURL(u)), [urls]);
  return <span className="row reg-thumbs">{urls.map((u, i) => <img key={u} src={u} alt={files[i].name} width={44} height={44} />)}</span>;
}

export function RegisterPeople() {
  const { t } = useI18n();
  const listLabel = useListLabel();
  const navigate = useNavigate();
  const [rows, setRows] = useState<Row[]>([row()]);
  const [running, setRunning] = useState(false);
  const set = (key: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const pending = rows.filter((r) => r.state !== "done" && r.name.trim());

  function addFiles(files: FileList | null) {
    if (!files) return;
    const groups = groupByName([...files]);
    setRows((rs) => [...rs.filter((r) => r.name.trim() || r.files.length), ...groups.map((g) => row(g.name, g.files))]);
  }
  async function submitAll() {
    setRunning(true);
    for (const r of pending) {                       // one after another: the face service embeds one photo at a time
      set(r.key, { state: "busy", error: undefined });
      const fd = new FormData();
      fd.append("full_name", r.name.trim());
      fd.append("list_status", r.list);
      r.files.forEach((f) => fd.append("photos", f, f.name));
      try {
        const res = await api<Result>("/persons/register", { method: "POST", body: fd });
        set(r.key, { state: "done", result: res });
      } catch (e) {
        const detail = e instanceof ApiError && e.status === 422 ? t("reg.noFace") : e instanceof ApiError ? e.message : String(e);
        set(r.key, { state: "error", error: detail });
      }
    }
    setRunning(false);
  }
  async function merge(r: Row) {
    if (!r.result?.similar) return;
    try {
      await api(`/persons/${r.result.similar.id}/merge`, json({ into: r.result.person.id }));
      set(r.key, { merged: true });
    } catch (e) { set(r.key, { error: e instanceof ApiError ? e.message : String(e) }); }
  }
  return (
    <>
      <div className="page-head"><Btn icon={ArrowLeft} flipRtl variant="ghost" onClick={() => navigate("/people")}>{t("person.back")}</Btn></div>
      <h1>{t("reg.title")}</h1><p className="sub">{t("reg.sub")}</p>
      <section className="card raised row reg-bar">
        <label className="btn-x file-btn"><FolderOpen size={18} aria-hidden="true" /> {t("reg.fromFiles")}
          <input type="file" accept="image/jpeg,image/png" multiple className="sr-only" onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
        </label>
        <span className="muted small">{t("reg.fromFilesHint")}</span>
        <Btn icon={Plus} onClick={() => setRows((rs) => [...rs, row()])}>{t("reg.addRow")}</Btn>
      </section>
      <section className="card raised" aria-label={t("reg.title")}>
        <div className="reg-rows">
          {rows.map((r, i) => (
            <div key={r.key} className={`reg-row inset${r.state === "done" ? " done" : r.state === "error" ? " failed" : ""}`}>
              <span className="reg-n muted">{i + 1}</span>
              <label className="grow">{t("lists.name")}
                <input className="inset" dir="auto" required value={r.name} disabled={r.state === "done" || running}
                  onChange={(e) => set(r.key, { name: e.target.value })} /></label>
              <label>{t("lists.list")}
                <select className="inset" value={r.list} disabled={r.state === "done" || running} onChange={(e) => set(r.key, { list: e.target.value as ListStatus })}>
                  {(["unknown", "whitelist", "blocklist"] as ListStatus[]).map((s) => <option key={s} value={s}>{listLabel(s)}</option>)}
                </select></label>
              <label className="btn-x file-btn btn-sm"><ImagePlus size={16} aria-hidden="true" /> {t("reg.photos", { n: r.files.length })}
                <input type="file" accept="image/jpeg,image/png" multiple className="sr-only" disabled={r.state === "done" || running}
                  onChange={(e) => { set(r.key, { files: [...r.files, ...Array.from(e.target.files ?? [])] }); e.target.value = ""; }} />
              </label>
              {r.files.length > 0 && <Thumbs files={r.files} />}
              {r.state !== "done" && <Btn icon={Trash2} iconOnly variant="ghost" className="btn-sm" label={t("reg.removeRow")} disabled={running}
                onClick={() => setRows((rs) => (rs.length > 1 ? rs.filter((x) => x.key !== r.key) : [row()]))} />}
              <div className="reg-result" role="status">
                {r.state === "busy" && <span className="muted">{t("reg.saving")}</span>}
                {r.error && <span className="bad">{r.error}</span>}
                {r.result && (<>
                  <span className="ok">{t("reg.saved", { ok: r.result.photos.filter((p) => p.ok).length, n: r.result.photos.length })}</span>
                  {r.result.photos.filter((p) => !p.ok).map((p) => <span key={p.file} className="warn small">{p.file}: {p.error}</span>)}
                  {r.result.similar && !r.merged && (
                    <span className="row small">{t("reg.similar", { name: personName(r.result.similar, t), v: Math.round(r.result.similar.similarity * 100) })}
                      <Btn icon={GitMerge} className="btn-sm" onClick={() => merge(r)}>{t("reg.merge")}</Btn></span>
                  )}
                  {r.merged && <span className="ok small">{t("person.merged")}</span>}
                  <Link className="small" to={`/people/${r.result.person.id}`}>{t("people.open")}</Link>
                </>)}
              </div>
            </div>
          ))}
        </div>
        <div className="row form-actions">
          <Btn variant="primary" icon={UserPlus} state={running ? "busy" : "idle"} disabled={!pending.length} onClick={submitAll}>
            {t("reg.submit", { n: pending.length })}</Btn>
        </div>
      </section>
    </>
  );
}
