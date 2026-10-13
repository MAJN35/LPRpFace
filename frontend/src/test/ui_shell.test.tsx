// Shared button (busy / success only after the operation / icon-only names), notifications per detection, and the
// multi-camera live grid (raw for all, detections on one camera at a time).
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Check } from "lucide-react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Camera, EventSummary, LiveState } from "../api";
import { Btn, useActions } from "../components/Button";
import { Notifications } from "../components/Notifications";
import { Live } from "../pages/Live";
import { render } from "./render";

const EV: EventSummary = {
  event_id: "22222222-2222-2222-2222-222222222222", event_type: "plate.recognized", camera_id: "gate",
  source_type: "rtsp", source_file: null, timestamp: "2026-10-13T08:00:00Z", track_id: 4, model_version: "v2",
  plate_type: "standard", plate_string_fa: "۱۲ ب ۳۴۵ | ۶۷", plate_string_latin: "12 Be 345 | 67", zone: null,
  expiry: null, markers: [], confidence: 0.93, is_valid: true, invalid_reason: null, frames_voted: 4, has_crop: false,
  list_status: "unknown", person_id: null,
};
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

function Saver({ fn }: { fn: () => Promise<unknown> }) {
  const a = useActions();
  return <Btn icon={Check} state={a.state("s")} onClick={() => a.run("s", fn).catch(() => undefined)}>Save</Btn>;
}

describe("Btn", () => {
  it("is busy while running, shows success only after it resolved, and blocks double submits", async () => {
    let resolve!: () => void;
    const fn = vi.fn(() => new Promise<void>((r) => { resolve = r; }));
    render(<Saver fn={fn} />);
    const b = screen.getByRole("button", { name: "Save" });
    await userEvent.click(b);
    expect(b).toBeDisabled();
    expect(b).toHaveAttribute("aria-busy", "true");
    expect(b).toHaveAttribute("data-state", "busy");
    await userEvent.click(b);
    expect(fn).toHaveBeenCalledTimes(1);
    await act(async () => { resolve(); });
    expect(b).toHaveAttribute("data-state", "done");
    expect(b).not.toBeDisabled();
  });
  it("shows the error state when the operation fails", async () => {
    render(<Saver fn={() => Promise.reject(new Error("x"))} />);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toHaveAttribute("data-state", "error"));
  });
  it("gives icon-only buttons an accessible name and a tooltip", () => {
    render(<Btn icon={Check} iconOnly label="Refresh" />);
    const b = screen.getByRole("button", { name: "Refresh" });
    expect(b).toHaveAttribute("data-tip", "Refresh");
    expect(b.textContent).toBe("");
  });
});

describe("Notifications", () => {
  function setup(enabled = true) {
    let onEvent!: (e: EventSummary) => void; let onAlert!: (e: EventSummary) => void;
    const connect = (ev: (e: EventSummary) => void, _s: (s: LiveState) => void, al?: (e: EventSummary) => void) => {
      onEvent = ev; onAlert = al!; return () => undefined;
    };
    render(<MemoryRouter><Notifications enabled={enabled} connect={connect} /></MemoryRouter>);
    return { event: (e: EventSummary) => act(() => onEvent(e)), alert: (e: EventSummary) => act(() => onAlert(e)) };
  }
  it("shows a notification for each detection and closes it after a few seconds", async () => {
    vi.useFakeTimers();
    const live = setup();
    live.event(EV);
    live.event({ ...EV, event_id: "33333333-3333-3333-3333-333333333333", camera_id: "door" });
    expect(screen.getAllByRole("status")).toHaveLength(2);
    expect(screen.getAllByRole("status")[0]).toHaveTextContent("door");
    act(() => { vi.advanceTimersByTime(6500); });
    expect(screen.queryAllByRole("status")).toHaveLength(0);
  });
  it("keeps blocklist alerts until dismissed, even when plate notifications are muted", async () => {
    vi.useFakeTimers();
    const live = setup(false);
    live.event(EV);
    expect(screen.queryAllByRole("status")).toHaveLength(0);
    live.alert({ ...EV, list_status: "blocklist" });
    act(() => { vi.advanceTimersByTime(60000); });
    const a = screen.getByRole("alert");
    expect(a).toHaveTextContent("Blocklisted plate");
    vi.useRealTimers();
    await userEvent.click(within(a).getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("Live grid", () => {
  it("plays every camera at once with detections on one of them", async () => {
    const cams: Camera[] = ["gate", "door"].map((id) => ({ id, name: id, type: "rtsp", uri: `rtsp://h/${id}`, enabled: true,
      max_fps: 10, roi: null, min_plate_px: 0, face_blur: true, record: false }));
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(cams), { status: 200, headers: { "Content-Type": "application/json" } })));
    render(<MemoryRouter><Live connect={() => () => undefined} /></MemoryRouter>);
    const gate = await screen.findByRole("group", { name: "View of gate" });
    const door = screen.getByRole("group", { name: "View of door" });
    expect(within(gate).getByRole("button", { name: "Detections" })).toHaveAttribute("aria-pressed", "true");
    expect(within(door).getByRole("button", { name: "Raw" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(within(door).getByRole("button", { name: "Detections" }));
    expect(within(door).getByRole("button", { name: "Detections" })).toHaveAttribute("aria-pressed", "true");
    expect(within(gate).getByRole("button", { name: "Raw" })).toHaveAttribute("aria-pressed", "true");
    expect(document.querySelectorAll("video")).toHaveLength(2);
  });
});
