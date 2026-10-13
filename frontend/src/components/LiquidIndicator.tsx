// Liquid selection indicator: one highlight that flows between the items of a group (sidebar menu, tabs, segmented
// buttons) like a drop of water. Each of its four edges is a spring; the edge facing the destination is stiff and
// leads, the trailing edge is soft and follows, so the drop stretches along its path, narrows a little while
// stretched (volume kept), and settles with a slight overshoot. Retargeting keeps position and velocity, so rapid
// clicks bend the motion toward the newest item instead of restarting it.
//
// Positions are measured from the real selected element (offset box relative to the group), on every change of
// `activeKey`, and again when the group resizes (collapse/expand, language/direction, fonts, wrapping on phones).
// Physical edges (top/left/...), so up/down, RTL/LTR and wrapped rows all work. requestAnimationFrame runs only while
// the drop moves; with prefers-reduced-motion it jumps to the target. The element is aria-hidden and ignores the
// pointer; the selected item keeps its own aria state.
import { HTMLAttributes, ReactNode, RefObject, useEffect, useLayoutEffect, useRef } from "react";

type Edge = { x: number; v: number };
type Box = { top: number; bottom: number; left: number; right: number };
const EDGES = ["top", "bottom", "left", "right"] as const;

// spring constants (per second): leading edge pulls ahead, trailing edge follows with a softer, slightly bouncier spring
const LEAD = { k: 520, c: 2 * Math.sqrt(520) * 0.82 };
const TRAIL = { k: 150, c: 2 * Math.sqrt(150) * 0.72 };
const SETTLE = { k: 300, c: 2 * Math.sqrt(300) * 0.9 };   // size changes in place (collapse, resize)
const SQUEEZE = 0.22;                                       // how much the drop narrows per unit of stretch

