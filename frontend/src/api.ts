// Backend API client: bearer token from login (sessionStorage), JSON helpers, live WebSocket with backoff.
export type EventSummary = {
  event_id: string; event_type: string; camera_id: string; source_type: string; source_file: string | null;
  timestamp: string; track_id: number | null; model_version: string; plate_type: string;
  plate_string_fa: string; plate_string_latin: string; zone: string | null; expiry: string | null;
  markers: string[]; confidence: number; is_valid: boolean | null; invalid_reason: string | null;
  frames_voted: number; has_crop: boolean; list_status: ListStatus; person_id: number | null;
};
export type ListStatus = "whitelist" | "blocklist" | "unknown";
export const LISTS: ListStatus[] = ["whitelist", "blocklist", "unknown"];
export type PlateEntry = { id: number; plate_key: string; plate_string_fa: string; plate_string_latin: string;
  list_status: ListStatus; effective_status: ListStatus; person_id: number | null; person_name: string | null;
  notes: string; last_seen: string | null };
export type PersonEntry = { id: number; full_name: string; notes: string; list_status: ListStatus; plates: number;
  auto_named?: boolean; faces?: number; last_seen?: string | null; cover_face?: string | null };
// Face recognition: one face track with its snapshot and the person it was matched to (or none).
export type FaceSummary = { id: string; timestamp: string; camera_id: string; track_id: number | null;
  person_id: number | null; person_name: string | null; person_auto: boolean; similarity: number | null;
  match: "matched" | "new_person" | "manual" | "none"; det_score: number; list_status: ListStatus;
  has_snapshot: boolean; has_embedding: boolean };
export type Snapshot = { kind: "plate" | "face"; id: string; timestamp: string; camera_id: string; list_status: ListStatus;
  person_id: number | null; person_name: string | null; person_auto?: boolean; plate_type?: string;
  plate_string_fa?: string; plate_string_latin?: string; zone?: string | null; is_valid?: boolean | null };
export type ListPage<T> = { items: T[]; total: number; limit: number; offset: number };
export type Unregistered = { plate_key: string; plate_string_fa: string; plate_string_latin: string; sightings: number; last_seen: string };
export type EventDetail = EventSummary & {
  characters: { class_id: number; name: string; confidence: number; margin?: number; box: number[] }[];
  plate_bbox: number[]; frame_size: number[]; model_sha256: string; engine_sha256: string | null;
  precision: string; processed_at: string | null; plate_key: string;
  person: { id: number; full_name: string; list_status: ListStatus } | null;
};
export type Page = { items: EventSummary[]; total: number; limit: number; offset: number };
export type Stats = { hours: number; total: number; valid: number; valid_rate: number | null;
  by_camera: Record<string, number>; by_plate_type: Record<string, number>; last_event_at: string | null };
export type SourceHealth = { status: string; fps_in?: number; fps_out?: number; last_frame_age_s?: number | null;
  last_error?: string | null; reconnects?: number; frames_in?: number };
export type Status = {
  database: { events: number; last_event_at: string | null };
  inference: { reachable: boolean; error?: string; model?: { version: string; precision: string; batch_profile: number[] };
    engine?: string; max_cameras?: number | null; pipeline?: Record<string, number>; worker?: Record<string, unknown>;
    capacity?: { max_cameras_memory_safe: number; max_cameras_at_target_fps: number; target_fps_per_camera: number };
    sources?: Record<string, SourceHealth> };
  retention_days: number;
};
export type Camera = { id: string; name: string; type: string; uri: string; enabled: boolean; max_fps: number; copy_of?: string | null;
  roi: number[][] | null; min_plate_px: number; face_blur: boolean; record: boolean };

const TOKEN_KEY = "lpr.token";
export const auth = {
  get token(): string | null { try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set(token: string | null) { try { token ? sessionStorage.setItem(TOKEN_KEY, token) : sessionStorage.removeItem(TOKEN_KEY); } catch { /* storage blocked */ } },
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (auth.token) headers.set("Authorization", `Bearer ${auth.token}`);
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Backend unreachable");
  }
  if (res.status === 401) { auth.set(null); window.dispatchEvent(new Event("lpr:unauthorized")); }
  if (!res.ok) {
    let detail = res.statusText;
    try { const b = await res.json(); detail = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail); } catch { /* not json */ }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export type Session = { role: string; mustChange: boolean };
export async function login(username: string, password: string): Promise<Session> {
  const body = new URLSearchParams({ username, password });
  const r = await api<{ access_token: string; role: string; must_change_password: boolean }>("/auth/login", { method: "POST", body });
  auth.set(r.access_token);
  return { role: r.role, mustChange: r.must_change_password };
}

export const cropUrl = (id: string) => `/api/v1/events/${id}/crop?token=${encodeURIComponent(auth.token ?? "")}`;
export const faceUrl = (id: string) => `/api/v1/faces/${id}/snapshot?token=${encodeURIComponent(auth.token ?? "")}`;

export function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export type LiveState = "connecting" | "open" | "closed";
// Live events with reconnect backoff (1 s doubling to 30 s). Returns a stop function.
export function connectLive(onEvent: (e: EventSummary) => void, onState: (s: LiveState) => void,
  onAlert?: (e: EventSummary) => void, onFace?: (f: FaceSummary, alert: boolean) => void): () => void {
  let ws: WebSocket | null = null; let delay = 1000; let stopped = false; let timer: number | undefined;
  const open = () => {
    if (stopped) return;
    onState("connecting");
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/api/v1/ws/events?token=${encodeURIComponent(auth.token ?? "")}`);
    ws.onopen = () => { delay = 1000; onState("open"); };
    ws.onmessage = (m) => { try { const d = JSON.parse(m.data); if (d.type === "event") onEvent(d.event); if (d.type === "alert") onAlert?.(d.event);
      if (d.type === "face") onFace?.(d.face, false); if (d.type === "face_alert") onFace?.(d.face, true); } catch { /* ignore */ } };
    ws.onclose = () => { onState("closed"); if (!stopped) { timer = window.setTimeout(open, delay); delay = Math.min(delay * 2, 30000); } };
  };
  open();
  return () => { stopped = true; window.clearTimeout(timer); ws?.close(); };
}

export const json = (body: unknown, method = "POST"): RequestInit =>
  ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
