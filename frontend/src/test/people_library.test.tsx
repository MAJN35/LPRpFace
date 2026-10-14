// People search (rename an unnamed person found by face), snapshot library (two-step delete), face notifications.
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EventSummary, FaceSummary, LiveState } from "../api";
import { Notifications } from "../components/Notifications";
import { Library } from "../pages/Library";
import { People } from "../pages/People";
import { render } from "./render";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
afterEach(() => { vi.unstubAllGlobals(); });

describe("People", () => {
  it("names an unknown person in place (saved only after the server confirmed)", async () => {
    const person = { id: 5, full_name: "", auto_named: true, notes: "", list_status: "unknown", plates: 0, faces: 3,
      last_seen: "2026-10-13T08:00:00Z", cover_face: "f-1" };
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") return json({ ...person, full_name: "Reza", auto_named: false });
      return json({ items: [person], total: 1, limit: 120, offset: 0 });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><People role="operator" /></MemoryRouter>);
    expect(await screen.findByText("Unknown #5")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    await userEvent.type(screen.getByLabelText("Name of Unknown #5"), "Reza{Enter}");
    await waitFor(() => expect(screen.getAllByText("Reza").length).toBeGreaterThan(0));
    const patch = fetchMock.mock.calls.find(([, i]) => i?.method === "PATCH")!;
    expect(String(patch[0])).toContain("/persons/5");
    expect(JSON.parse(String(patch[1]!.body))).toEqual({ full_name: "Reza" });
  });
  it("searches by name", async () => {
    const fetchMock = vi.fn(async (_url: string) => json({ items: [], total: 0, limit: 120, offset: 0 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><People role="viewer" /></MemoryRouter>);
    await userEvent.type(screen.getByPlaceholderText("Search name (or #number)"), "علی{Enter}");
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => decodeURIComponent(String(u)).includes("q=علی"))).toBe(true));
  });
});

describe("Library", () => {
  it("deletes a selected snapshot after a second confirming press", async () => {
    const snap = { kind: "face", id: "f-9", timestamp: "2026-10-13T08:00:00Z", camera_id: "door", list_status: "unknown",
      person_id: 4, person_name: "Sara", person_auto: false };
    const fetchMock = vi.fn(async (_u: string, init?: RequestInit) =>
      init?.method === "DELETE" ? json({ deleted: 1 }) : json({ items: [snap], total: 1, limit: 48, offset: 0 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><Library role="admin" /></MemoryRouter>);
    await userEvent.click(await screen.findByRole("checkbox", { name: "Select Sara" }));
    const del = screen.getByRole("button", { name: "Delete selected" });
    await userEvent.click(del);
    expect(fetchMock.mock.calls.some(([, i]) => i?.method === "DELETE")).toBe(false);   // first press only arms it
    await userEvent.click(screen.getByRole("button", { name: "Delete 1 images?" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("1 images deleted."));
    const call = fetchMock.mock.calls.find(([, i]) => i?.method === "DELETE")!;
    expect(JSON.parse(String(call[1]!.body))).toEqual({ items: [{ kind: "face", id: "f-9" }] });
  });
});

describe("Face notifications", () => {
  it("shows a blocklisted person's name and snapshot as an alert", async () => {
    let onFace!: (f: FaceSummary, alert: boolean) => void;
    const connect = (_e: (e: EventSummary) => void, _s: (s: LiveState) => void, _a?: (e: EventSummary) => void,
      face?: (f: FaceSummary, alert: boolean) => void) => { onFace = face!; return () => undefined; };
    render(<MemoryRouter><Notifications enabled connect={connect} /></MemoryRouter>);
    const f: FaceSummary = { id: "f-1", timestamp: "2026-10-13T08:00:00Z", camera_id: "door", track_id: 2, person_id: 3,
      person_name: "Sara", person_auto: false, similarity: 0.7, match: "matched", det_score: 0.9, list_status: "blocklist",
      has_snapshot: true, has_embedding: true };
    act(() => onFace(f, true));
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Blocklisted person");
    expect(alert).toHaveTextContent("Sara");
    expect(alert.querySelector("img")).toHaveAttribute("src", expect.stringContaining("/faces/f-1/snapshot"));
  });
});

describe("Register people", () => {
  it("derives names from file names and groups photos per person", async () => {
    const { nameFromFile, groupByName } = await import("../pages/RegisterPeople");
    expect(nameFromFile("Ali_Rezaei-2.jpg")).toBe("Ali Rezaei");
    expect(nameFromFile("علی رضایی (3).png")).toBe("علی رضایی");
    expect(nameFromFile("Sara.JPG")).toBe("Sara");
    const f = (n: string) => new File(["x"], n, { type: "image/jpeg" });
    const g = groupByName([f("Ali Rezaei.jpg"), f("Ali Rezaei_2.jpg"), f("Sara.png"), f("notes.txt")]);
    expect(g.map((x) => [x.name, x.files.length])).toEqual([["Ali Rezaei", 2], ["Sara", 1]]);
  });
  it("registers each row in turn and offers a merge with an already seen face", async () => {
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => undefined }));
    const { RegisterPeople } = await import("../pages/RegisterPeople");
    const bodies: FormData[] = [];
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).includes("/merge")) return json({ id: 9, merged: 4 });
      bodies.push(init!.body as FormData);
      return json({ person: { id: 9, full_name: "Ali" }, photos: [{ file: "a.jpg", ok: true }],
        similar: { id: 4, full_name: "", auto_named: true, similarity: 0.71 } }, 201);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><RegisterPeople /></MemoryRouter>);
    await userEvent.type(screen.getByLabelText("Name"), "Ali");
    await userEvent.upload(screen.getByLabelText(/Photos \(0\)/), new File(["x"], "a.jpg", { type: "image/jpeg" }));
    await userEvent.click(screen.getByRole("button", { name: "Register 1 people" }));
    expect(await screen.findByText("Saved: 1 of 1 photos had a face")).toBeInTheDocument();
    expect(bodies[0].get("full_name")).toBe("Ali");
    expect((bodies[0].getAll("photos")[0] as File).name).toBe("a.jpg");
    expect(screen.getByText(/looks like “Unknown #4” \(71%\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Merge" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/persons/4/merge"))).toBe(true));
  });
});

