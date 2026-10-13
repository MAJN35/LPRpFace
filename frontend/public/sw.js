// Service worker for OS notifications of the open dashboard (no push service: nothing leaves the device).
// Clicking a notification focuses a dashboard window on the event or person, or opens one.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
    for (const w of wins) {
      if ("focus" in w) return (w.navigate ? w.navigate(url) : Promise.resolve()).then(() => w.focus());
    }
    return self.clients.openWindow(url);
  }));
});
