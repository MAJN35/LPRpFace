import Hls from "hls.js";
import { useEffect, useRef, useState } from "react";
import { auth } from "../api";
import { useI18n } from "../i18n";

type State = "connecting" | "playing" | "unavailable" | "unsupported";

// Plays /live/<path>/index.m3u8 (mediamtx LL-HLS through nginx, sent with the dashboard token). Retries every 5 s
// while the stream is not there yet (camera offline, pipeline starting, no viewer-triggered pull yet).
export function LiveVideo({ path, label, HlsImpl = Hls }: { path: string; label: string; HlsImpl?: typeof Hls }) {
  const { t } = useI18n();
  const video = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<State>("connecting");
  useEffect(() => {
    const el = video.current;
    if (!el) return;
    if (!HlsImpl.isSupported()) { setState("unsupported"); return; }
    let hls: Hls | null = null; let timer: number | undefined; let stopped = false;
    const start = () => {
      if (stopped) return;
      setState("connecting");
      hls = new HlsImpl({
        lowLatencyMode: true, liveSyncDurationCount: 2, manifestLoadingMaxRetry: 0,
        xhrSetup: (xhr) => { if (auth.token) xhr.setRequestHeader("Authorization", `Bearer ${auth.token}`); },
      });
      hls.on(HlsImpl.Events.MANIFEST_PARSED, () => { el.play().catch(() => {}); });
      hls.on(HlsImpl.Events.FRAG_BUFFERED, () => setState("playing"));
      hls.on(HlsImpl.Events.ERROR, (_e, data) => {
        if (!data.fatal) return;
        hls?.destroy(); hls = null;
        setState("unavailable");
        timer = window.setTimeout(start, 5000);
      });
      hls.loadSource(`/live/${encodeURIComponent(path)}/index.m3u8`);
      hls.attachMedia(el);
    };
    start();
    return () => { stopped = true; window.clearTimeout(timer); hls?.destroy(); };
  }, [path, HlsImpl]);
  return (
    <div className="video-box inset">
      <video ref={video} muted playsInline autoPlay aria-label={label} data-state={state} />
      {state !== "playing" && (
        <div className="video-state" role="status">
          {state === "connecting" && <span><span className="dot pulse" aria-hidden="true" style={{ background: "var(--warn)" }} /> {t("video.connecting")}</span>}
          {state === "unavailable" && <span>{t("video.unavailable")}</span>}
          {state === "unsupported" && <span>{t("video.unsupported")}</span>}
        </div>
      )}
    </div>
  );
}
