// Iranian licence plate drawn with CSS/SVG and real text (no images). The plate is always laid out in physical
// left-to-right order (dir="ltr"), whatever the page direction:
//   standard: [blue I.R. IRAN strip with flag] 2 digits · letter · 3 digits | ["ایران" over the 2-digit code]
// Only the standard layout follows a verified rule; the others are drawn from the reader's rules and marked
// approximate in the search form (see plate/formats.ts).
import { ReactNode } from "react";
import { ZONES } from "./charset";
import { PlateFormat, SlotValues } from "./formats";

export type SlotRender = (index: number) => ReactNode;

function Flag() {
  return (
    <svg className="lp-flag" viewBox="0 0 12 8" aria-hidden="true" focusable="false">
      <rect width="12" height="8" fill="#da0000" /><rect width="12" height="5.33" fill="#fff" /><rect width="12" height="2.67" fill="#239f40" />
    </svg>
  );
}

export function PlateFrame({ format, values, slot, zone, size = "lg", label }: {
  format: PlateFormat; values: SlotValues; slot: SlotRender; zone?: string; size?: "lg" | "sm"; label: string;
}) {
  const z = ZONES.find((x) => x.code === zone);
  const range = (a: number, b: number) => Array.from({ length: b - a }, (_, i) => a + i);
  if (format.layout === "freezone") return (
    <div className={`lp lp-${size} lp-fz`} dir="ltr" role="group" aria-label={label}>
      <div className="lp-zone" lang="fa"><span>{z ? z.fa : "منطقه آزاد"}</span><span className="lp-latin">{z ? z.code : "FREE ZONE"}</span></div>
      {/* the same number twice: Persian digits above (the positions), Latin digits below (mirror) */}
      <div className="lp-main">{range(0, format.slots.length).map((i) => (
        <span key={i} className="lp-cell lp-col">{slot(i)}<span className="lp-latin" aria-hidden="true">{values[i]?.name ?? "–"}</span></span>
      ))}</div>
    </div>
  );
  if (format.layout === "protocol") return (
    <div className={`lp lp-${size} lp-protocol`} dir="ltr" role="group" aria-label={label}>
      <div className="lp-main">{range(0, format.slots.length).map((i) => <span key={i} className="lp-cell">{slot(i)}</span>)}</div>
      <div className="lp-side" lang="fa"><span className="lp-iran">تشریفات</span></div>
    </div>
  );
  return (
    <div className={`lp lp-${size} lp-${format.id}`} dir="ltr" role="group" aria-label={label}>
      <div className="lp-strip" aria-hidden="true"><Flag /><span>I.R.</span><span>IRAN</span></div>
      <div className="lp-main">
        {range(0, 6).map((i) => <span key={i} className={`lp-cell${i === 2 ? " lp-letter" : ""}`}>{slot(i)}</span>)}
      </div>
      <div className="lp-side">
        <span className="lp-iran" lang="fa">ایران</span>
        <span className="lp-code">{range(6, 8).map((i) => <span key={i} className="lp-cell">{slot(i)}</span>)}</span>
      </div>
    </div>
  );
}

// Read-only plate (results table, event detail). Empty positions show a dash.
export function PlateView({ format, values, zone, size = "sm", label }: {
  format: PlateFormat; values: SlotValues; zone?: string | null; size?: "lg" | "sm"; label: string;
}) {
  return (
    <PlateFrame format={format} values={values} zone={zone ?? undefined} size={size} label={label}
      slot={(i) => <span className="lp-glyph" lang="fa">{values[i]?.glyph ?? "–"}</span>} />
  );
}