describe("Videos", () => {
  it("cleans file names and sends loop/realtime only for file sources", async () => {
    const { cleanName } = await import("../components/VideoUploads");
    const { sourceBody } = await import("../pages/Settings");
    expect(cleanName("My gate video?.MP4")).toBe("My gate video_.mp4");
    expect(cleanName("../../etc/passwd.mov")).toBe("passwd.mov");
    expect(cleanName("ورودی ۱.mkv")).toBe("ورودی ۱.mkv");
    const base = { id: "v", name: "v", uri: "/data/videos/v.mp4", max_fps: "10", loop: true, fast: true };
    expect(sourceBody({ ...base, type: "file" })).toEqual({ id: "v", name: "v", type: "file", uri: "/data/videos/v.mp4", max_fps: 10, loop: true, realtime: false });
    expect(sourceBody({ ...base, type: "rtsp" })).toEqual({ id: "v", name: "v", type: "rtsp", uri: "/data/videos/v.mp4", max_fps: 10 });
  });
});

describe("Source copies", () => {
  it("adds the source, then its copies pointing at it", async () => {
    const { Settings } = await import("../pages/Settings");
    const posts: Record<string, unknown>[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && String(url).endsWith("/cameras")) { posts.push(JSON.parse(String(init.body))); return json({}, 201); }
      if (String(url).includes("/videos")) return json({ items: [], free_bytes: 1e10, max_bytes: 2e9 });
      return json([]);
    }));
    render(<MemoryRouter><Settings role="admin" onTheme={() => undefined} /></MemoryRouter>);
    await userEvent.type(await screen.findByLabelText("ID"), "gate");
    await userEvent.type(screen.getByLabelText("URI"), "rtsp://cam/1");
    await userEvent.clear(screen.getByLabelText("Copies"));
    await userEvent.type(screen.getByLabelText("Copies"), "3");
    await userEvent.click(screen.getByRole("button", { name: "Add source" }));
    await waitFor(() => expect(posts).toHaveLength(3));
    expect(posts.map((p) => [p.id, p.copy_of ?? null])).toEqual([["gate", null], ["gate-2", "gate"], ["gate-3", "gate"]]);
  });
});
