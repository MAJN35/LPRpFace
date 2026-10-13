// Snapshot library: every stored plate crop and face snapshot, newest first, with filters, multi-select and delete.
// Deleting removes the image only; the plate event / face record stays (without an image).
import { CheckSquare, ChevronLeft, ChevronRight, Eye, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, ListPage, Snapshot, api, cropUrl, faceUrl, query } from "../api";
import { Btn, useActions } from "../components/Button";
import { ListBadge, Plate, StateView, fmtTime, useApi } from "../components/ui";
import { useI18n } from "../i18n";
import { ConfirmBtn } from "./PersonDetail";
import { personName } from "./People";

const LIMIT = 48;
type Kind = "all" | "plate" | "face";

export function Library({ role }: { role: string }) {
  const { t } = useI18n();
  const canEdit = role === "admin" || role === "operator";
  const [kind, setKind] = useState<Kind>("all");
  const [camera, setCamera] = useState("");
  const [offset, setOffset] = useState(0);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const page = useApi<ListPage<Snapshot>>(`/snapshots${query({ kind, camera_id: camera, limit: LIMIT, offset })}`);
  const actions = useActions();
  const items = page.data?.items ?? [];
  const total = page.data?.total ?? 0;
  const key = (s: Snapshot) => `${s.kind}:${s.id}`;
  const toggle = (k: string) => setSel((x) => { const n = new Set(x); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const label = (s: Snapshot) => s.kind === "face"
    ? (s.person_id ? personName({ id: s.person_id, full_name: s.person_name ?? "", auto_named: s.person_auto }, t) : t("notify.face"))
    : s.plate_string_latin ?? "";

  async function remove(keys: string[], actionKey: string) {
    setMsg(null);
    const items = keys.map((k) => { const [kind, ...id] = k.split(":"); return { kind, id: id.join(":") }; });
    try {
      const r = await actions.run(actionKey, () => api<{ deleted: number }>("/snapshots", {
        method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items }) }));
      if (r) { setMsg({ text: t("lib.deleted", { n: r.deleted }) }); setSel(new Set()); page.reload(); }
    } catch (x) { setMsg({ text: t("set.failed", { m: x instanceof ApiError ? x.message : "" }), bad: true }); }
  }
  return (
    <>
      <h1>{t("lib.title")}</h1><p className="sub">{t("lib.sub")}</p>
      <div className="card raised row lib-bar">
        <div role="radiogroup" aria-label={t("lib.kind")} className="row seg">
          {([["all", "lib.all"], ["plate", "lib.plates"], ["face", "lib.faces"]] as const).map(([v, k]) => (
            <Btn key={v} role="radio" aria-checked={kind === v} className={kind === v ? "inset" : ""}
              onClick={() => { setKind(v); setOffset(0); setSel(new Set()); }}>{t(k)}</Btn>
          ))}
        </div>
        <label>{t("hist.camera")}<input className="inset" dir="ltr" value={camera} onChange={(e) => { setCamera(e.target.value); setOffset(0); }} /></label>
        <Btn icon={RefreshCw} iconOnly variant="ghost" spin={page.loading} label={t("common.refresh")} onClick={page.reload} />
        <span className="muted" aria-live="polite">{page.data ? t("lib.count", { n: total }) : ""}</span>
        {canEdit && (
          <span className="row lib-actions">
            <Btn icon={CheckSquare} className="btn-sm" onClick={() => setSel(new Set(items.map(key)))} disabled={!items.length}>{t("lib.selectPage")}</Btn>
            {sel.size > 0 && <span>{t("lib.selected", { n: sel.size })}</span>}
            {sel.size > 0 && <ConfirmBtn label={t("lib.deleteSel")} confirm={t("lib.confirmN", { n: sel.size })} state={actions.state("bulk")}
              onConfirm={() => remove([...sel], "bulk")} />}
          </span>
        )}
      </div>
      {msg && <div className="banner inset" role="status"><span className={msg.bad ? "bad" : "ok"}>{msg.text}</span></div>}
      <StateView hasData={!!page.data} loading={page.loading} error={page.error} empty={!items.length} emptyText={t("lib.empty")} onRetry={page.reload}>
        <div className="lib-grid">
          {items.map((s) => {
            const k = key(s);
            const href = s.kind === "plate" ? `/events/${s.id}` : s.person_id ? `/people/${s.person_id}` : null;
            return (
              <figure key={k} className={`lib-tile raised${sel.has(k) ? " selected" : ""}`}>
                {canEdit && <label className="lib-check"><span className="sr-only">{t("lib.select", { name: label(s) })}</span>
                  <input type="checkbox" checked={sel.has(k)} onChange={() => toggle(k)} /></label>}
                <img src={s.kind === "plate" ? cropUrl(s.id) : faceUrl(s.id)} alt={label(s)} loading="lazy"
                  className={s.kind === "face" ? "lib-face" : "lib-plate"}
                  onError={(e) => { e.currentTarget.classList.add("missing"); e.currentTarget.alt = ""; }} />
                <figcaption>
                  {s.kind === "plate" ? <Plate e={{ plate_string_fa: s.plate_string_fa ?? "", plate_string_latin: s.plate_string_latin ?? "",
                    zone: s.zone ?? null, plate_type: s.plate_type, is_valid: s.is_valid }} /> : <strong>{label(s)}</strong>}
                  <span className="muted small">{s.camera_id} · {fmtTime(s.timestamp)}</span>
                  <span className="row lib-tile-actions">
                    <ListBadge status={s.list_status} />
                    {href && <Link className="icon-link" to={href}><Eye size={16} aria-hidden="true" />{t("lib.open")}</Link>}
                    {canEdit && <ConfirmBtn iconOnly label={t("lib.delete")} confirm={t("person.confirm")} state={actions.state(`d-${k}`)}
                      onConfirm={() => remove([k], `d-${k}`)} />}
                  </span>
                </figcaption>
              </figure>
            );
          })}
        </div>
        <nav className="row" aria-label={t("hist.pages")} style={{ marginTop: 12 }}>
          <Btn icon={ChevronLeft} flipRtl disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>{t("hist.prev")}</Btn>
          <span className="muted">{t("hist.range", { from: offset + 1, to: Math.min(offset + LIMIT, total), total })}</span>
          <Btn icon={ChevronRight} flipRtl className="icon-end" disabled={offset + LIMIT >= total} onClick={() => setOffset(offset + LIMIT)}>{t("hist.next")}</Btn>
        </nav>
      </StateView>
    </>
  );
}
