import { Activity, Cctv, Images, UsersRound, Gauge, ListChecks, LogOut, LucideIcon, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen,
  ScanSearch, Settings as SettingsIcon } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { api, auth } from "./api";
import { Btn } from "./components/Button";
import { LiquidIndicator } from "./components/LiquidIndicator";
import { Logo } from "./components/Logo";
import { Notifications, readNotify, storeNotify } from "./components/Notifications";
import { SysState, setSys, sysState } from "./components/systemNotify";
import { Key, useI18n } from "./i18n";
import { EventDetail } from "./pages/EventDetail";
import { Health } from "./pages/Health";
import { History } from "./pages/History";
import { Library } from "./pages/Library";
import { Lists } from "./pages/Lists";
import { People } from "./pages/People";
import { PersonDetail } from "./pages/PersonDetail";
import { RegisterPeople } from "./pages/RegisterPeople";
import { Live } from "./pages/Live";
import { Login } from "./pages/Login";
import { ChangePassword } from "./pages/ChangePassword";
import { Overview } from "./pages/Overview";
import { Settings } from "./pages/Settings";

const THEME_KEY = "lpr.theme";
const NAV_KEY = "lpr.nav";                       // "collapsed" | "expanded", per browser like the theme
const LINKS: [string, Key, LucideIcon][] = [
  ["/", "nav.overview", Gauge], ["/live", "nav.live", Cctv], ["/history", "nav.history", ScanSearch],
  ["/people", "nav.people", UsersRound], ["/lists", "nav.lists", ListChecks], ["/library", "nav.library", Images],
  ["/health", "nav.health", Activity], ["/settings", "nav.settings", SettingsIcon],
];
function applyTheme(t: string) {
  if (t === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.dataset.theme = t;
  try { localStorage.setItem(THEME_KEY, t); } catch { /* storage blocked */ }
}

// Re-mounts on navigation so each page fades in (CSS .page; off under reduced motion).
function PageFade({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation();
  return <div className="page" key={pathname}>{children}</div>;
}

function readNav() { try { return localStorage.getItem(NAV_KEY) === "collapsed"; } catch { return false; } }

export function App() {
  const { t, lang } = useI18n();
  const { pathname } = useLocation();               // drives the liquid menu indicator (also back/forward, direct URLs)
  const menu = useRef<HTMLDivElement>(null);
  const [collapsed, setCollapsed] = useState(readNav);
  const [notify, setNotify] = useState(readNotify);
  const [sys, setSysState] = useState<SysState>(sysState);
  const toggleNav = () => setCollapsed((c) => {
    try { localStorage.setItem(NAV_KEY, c ? "expanded" : "collapsed"); } catch { /* storage blocked */ }
    return !c;
  });
  const [role, setRole] = useState<string | null>(null);
  const [mustChange, setMustChange] = useState(false);
  const [checked, setChecked] = useState(false);
  useEffect(() => {
    try { applyTheme(localStorage.getItem(THEME_KEY) ?? "auto"); } catch { /* storage blocked */ }
    const out = () => setRole(null);
    window.addEventListener("lpr:unauthorized", out);
    (auth.token ? api<{ role: string; must_change_password: boolean }>("/auth/me")
      .then((u) => { setRole(u.role); setMustChange(u.must_change_password); }).catch(out) : Promise.resolve())
      .finally(() => setChecked(true));
    return () => window.removeEventListener("lpr:unauthorized", out);
  }, []);
  if (!checked) return <div className="state" role="status">{t("common.loading")}</div>;
  if (!role) return <Login onDone={(s) => { setRole(s.role); setMustChange(s.mustChange); }} />;
  if (mustChange) return <ChangePassword onDone={() => setMustChange(false)} />;
  // The sidebar sits at the inline start (right in Persian): the collapse icon follows that side.
  const rtl = lang === "fa";
  const CollapseIcon = collapsed ? (rtl ? PanelRightOpen : PanelLeftOpen) : (rtl ? PanelRightClose : PanelLeftClose);
  return (
    <div className={`shell${collapsed ? " nav-collapsed" : ""}`}>
      <nav className={`side raised${collapsed ? " collapsed" : ""}`} aria-label={t("nav.main")}>
        <div className="side-head">
          <Logo compact={collapsed} />
          <Btn icon={CollapseIcon} iconOnly variant="ghost" className="nav-toggle" label={t(collapsed ? "nav.expand" : "nav.collapse")}
            aria-expanded={!collapsed} onClick={toggleNav} />
        </div>
        <div className="nav-links liquid-host" ref={menu}>
          {LINKS.map(([to, label, Icon]) => (
            <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => `nav-item has-tip${isActive ? " active" : ""}`}
              data-tip={t(label)}>
              <Icon className="nav-icon" size={20} strokeWidth={2} aria-hidden="true" />
              <span className="nav-label">{t(label)}</span>
            </NavLink>
          ))}
          <LiquidIndicator group={menu} selector="a.active" activeKey={`${pathname}|${collapsed}|${lang}`} className="bar" />
        </div>
        <div className="side-foot">
          <Btn icon={LogOut} flipRtl className="nav-out" iconOnly={collapsed} label={t("nav.signout")}
            onClick={() => { auth.set(null); setRole(null); }}>{t("nav.signout")}</Btn>
        </div>
      </nav>
      <Notifications enabled={notify} />
      <main>
        <PageFade>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/live" element={<Live />} />
          <Route path="/history" element={<History />} />
          <Route path="/lists" element={<Lists role={role} />} />
          <Route path="/people" element={<People role={role} />} />
          <Route path="/people/register" element={<RegisterPeople />} />
          <Route path="/people/:id" element={<PersonDetail role={role} />} />
          <Route path="/library" element={<Library role={role} />} />
          <Route path="/events/:id" element={<EventDetail role={role} />} />
          <Route path="/health" element={<Health />} />
          <Route path="/settings" element={<Settings role={role} onTheme={applyTheme} notify={notify}
            onNotify={(on) => { storeNotify(on); setNotify(on); }} sys={sys} onSys={async (on) => setSysState(await setSys(on))} />} />
          <Route path="*" element={<div className="state">{t("common.notFound")}</div>} />
        </Routes>
        </PageFade>
      </main>
    </div>
  );
}
