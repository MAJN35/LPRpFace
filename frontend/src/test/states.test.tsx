import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EventSummary, LiveState } from "../api";
import { Plate, StaleBanner, StateView } from "../components/ui";
import { History } from "../pages/History";
import { Live } from "../pages/Live";
import { Login } from "../pages/Login";
import { Overview } from "../pages/Overview";
import { ApiError } from "../api";

const EV: EventSummary = {
  event_id: "11111111-1111-1111-1111-111111111111", event_type: "plate.recognized", camera_id: "cam-01",
  source_type: "rtsp", source_file: null, timestamp: "2026-10-13T08:00:00Z", track_id: 1, model_version: "v2",
  plate_type: "standard", plate_string_fa: "۱۲ ب ۳۴۵ | ۶۷", plate_string_latin: "12 Be 345 | 67", zone: null,
  expiry: null, markers: [], confidence: 0.93, is_valid: true, invalid_reason: null, frames_voted: 4, has_crop: true,
  list_status: "unknown", person_id: null,
};

function mockFetch(handler: (url: string) => { status?: number; body?: unknown } | Promise<never>) {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const r = await handler(String(url));
    return new Response(JSON.stringify(r.body ?? {}), { status: r.status ?? 200, headers: { "Content-Type": "application/json" } });
  }));
}
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("StateView", () => {
  it("shows loading, error with retry, empty and content", async () => {
    const retry = vi.fn();
    const { rerender } = render(<StateView loading error={null}>x</StateView>);
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    rerender(<StateView loading={false} error={new ApiError(0, "x")} onRetry={retry}>x</StateView>);
    expect(screen.getByRole("alert")).toHaveTextContent("Cannot reach the backend");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalled();
    rerender(<StateView loading={false} error={null} empty emptyText="Nothing here">x</StateView>);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
    rerender(<StateView loading={false} error={null}>content</StateView>);
    expect(screen.getByText("content")).toBeInTheDocument();
  });
});

describe("Plate", () => {
  it("renders Persian right-to-left next to the Latin form", () => {
    render(<Plate e={EV} />);
    const fa = screen.getByText("۱۲ ب ۳۴۵ | ۶۷");
    expect(fa).toHaveAttribute("dir", "rtl");
    expect(fa).toHaveAttribute("lang", "fa");
    expect(screen.getByText("12 Be 345 | 67")).toBeInTheDocument();
  });
  it("handles an event without a read", () => {
    render(<Plate e={{ plate_string_fa: "", plate_string_latin: "", zone: null }} />);
    expect(screen.getByText("no plate read")).toBeInTheDocument();
  });
});

describe("StaleBanner", () => {
  it("appears only when data is old", () => {
    const { rerender } = render(<StaleBanner updatedAt={Date.now()} maxAgeMs={10000} what="Status" />);
    expect(screen.queryByText(/Stale/)).toBeNull();
    rerender(<StaleBanner updatedAt={Date.now() - 60000} maxAgeMs={10000} what="Status" />);
    expect(screen.getByText(/Stale/)).toBeInTheDocument();
  });
});

describe("History", () => {
  it("shows the empty state", async () => {
    mockFetch(() => ({ body: { items: [], total: 0, limit: 25, offset: 0 } }));
    render(<MemoryRouter><History /></MemoryRouter>);
    expect(await screen.findByText("No events match these filters.")).toBeInTheDocument();
  });
  it("shows results and sends the search query", async () => {
    mockFetch(() => ({ body: { items: [EV], total: 1, limit: 25, offset: 0 } }));
    render(<MemoryRouter><History /></MemoryRouter>);
    expect(await screen.findByText("12 Be 345 | 67")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Plate"), "ب۳۴۵");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([u]) => String(u).includes("q=%D8%A8%DB%B3%DB%B4%DB%B5"))).toBe(true));
  });
  it("shows a server error", async () => {
    mockFetch(() => ({ status: 500, body: { detail: "boom" } }));
    render(<MemoryRouter><History /></MemoryRouter>);
    expect(await screen.findByRole("alert")).toHaveTextContent("Error 500: boom");
  });
});

describe("Overview", () => {
  it("shows the inference-down banner and empty recent list", async () => {
    mockFetch((u) => u.includes("/status")
      ? { body: { database: { events: 0, last_event_at: null }, inference: { reachable: false, error: "inference service unavailable" }, retention_days: 30 } }
      : u.includes("/stats") ? { body: { hours: 24, total: 0, valid: 0, valid_rate: null, by_camera: {}, by_plate_type: {}, last_event_at: null } }
        : { body: { items: [], total: 0, limit: 8, offset: 0 } });
    render(<MemoryRouter><Overview /></MemoryRouter>);
    expect(await screen.findByText(/Inference service unreachable/)).toBeInTheDocument();
    expect(await screen.findByText("No plates recorded yet.")).toBeInTheDocument();
  });
});

describe("Live", () => {
  it("shows disconnected state and live events", async () => {
    let push: (e: EventSummary) => void = () => {};
    let state: (s: LiveState) => void = () => {};
    const connect = (onEvent: (e: EventSummary) => void, onState: (s: LiveState) => void) => { push = onEvent; state = onState; return () => {}; };
    render(<MemoryRouter><Live connect={connect} /></MemoryRouter>);
    act(() => state("closed"));
    expect(screen.getByText(/Disconnected/)).toBeInTheDocument();
    act(() => { state("open"); push(EV); });
    expect(screen.queryByText(/Disconnected/)).toBeNull();
    expect(screen.getByText("۱۲ ب ۳۴۵ | ۶۷")).toBeInTheDocument();
  });
});

describe("Login", () => {
  it("reports wrong credentials", async () => {
    mockFetch(() => ({ status: 401, body: { detail: "wrong username or password" } }));
    render(<Login onDone={() => {}} />);
    await userEvent.type(screen.getByLabelText("Username"), "admin");
    await userEvent.type(screen.getByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong username or password.");
  });
});

import { ChangePassword } from "../pages/ChangePassword";
describe("ChangePassword", () => {
  it("validates locally and posts the change", async () => {
    const done = vi.fn();
    mockFetch(() => ({ body: { username: "admin", role: "admin", is_active: true, must_change_password: false } }));
    render(<ChangePassword onDone={done} />);
    await userEvent.type(screen.getByLabelText("Current password"), "initial-password");
    await userEvent.type(screen.getByLabelText("New password"), "short");
    await userEvent.type(screen.getByLabelText("Repeat new password"), "short");
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(screen.getByRole("alert")).toHaveTextContent("at least 12");
    await userEvent.clear(screen.getByLabelText("New password")); await userEvent.type(screen.getByLabelText("New password"), "a-much-longer-password");
    await userEvent.clear(screen.getByLabelText("Repeat new password")); await userEvent.type(screen.getByLabelText("Repeat new password"), "a-much-longer-password");
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    await waitFor(() => expect(done).toHaveBeenCalled());
    expect(vi.mocked(fetch).mock.calls.some(([u]) => String(u).endsWith("/auth/change-password"))).toBe(true);
  });
});