function reduced() {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

export function measure(group: HTMLElement, el: HTMLElement): Box {
  const g = group.getBoundingClientRect();
  const r = el.getBoundingClientRect();
  return { top: r.top - g.top, bottom: r.bottom - g.top, left: r.left - g.left, right: r.right - g.left };
}

export function LiquidIndicator({ group, selector, activeKey, className = "" }: {
  group: RefObject<HTMLElement>; selector: string; activeKey: unknown; className?: string;
}) {
  const drop = useRef<HTMLSpanElement>(null);
  const edges = useRef<Record<(typeof EDGES)[number], Edge> | null>(null);
  const target = useRef<Box | null>(null);
  const springs = useRef<Record<(typeof EDGES)[number], { k: number; c: number }>>({ top: SETTLE, bottom: SETTLE, left: SETTLE, right: SETTLE });
  const frame = useRef<number | null>(null);
  const last = useRef(0);

  const paint = () => {
    const e = edges.current, el = drop.current, t = target.current;
    if (!e || !el || !t) return;
    const h = Math.max(1, e.bottom.x - e.top.x), w = Math.max(1, e.right.x - e.left.x);
    const th = Math.max(1, t.bottom - t.top), tw = Math.max(1, t.right - t.left);
    // stretch along the longer travel axis -> narrow the other axis a little (a drop keeps its volume)
    const sv = Math.max(0, h / th - 1), sh = Math.max(0, w / tw - 1);
    const insetX = Math.min(w * 0.18, w * SQUEEZE * sv / (1 + sv)), insetY = Math.min(h * 0.18, h * SQUEEZE * sh / (1 + sh));
    el.style.transform = `translate(${e.left.x + insetX}px, ${e.top.x + insetY}px)`;
    el.style.width = `${w - 2 * insetX}px`;
    el.style.height = `${h - 2 * insetY}px`;
    el.style.setProperty("--stretch", String(Math.min(1, sv + sh)));
  };

  const step = (now: number) => {
    const e = edges.current, t = target.current;
    if (!e || !t) { frame.current = null; return; }
    // rAF timestamps can be earlier than performance.now() taken when the frame was requested: the first frame only
    // sets the clock, and every step is kept positive and short (a negative step made the springs blow up)
    if (last.current < 0) { last.current = now; frame.current = requestAnimationFrame(step); return; }
    const dt = Math.min(0.032, Math.max(0.001, (now - last.current) / 1000));
    last.current = now;
    let moving = false;
    for (const k of EDGES) {
      const s = springs.current[k], ed = e[k];
      const a = -s.k * (ed.x - t[k]) - s.c * ed.v;
      ed.v += a * dt;
      ed.x += ed.v * dt;
      if (Math.abs(ed.x - t[k]) > 0.25 || Math.abs(ed.v) > 4) moving = true;
      else { ed.x = t[k]; ed.v = 0; }
    }
    paint();
    if (moving) frame.current = requestAnimationFrame(step);
    else { frame.current = null; drop.current?.classList.add("settled"); }
  };

  const go = (animate: boolean) => {
    const g = group.current;
    const el = g?.querySelector<HTMLElement>(selector);
    if (!g || !el || !drop.current) {
      if (drop.current) drop.current.style.opacity = "0";
      return;
    }
    const t = measure(g, el);
    const prev = target.current;
    const same = prev && EDGES.every((k) => Math.abs(prev[k] - t[k]) < 0.5);
    if (same && edges.current && frame.current == null) return;          // nothing moved: no frames at all
    target.current = t;
    drop.current.style.opacity = "1";
    if (!edges.current || !animate || reduced()) {
      edges.current = { top: { x: t.top, v: 0 }, bottom: { x: t.bottom, v: 0 }, left: { x: t.left, v: 0 }, right: { x: t.right, v: 0 } };
      if (frame.current) cancelAnimationFrame(frame.current);
      frame.current = null;
      paint();
      return;
    }
    // leading edges: the ones facing the direction of travel (by the target's centre vs. the drop's current centre)
    const e = edges.current;
    const dy = (t.top + t.bottom) / 2 - (e.top.x + e.bottom.x) / 2;
    const dx = (t.left + t.right) / 2 - (e.left.x + e.right.x) / 2;
    const moved = !prev || Math.abs(dy) > 2 || Math.abs(dx) > 2;
    springs.current = moved ? {
      top: Math.abs(dy) < 2 ? SETTLE : dy < 0 ? LEAD : TRAIL, bottom: Math.abs(dy) < 2 ? SETTLE : dy > 0 ? LEAD : TRAIL,
      left: Math.abs(dx) < 2 ? SETTLE : dx < 0 ? LEAD : TRAIL, right: Math.abs(dx) < 2 ? SETTLE : dx > 0 ? LEAD : TRAIL,
    } : { top: SETTLE, bottom: SETTLE, left: SETTLE, right: SETTLE };
    drop.current.classList.remove("settled");
    if (frame.current == null) {
      last.current = -1;
      frame.current = requestAnimationFrame(step);
    }
  };

  // selection changed: flow to it (the first placement, e.g. a direct URL load, jumps without animation)
  useLayoutEffect(() => { go(edges.current !== null); }, [activeKey]);
  // first placement: the group's ref is attached after this child's layout effect, so place it once after mount
  useEffect(() => { if (!edges.current) go(false); }, []);
  // geometry changed (collapse/expand, language/direction, wrapping on phones): follow the item's new box
  useEffect(() => {
    const g = group.current;
    if (!g || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => go(true));
    ro.observe(g);
    Array.from(g.children).forEach((n) => ro.observe(n));
    return () => ro.disconnect();
  }, [group, selector]);
  useEffect(() => () => { if (frame.current) cancelAnimationFrame(frame.current); }, []);

  return <span ref={drop} className={`liquid ${className}`} aria-hidden="true" />;
}

// A group (tabs, segmented buttons) whose selected item is marked by the liquid drop. The drop is the last child
// (so :first-child selectors on the items keep working) and sits behind the items (CSS .liquid-host).
export function LiquidGroup({ selector, activeKey, className = "", children, ...rest }: {
  selector: string; activeKey: unknown; className?: string; children: ReactNode } & HTMLAttributes<HTMLDivElement>) {
  const ref = useRef<HTMLDivElement>(null);
  return (
    <div ref={ref} className={`${className} liquid-host`} {...rest}>
      {children}
      <LiquidIndicator group={ref} selector={selector} activeKey={activeKey} />
    </div>
  );
}
