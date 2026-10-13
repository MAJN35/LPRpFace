import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api, auth } from "./api";
import { EventDetail } from "./pages/EventDetail";
import { Health } from "./pages/Health";
import { History } from "./pages/History";
import { Lists } from "./pages/Lists";
import { Live } from "./pages/Live";
import { Login } from "./pages/Login";
import { Overview } from "./pages/Overview";
import { Settings } from "./pages/Settings";

const THEME_KEY = "lpr.theme";
function applyTheme(t: string) {
  if (t === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.dataset.theme = t;
  try { localStorage.setItem(THEME_KEY, t); } catch { /* storage blocked */ }
}

export function App() {
  const [role, setRole] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  useEffect(() => {
    try { applyTheme(localStorage.getItem(THEME_KEY) ?? "auto"); } catch { /* storage blocked */ }
    const out = () => setRole(null);
    window.addEventListener("lpr:unauthorized", out);
    (auth.token ? api<{ role: string }>("/auth/me").then((u) => setRole(u.role)).catch(out) : Promise.resolve()).finally(() => setChecked(true));
    return () => window.removeEventListener("lpr:unauthorized", out);
  }, []);
  if (!checked) return <div className="state" role="status">Loading…</div>;
  if (!role) return <Login onDone={setRole} />;
  const links: [string, string][] = [["/", "Overview"], ["/live", "Live"], ["/history", "History"], ["/lists", "Lists"], ["/health", "System health"], ["/settings", "Settings"]];
  return (
    <div className="shell">
      <nav className="side raised" aria-label="Main">
        <strong style={{ padding: "6px 14px 12px" }}>LPR · Edge</strong>
        {links.map(([to, label]) => <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>{label}</NavLink>)}
        <button type="button" onClick={() => { auth.set(null); setRole(null); }} style={{ marginTop: 12 }}>Sign out</button>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/live" element={<Live />} />
          <Route path="/history" element={<History />} />
          <Route path="/lists" element={<Lists role={role} />} />
          <Route path="/events/:id" element={<EventDetail role={role} />} />
          <Route path="/health" element={<Health />} />
          <Route path="/settings" element={<Settings role={role} onTheme={applyTheme} />} />
          <Route path="*" element={<div className="state">Page not found.</div>} />
        </Routes>
      </main>
    </div>
  );
}
