// Settings -> Videos: upload video files for file sources (PUT /videos/<name>, the body is the file, so large files
// stream to the server without a multipart copy), with a progress bar; list, delete, and "Add as source", which fills
// the Add source form (type file, the stored path).
import { Clapperboard, FileVideo, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import { ApiError, api, auth } from "../api";
import { useI18n } from "../i18n";
import { ConfirmBtn } from "../pages/PersonDetail";
import { Btn, useActions } from "./Button";
import { StateView, fmtTime, useApi } from "./ui";

export type Video = { name: string; size: number; path: string; uploaded_at: string };
type Listing = { items: Video[]; free_bytes: number; max_bytes: number };
const EXT = /\.(mp4|mkv|mov|ts)$/i;

export const mb = (n: number) => (n / 1024 / 1024).toFixed(n < 10 * 1024 * 1024 ? 1 : 0);

// A file name the server accepts: letters (Latin/Persian), digits, space and ._-()+, one video extension.
export function cleanName(name: string): string {
  name = name.split(/[\\/]/).pop() ?? name;                 // never a path, only the file's own name
  const ext = (EXT.exec(name)?.[0] ?? ".mp4").toLowerCase();
  const base = name.replace(EXT, "").replace(/[^\w؀-ۿ .()+-]+/g, "_").replace(/^[^\w؀-ۿ]+/, "").slice(0, 100);
  return `${base || "video"}${ext}`;
}

function put(name: string, file: File, onProgress: (f: number) => void, signal: { xhr?: XMLHttpRequest }) {
  return new Promise<Video>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    signal.xhr = xhr;
    xhr.open("PUT", `/api/v1/videos/${encodeURIComponent(name)}`);
    if (auth.token) xhr.setRequestHeader("Authorization", `Bearer ${auth.token}`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let body: { detail?: string } & Partial<Video> = {};
      try { body = JSON.parse(xhr.responseText); } catch { /* not json */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as Video);
      else reject(new ApiError(xhr.status, body.detail ?? xhr.statusText));
    };
    xhr.onerror = () => reject(new ApiError(0, "network error"));
    xhr.onabort = () => reject(new ApiError(0, "cancelled"));
    xhr.send(file);
  });
}

export function VideoUploads({ canEdit, onUse }: { canEdit: boolean; onUse: (v: Video) => void }) {
  const { t, num } = useI18n();
  const list = useApi<Listing>("/videos");
  const actions = useActions();
  const [progress, setProgress] = useState<number | null>(null);
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null);
  const current = useRef<{ xhr?: XMLHttpRequest }>({});

  async function upload(file: File | undefined) {
    if (!file) return;
    setMsg(null);
    if (!EXT.test(file.name)) { setMsg({ text: t("vid.badType"), bad: true }); return; }
    if (list.data && file.size > list.data.max_bytes) { setMsg({ text: t("vid.tooBig", { mb: mb(list.data.max_bytes) }), bad: true }); return; }
    setProgress(0);
    current.current = {};
    try {
      const v = await put(cleanName(file.name), file, setProgress, current.current);
      setMsg({ text: t("vid.uploaded", { name: v.name }) });
      list.reload();
    } catch (e) {
      setMsg({ text: t("set.failed", { m: e instanceof ApiError ? e.message : String(e) }), bad: true });
    } finally { setProgress(null); }
  }
  return (
    <section className="card raised" aria-labelledby="vid-h">
      <div className="card-head"><h2 id="vid-h">{t("vid.title")}</h2>
        {list.data && <span className="muted small">{t("vid.free", { mb: num(mb(list.data.free_bytes)) })}</span>}</div>
      <p className="muted small" style={{ marginTop: 0 }}>{t("vid.hint")}</p>
      {canEdit && (
        <div className="row">
          <label className={`btn-x file-btn${progress !== null ? " busy" : ""}`}><Upload size={18} aria-hidden="true" /> {t("vid.choose")}
            <input type="file" accept="video/mp4,video/x-matroska,video/quicktime,video/mp2t,.mp4,.mkv,.mov,.ts" className="sr-only"
              disabled={progress !== null} onChange={(e) => { upload(e.target.files?.[0]); e.target.value = ""; }} />
          </label>
          {progress !== null && (<>
            <progress className="vid-progress" max={1} value={progress} aria-label={t("vid.uploading")} />
            <span className="small">{num(Math.round(progress * 100))}%</span>
            <Btn icon={X} iconOnly variant="ghost" className="btn-sm" label={t("people.cancel")} onClick={() => current.current.xhr?.abort()} />
          </>)}
        </div>
      )}
      {msg && <p role="status" className={msg.bad ? "bad" : "ok"}>{msg.text}</p>}
      <StateView hasData={!!list.data} loading={list.loading} error={list.error} empty={!list.data?.items.length} emptyText={t("vid.none")} onRetry={list.reload}>
        <div className="table-wrap"><table><thead><tr><th>{t("vid.file")}</th><th>{t("vid.size")}</th><th>{t("vid.when")}</th><th>{t("set.actions")}</th></tr></thead><tbody>
          {list.data?.items.map((v) => (
            <tr key={v.name}>
              <td><span className="row" style={{ gap: 6 }}><FileVideo size={16} aria-hidden="true" /><span dir="auto">{v.name}</span></span></td>
              <td>{num(mb(v.size))} MB</td><td className="muted">{fmtTime(v.uploaded_at)}</td>
              <td className="row">{canEdit && <>
                <Btn icon={Clapperboard} className="btn-sm" onClick={() => onUse(v)}>{t("vid.use")}</Btn>
                <ConfirmBtn iconOnly label={t("vid.delete")} confirm={t("person.confirm")} state={actions.state(`d-${v.name}`)}
                  onConfirm={async () => {
                    try { await actions.run(`d-${v.name}`, () => api(`/videos/${encodeURIComponent(v.name)}`, { method: "DELETE" })); list.reload(); }
                    catch (e) { setMsg({ text: t("set.failed", { m: e instanceof ApiError ? e.message : "" }), bad: true }); }
                  }} /></>}</td>
            </tr>
          ))}
        </tbody></table></div>
      </StateView>
    </section>
  );
}
