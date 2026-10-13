// Liquid indicator: it flows from the old item to the new one (stretching on the way, leading edge first), settles
// exactly on the target, retargets mid-flight, and jumps without animation under reduced motion.
import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiquidGroup } from "../components/LiquidIndicator";
import { render } from "./render";

// three stacked items, 30 px tall, 10 px apart (top = 40 * index), 100 px wide
function rect(top: number, h = 30) {
  return { top, bottom: top + h, left: 0, right: 100, width: 100, height: h, x: 0, y: top, toJSON: () => ({}) } as DOMRect;
}
function Menu() {
  const [sel, setSel] = useState(0);
  return (
    <LiquidGroup selector='[aria-pressed="true"]' activeKey={sel} role="group" aria-label="menu">
      {[0, 1, 2].map((i) => <button key={i} aria-pressed={sel === i} data-i={i} onClick={() => setSel(i)}>item {i}</button>)}
    </LiquidGroup>
  );
}
let frameCbs: FrameRequestCallback[] = [];
let now = 0;
function frames(n: number) {
  for (let k = 0; k < n; k++) {
    now += 16;
    const cbs = frameCbs; frameCbs = [];
    act(() => cbs.forEach((cb) => cb(now)));
  }
}
const box = () => {
  const el = document.querySelector<HTMLElement>(".liquid")!;
  const m = /translate\(([-\d.]+)px, ([-\d.]+)px\)/.exec(el.style.transform)!;
  return { top: Number(m[2]), height: parseFloat(el.style.height), width: parseFloat(el.style.width) };
};

beforeEach(() => {
  frameCbs = []; now = 0;
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => { frameCbs.push(cb); return frameCbs.length; });
  vi.stubGlobal("cancelAnimationFrame", () => { frameCbs = []; });
  vi.spyOn(performance, "now").mockImplementation(() => now);
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    const i = this.dataset.i;
    return i !== undefined ? rect(40 * Number(i)) : rect(0, 120);
  });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("Liquid indicator", () => {
  it("starts on the selected item without animating", () => {
    render(<Menu />);
    expect(box()).toEqual({ top: 0, height: 30, width: 100 });
    expect(frameCbs).toHaveLength(0);
  });
  it("stretches toward the new item (leading edge first), narrows, then settles there", async () => {
    render(<Menu />);
    await userEvent.click(screen.getByText("item 2"));
    frames(4);
    const mid = box();
    expect(mid.height).toBeGreaterThan(40);          // stretched along the path
    expect(mid.top).toBeLessThan(40);                // trailing edge still behind
    expect(mid.width).toBeLessThan(100);             // a stretched drop is narrower
    frames(120);
    expect(box()).toEqual({ top: 80, height: 30, width: 100 });
    expect(frameCbs).toHaveLength(0);                // no frames once settled
  });
  it("retargets mid-flight without jumping back", async () => {
    render(<Menu />);
    await userEvent.click(screen.getByText("item 2"));
    frames(3);
    const before = box().top;
    await userEvent.click(screen.getByText("item 1"));
    frames(1);
    expect(Math.abs(box().top - before)).toBeLessThan(15);   // continues from where it was
    frames(120);
    expect(box()).toEqual({ top: 40, height: 30, width: 100 });
  });
  it("stays bounded when frame timestamps are earlier than the request time (seen in Chromium)", async () => {
    render(<Menu />);
    vi.spyOn(performance, "now").mockImplementation(() => now + 500);    // the clock read at request time runs ahead
    await userEvent.click(screen.getByText("item 2"));
    let maxH = 0;
    for (let k = 0; k < 120; k++) { frames(1); maxH = Math.max(maxH, box().height); }
    expect(maxH).toBeLessThan(30 + 80 + 1);       // never longer than the whole path
    expect(box()).toEqual({ top: 80, height: 30, width: 100 });
  });
  it("jumps straight to the item under reduced motion", async () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("reduce"), media: q, addEventListener() {}, removeEventListener() {} }));
    render(<Menu />);
    await userEvent.click(screen.getByText("item 2"));
    expect(box()).toEqual({ top: 80, height: 30, width: 100 });
    expect(frameCbs).toHaveLength(0);
  });
});
