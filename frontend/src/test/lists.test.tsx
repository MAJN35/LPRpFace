import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Lists } from "../pages/Lists";

const PLATE = { id: 7, plate_key: "21Ta65487", plate_string_fa: "۲۱ ط ۶۵۴ | ۸۷", plate_string_latin: "21 Ta 654 | 87",
  list_status: "blocklist", effective_status: "blocklist", person_id: null, person_name: null, notes: "", last_seen: null };
const PLATE2 = { ...PLATE, id: 8, plate_key: "33Mim11122", plate_string_fa: "۳۳ م ۱۱۱ | ۲۲", plate_string_latin: "33 Mim 111 | 22" };

type Call = { url: string; method: string; body: unknown };
function backend() {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const u = String(url); const method = init.method ?? "GET";
    calls.push({ url: u, method, body: init.body ? JSON.parse(String(init.body)) : null });
    let body: unknown = { items: [], total: 0, limit: 1, offset: 0 };
    if (method === "GET" && u.includes("/plates?") && u.includes("list_status=blocklist") && u.includes("limit=200")) body = { items: [PLATE, PLATE2], total: 2, limit: 200, offset: 0 };
    if (u.includes("/plates/unregistered")) body = [];
    if (method !== "GET") body = { ...PLATE, list_status: "whitelist", moved: [7, 8], not_found: [] };
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
  return calls;
}
afterEach(() => vi.unstubAllGlobals());

describe("Lists", () => {
  it("moves a plate to another list with one click", async () => {
    const calls = backend();
    render(<MemoryRouter><Lists role="operator" /></MemoryRouter>);
    const group = await screen.findByRole("group", { name: "List for 21 Ta 654 | 87" });
    expect(within(group).getByRole("button", { name: "Blocklist" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(within(group).getByRole("button", { name: "Whitelist" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH" && c.url.endsWith("/plates/7") && (c.body as { list_status: string }).list_status === "whitelist")).toBe(true));
    expect(await screen.findByText(/moved to Whitelist/)).toBeInTheDocument();
  });

  it("moves several plates in bulk with one call", async () => {
    const calls = backend();
    render(<MemoryRouter><Lists role="admin" /></MemoryRouter>);
    await userEvent.click(await screen.findByLabelText("Select 21 Ta 654 | 87"));
    await userEvent.click(screen.getByLabelText("Select 33 Mim 111 | 22"));
    const bar = screen.getByRole("region", { name: "Bulk move" });
    await userEvent.click(within(bar).getByRole("button", { name: "Unknown" }));
    await waitFor(() => {
      const c = calls.find((x) => x.url.endsWith("/lists/move"));
      expect(c?.body).toEqual({ kind: "plate", ids: [7, 8], list_status: "unknown" });
    });
  });

  it("adds a plate typed in Persian to the current list", async () => {
    const calls = backend();
    render(<MemoryRouter><Lists role="operator" /></MemoryRouter>);
    await userEvent.type(await screen.findByLabelText("Plate (Persian or Latin)"), "۱۲ ب ۳۴۵ | ۶۷");
    await userEvent.click(screen.getByRole("button", { name: "Add to Blocklist" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/plates") && (c.body as { plate: string }).plate === "۱۲ ب ۳۴۵ | ۶۷")).toBe(true));
  });

  it("is read-only for viewers", async () => {
    backend();
    render(<MemoryRouter><Lists role="viewer" /></MemoryRouter>);
    const group = await screen.findByRole("group", { name: "List for 21 Ta 654 | 87" });
    within(group).getAllByRole("button").forEach((b) => expect(b).toBeDisabled());
    expect(screen.queryByRole("button", { name: /Add to/ })).toBeNull();
  });
});
