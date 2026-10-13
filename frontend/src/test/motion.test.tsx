import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { EventSummary, LiveState } from "../api";
import { StateView } from "../components/ui";
import { Live } from "../pages/Live";

describe("StateView without flicker", () => {
  it("shows a skeleton on the first load", () => {
    const { container } = render(<StateView loading error={null}>content</StateView>);
    expect(container.querySelector(".skeleton")).not.toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    expect(screen.queryByText("content")).toBeNull();
  });
  it("keeps data visible and dimmed while reloading", () => {
    const { rerender } = render(<StateView loading={false} error={null} hasData>table</StateView>);
    expect(screen.getByText("table")).not.toHaveAttribute("aria-busy", "true");
    rerender(<StateView loading error={null} hasData>table</StateView>);
    const box = screen.getByText("table");
    expect(box).toHaveAttribute("aria-busy", "true");
    expect(box).toHaveClass("busy");
  });
});

describe("Live arrivals", () => {
  it("marks rows that arrive live for the highlight", () => {
    let push: (e: EventSummary) => void = () => {};
    let state: (s: LiveState) => void = () => {};
    const connect = (onEvent: (e: EventSummary) => void, onState: (s: LiveState) => void) => { push = onEvent; state = onState; return () => {}; };
    render(<MemoryRouter><Live connect={connect} /></MemoryRouter>);
    act(() => { state("open"); push({ event_id: "e1", event_type: "plate.recognized", camera_id: "cam", source_type: "rtsp",
      source_file: null, timestamp: "2026-10-13T08:00:00Z", track_id: 1, model_version: "v2", plate_type: "standard",
      plate_string_fa: "۱۲ ب ۳۴۵ | ۶۷", plate_string_latin: "12 Be 345 | 67", zone: null, expiry: null, markers: [],
      confidence: 0.9, is_valid: true, invalid_reason: null, frames_voted: 3, has_crop: false, list_status: "unknown", person_id: null }); });
    expect(screen.getByText("12 Be 345 | 67").closest("tr")).toHaveClass("arrived");
  });
});
