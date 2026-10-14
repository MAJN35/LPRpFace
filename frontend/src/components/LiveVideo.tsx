import Hls from "hls.js";
import { useEffect, useRef, useState } from "react";
import { auth } from "../api";
import { useI18n } from "../i18n";

type State = "connecting" | "playing" | "unavailable" | "unsupported";

// Plays /hls/<path>/index.m3u8 (mediamtx LL-HLS through nginx, sent with the dashboard token). Retries every 5 s
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
    let played = false; let outage: number | undefined;
    const start = () => {
      if (stopped) return;
      if (!played) setState("connecting");          // after a gap the last frame stays on screen meanwhile
      hls = new HlsImpl({
        // The gateway may need several seconds before the first segments of a stream exist (detection stream at the
        // inference rate): generous timeouts instead of hls.js' 10 s defaults, which made browsers give up.
        lowLatencyMode: false, liveSyncDurationCount: 2, manifestLoadingTimeOut: 30000, manifestLoadingMaxRetry: 2,
        levelLoadingTimeOut: 30000, fragLoadingTimeOut: 30000,
        // Camera connections on this site are cut once a minute (network); the gateway's stream is back after a few
        // seconds. Retry playlists and segments quickly instead of failing.
        manifestLoadingRetryDelay: 1000, levelLoadingMaxRetry: 8, levelLoadingRetryDelay: 1000,
        fragLoadingMaxRetry: 8, fragLoadingRetryDelay: 1000,
        xhrSetup: (xhr) => { if (auth.token) xhr.setRequestHeader("Authorization", `Bearer ${auth.token}`); },
      });
      hls.on(HlsImpl.Events.MANIFEST_PARSED, () => { el.play().catch(() => {}); });
      hls.on(HlsImpl.Events.FRAG_BUFFERED, () => {
        played = true; window.clearTimeout(outage); outage = undefined; setState("playing");
      });
      hls.on(HlsImpl.Events.ERROR, (_e, data) => {
        if (!data.fatal) return;
        hls?.destroy(); hls = null;
        // a short gap keeps the last frame; "unavailable" only when the stream stays away for 8 s
        if (!played) setState("unavailable");
        else if (outage === undefined) outage = window.setTimeout(() => setState("unavailable"), 8000);
        timer = window.setTimeout(start, played ? 1500 : 5000);
      });
      hls.loadSource(`/hls/${encodeURIComponent(path)}/index.m3u8`);
      hls.attachMedia(el);
    };
    start();
    return () => { stopped = true; window.clearTimeout(timer); window.clearTimeout(outage); hls?.destroy(); };
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
