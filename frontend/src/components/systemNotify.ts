// OS notifications from the open dashboard (Notification API through the service worker, so Android Chrome works
// too). Needs a secure context: the dashboard over https (port 8443, tools/make_cert.sh). Stored per browser in
// localStorage "lpr.sysnotify".
const KEY = "lpr.sysnotify";

export type SysState = "unsupported" | "insecure" | "denied" | "off" | "on";

export function sysState(): SysState {
  if (typeof window === "undefined" || !("Notification" in window)) return "unsupported";
  if (!window.isSecureContext) return "insecure";
  if (Notification.permission === "denied") return "denied";
  let on = false;
  try { on = localStorage.getItem(KEY) === "on"; } catch { /* storage blocked */ }
  return on && Notification.permission === "granted" ? "on" : "off";
}

export async function setSys(on: boolean): Promise<SysState> {
  try { localStorage.setItem(KEY, on ? "on" : "off"); } catch { /* storage blocked */ }
  if (on && "Notification" in window && Notification.permission === "default") await Notification.requestPermission();
  return sysState();
}

export function registerWorker() {
  if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("/sw.js").catch(() => undefined);
}

// Shown when the dashboard is not in front (the in-page notification covers the visible case); alerts always.
export async function showSystem(title: string, body: string, url: string, opts: { image?: string; alert?: boolean; tag: string }) {
  if (sysState() !== "on") return;
  if (!opts.alert && document.visibilityState === "visible" && document.hasFocus()) return;
  const n: NotificationOptions & { image?: string; renotify?: boolean } = {
    body, tag: opts.tag, icon: opts.image ?? "/icon-192.png", badge: "/favicon-32.png", data: { url },
    requireInteraction: !!opts.alert, lang: document.documentElement.lang, dir: document.documentElement.dir === "rtl" ? "rtl" : "ltr",
  };
  if (opts.image) n.image = opts.image;
  try {
    const reg = "serviceWorker" in navigator ? await navigator.serviceWorker.getRegistration() : undefined;
    if (reg) await reg.showNotification(title, n);
    else new Notification(title, n);
  } catch { /* the browser refused: nothing else to do */ }
}
