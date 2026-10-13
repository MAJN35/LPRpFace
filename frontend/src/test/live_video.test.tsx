import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LiveVideo } from "../components/LiveVideo";

type Handler = (e: string, d: { fatal: boolean }) => void;
function fakeHls(supported = true) {
  const inst: { handlers: Record<string, Handler>; src?: string; destroyed: boolean; headers: Record<string, string> } =
    { handlers: {}, destroyed: false, headers: {} };
  class FakeHls {
    static isSupported() { return supported; }
    static Events = { MANIFEST_PARSED: "m", FRAG_BUFFERED: "f", ERROR: "e" };
    constructor(cfg: { xhrSetup: (x: { setRequestHeader: (k: string, v: string) => void }) => void }) {
      cfg.xhrSetup({ setRequestHeader: (k, v) => { inst.headers[k] = v; } });
    }
    on(ev: string, h: Handler) { inst.handlers[ev] = h; }
    loadSource(src: string) { inst.src = src; }
    attachMedia() {}
    destroy() { inst.destroyed = true; }
  }
  return { FakeHls, inst };
}

describe("LiveVideo", () => {
  it("loads the stream through /live with the token and shows states", () => {
    sessionStorage.setItem("lpr.token", "tok123");
    const { FakeHls, inst } = fakeHls();
    // @ts-expect-error test double
    render(<LiveVideo path="cam-01-osd" label="cam" HlsImpl={FakeHls} />);
    expect(inst.src).toBe("/live/cam-01-osd/index.m3u8");
    expect(inst.headers.Authorization).toBe("Bearer tok123");
    expect(screen.getByRole("status")).toHaveTextContent("Connecting");
    act(() => inst.handlers.f("f", { fatal: false }));
    expect(screen.queryByRole("status")).toBeNull();
    act(() => inst.handlers.e("e", { fatal: true }));
    expect(screen.getByRole("status")).toHaveTextContent("not available");
  });
  it("explains when the browser cannot play HLS", () => {
    const { FakeHls } = fakeHls(false);
    // @ts-expect-error test double
    render(<LiveVideo path="x" label="cam" HlsImpl={FakeHls} />);
    expect(screen.getByRole("status")).toHaveTextContent("cannot play");
  });
});
