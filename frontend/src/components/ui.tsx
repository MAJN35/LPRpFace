import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { ApiError, EventSummary, LISTS, ListStatus, api } from "../api";

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

// Loading / error / empty states around content.
export function StateView({ loading, error, empty, emptyText = "Nothing to show yet.", onRetry, children }: {
  loading: boolean; error: ApiError | null; empty?: boolean; emptyText?: string; onRetry?: () => void; children: ReactNode;
}) {
  if (loading) return <div className="state" role="status" aria-live="polite">Loading…</div>;
  if (error) return (
    <div className="state" role="alert">
      <p className="bad">{error.status === 0 ? "Cannot reach the backend." : `Error ${error.status}: ${error.message}`}</p>
      {onRetry && <button type="button" onClick={onRetry}>Retry</button>}
    </div>
  );
  if (empty) return <div className="state">{emptyText}</div>;
  return <>{children}</>;
}

// Shown when data is older than `maxAgeMs` (e.g. polling failed silently).
export function StaleBanner({ updatedAt, maxAgeMs, what }: { updatedAt: number | null; maxAgeMs: number; what: string }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(t); }, []);
  if (!updatedAt || now - updatedAt < maxAgeMs) return null;
  return (
    <div className="banner inset" role="status">
      <span className="dot" style={{ background: "var(--warn)" }} aria-hidden="true" />
      <span><strong className="warn">Stale:</strong> {what} last updated {Math.round((now - updatedAt) / 1000)} s ago.</span>
    </div>
  );
}

// Persian plate right-to-left (isolated) next to its Latin form.
export function Plate({ e }: { e: Pick<EventSummary, "plate_string_fa" | "plate_string_latin" | "zone"> }) {
  if (!e.plate_string_fa && !e.plate_string_latin) return <span className="muted">no plate read</span>;
  return (
    <span className="plate">
      <span className="fa inset" lang="fa" dir="rtl">{e.plate_string_fa}</span>
      <span className="lat">{e.plate_string_latin}{e.zone ? ` · ${e.zone}` : ""}</span>
    </span>
  );
}

export function Validity({ e }: { e: Pick<EventSummary, "is_valid" | "invalid_reason"> }) {
  if (e.is_valid === true) return <span className="badge inset ok">valid</span>;
  if (e.is_valid === null) return <span className="badge inset muted" title="No validated format rule">not applicable</span>;
  return <span className="badge inset bad" title={e.invalid_reason ?? ""}>{e.invalid_reason ?? "invalid"}</span>;
}

export const fmtTime = (iso: string) => new Date(iso).toLocaleString(undefined, { hour12: false });

const LIST_LABEL: Record<ListStatus, string> = { whitelist: "Whitelist", blocklist: "Blocklist", unknown: "Unknown" };
const LIST_CLASS: Record<ListStatus, string> = { whitelist: "ok", blocklist: "bad", unknown: "muted" };
export const listLabel = (s: ListStatus) => LIST_LABEL[s];

export function ListBadge({ status }: { status: ListStatus | undefined }) {
  const s = status ?? "unknown";
  return <span className={`badge inset ${LIST_CLASS[s]}`}>{LIST_LABEL[s]}</span>;
}

// One-click move between lists: the current list is pressed; the others move the entry there.
export function ListSwitch({ value, onChange, disabled, label }: {
  value: ListStatus; onChange: (s: ListStatus) => void; disabled?: boolean; label: string;
}) {
  return (
    <div className="row" role="group" aria-label={`List for ${label}`} style={{ gap: 6 }}>
      {LISTS.map((s) => (
        <button key={s} type="button" aria-pressed={value === s} disabled={disabled || value === s}
          className={value === s ? `inset ${LIST_CLASS[s]}` : ""} onClick={() => onChange(s)}
          style={{ padding: "4px 10px", fontSize: 13 }}>{LIST_LABEL[s]}</button>
      ))}
    </div>
  );
}
