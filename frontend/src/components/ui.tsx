import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { ApiError, EventSummary, LISTS, ListStatus, api } from "../api";
import { Key, useI18n } from "../i18n";

// Fetch state for a path; re-runs when `path` changes or reload() is called; optional polling.
export function useApi<T>(path: string | null, pollMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const seq = useRef(0);
  const load = useCallback(async () => {
    if (!path) return;
    const my = ++seq.current;
    try {
      const d = await api<T>(path);
      if (my === seq.current) { setData(d); setError(null); setUpdatedAt(Date.now()); }
    } catch (e) {
      if (my === seq.current) setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
    } finally {
      if (my === seq.current) setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    setLoading(true);
    load();
    if (!pollMs) return;
    const t = window.setInterval(load, pollMs);
    return () => window.clearInterval(t);
  }, [load, pollMs]);
  return { data, error, loading, reload: load, updatedAt };
}

// Loading / error / empty states around content. With data already on screen, a reload keeps it visible (dimmed)
// instead of flashing a loading state; the first load shows a skeleton.
export function StateView({ loading, error, empty, emptyText, onRetry, hasData = false, children }: {
  loading: boolean; error: ApiError | null; empty?: boolean; emptyText?: string; onRetry?: () => void;
  hasData?: boolean; children: ReactNode;
}) {
  const { t } = useI18n();
  if (loading && !hasData) return (
    <div className="skeleton" role="status" aria-live="polite"><span className="sr-only">{t("common.loading")}</span><span /><span /><span /></div>
  );
  if (error) return (
    <div className="state" role="alert">
      <p className="bad">{error.status === 0 ? t("common.backendDown") : t("common.error", { status: error.status, message: error.message })}</p>
      {onRetry && <button type="button" onClick={onRetry}>{t("common.retry")}</button>}
    </div>
  );
  if (empty && !loading) return <div className="state">{emptyText ?? t("common.empty")}</div>;
  return <div className={loading ? "busy" : "settled"} aria-busy={loading}>{children}</div>;
}

// Shown when data is older than `maxAgeMs` (e.g. polling failed silently).
export function StaleBanner({ updatedAt, maxAgeMs, what }: { updatedAt: number | null; maxAgeMs: number; what: string }) {
  const { t } = useI18n();
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(t); }, []);
  if (!updatedAt || now - updatedAt < maxAgeMs) return null;
  return (
    <div className="banner inset" role="status">
      <span className="dot" style={{ background: "var(--warn)" }} aria-hidden="true" />
      <span><strong className="warn">{t("common.stale")}</strong> {t("common.staleText", { what, seconds: Math.round((now - updatedAt) / 1000) })}</span>
    </div>
  );
}

// Persian plate right-to-left (isolated) next to its Latin form.
export function Plate({ e }: { e: Pick<EventSummary, "plate_string_fa" | "plate_string_latin" | "zone"> }) {
  const { t } = useI18n();
  if (!e.plate_string_fa && !e.plate_string_latin) return <span className="muted">{t("common.noRead")}</span>;
  return (
    <span className="plate">
      <span className="fa inset" lang="fa" dir="rtl">{e.plate_string_fa}</span>
      <span className="lat" dir="ltr">{e.plate_string_latin}{e.zone ? ` · ${e.zone}` : ""}</span>
    </span>
  );
}

// invalid_reason comes from the reader in English (technical detail); it stays as the tooltip in both languages.
export function Validity({ e }: { e: Pick<EventSummary, "is_valid" | "invalid_reason"> }) {
  const { t } = useI18n();
  if (e.is_valid === true) return <span className="badge inset ok">{t("valid.ok")}</span>;
  if (e.is_valid === null) return <span className="badge inset muted" title={t("valid.naTitle")}>{t("valid.na")}</span>;
  return <span className="badge inset bad" title={e.invalid_reason ?? ""}>{t("valid.bad")}</span>;
}

// Local time in the page language (Persian: fa-IR, i.e. Solar Hijri calendar and Persian digits).
export const fmtTime = (iso: string) =>
  new Date(iso).toLocaleString(document.documentElement.lang === "fa" ? "fa-IR" : undefined, { hour12: false });

const LIST_KEY: Record<ListStatus, Key> = { whitelist: "list.whitelist", blocklist: "list.blocklist", unknown: "list.unknown" };
const LIST_CLASS: Record<ListStatus, string> = { whitelist: "ok", blocklist: "bad", unknown: "muted" };
export function useListLabel() {
  const { t } = useI18n();
  return (s: ListStatus) => t(LIST_KEY[s]);
}

const TYPE_KEYS = ["standard", "disabled", "diplomatic", "transit", "freezone", "protocol", "unknown"] as const;
export function PlateType({ type }: { type: string }) {
  const { t } = useI18n();
  return <>{(TYPE_KEYS as readonly string[]).includes(type) ? t(`ptype.${type}` as Key) : type}</>;
}

export function ListBadge({ status }: { status: ListStatus | undefined }) {
  const label = useListLabel();
  const s = status ?? "unknown";
  return <span className={`badge inset ${LIST_CLASS[s]}`}>{label(s)}</span>;
}

// One-click move between lists: the current list is pressed; the others move the entry there.
export function ListSwitch({ value, onChange, disabled, label }: {
  value: ListStatus; onChange: (s: ListStatus) => void; disabled?: boolean; label: string;
}) {
  const { t } = useI18n();
  const name = useListLabel();
  return (
    <div role="group" aria-label={t("list.for", { label })} style={{ display: "flex", gap: 6, flexWrap: "nowrap" }}>
      {LISTS.map((s) => (
        <button key={s} type="button" aria-pressed={value === s} disabled={disabled}
          className={value === s ? `inset ${LIST_CLASS[s]}` : ""} onClick={() => value !== s && onChange(s)}
          style={{ padding: "4px 10px", fontSize: 13, whiteSpace: "nowrap", fontWeight: value === s ? 700 : 400 }}>
          {name(s)}</button>
      ))}
    </div>
  );
}
