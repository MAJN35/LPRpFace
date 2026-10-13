// Editable plate: every position is a select-only combobox (button + listbox, WAI-ARIA APG pattern).
//   click / Enter / Space / ArrowDown      open the list of allowed characters for that position
//   typing a character                     sets the position directly (Persian, Arabic-Indic or Western digits;
//                                          Persian letters, Arabic ي/ك normalized) and moves to the next one
//   ArrowLeft / ArrowRight, Home / End     move between positions in the plate's physical (left-to-right) order
//   Backspace / Delete                     clear the position (Backspace on an empty one goes back)
// A character that is not allowed in a position is rejected with a message; object labels (plate, face, freezone,
// fz_*, protocol) are never in any list.
import { KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { Key, useI18n } from "../i18n";
import { CharClass, parseChar } from "./charset";
import { PlateFormat, SlotValues } from "./formats";
import { PlateFrame } from "./PlateView";

export function slotLabel(f: PlateFormat, i: number, t: (k: Key, v?: Record<string, string | number>) => string) {
  const s = f.slots[i];
  if (s.kind === "letter") return t("plate.slot.letter");
  if (f.layout === "standard") return i >= 6 ? t("plate.slot.code", { n: i - 5 }) : t("plate.slot.digit", { n: i < 2 ? i + 1 : i });
  return t("plate.slot.fz", { n: i + 1 });
}

export function PlateEditor({ format, values, onChange, zone, onError, label }: {
  format: PlateFormat; values: SlotValues; onChange: (v: SlotValues) => void; zone?: string;
  onError: (msg: string | null) => void; label: string;
}) {
  const { t } = useI18n();
  const id = useId();
  const [open, setOpen] = useState<number | null>(null);
  const [active, setActive] = useState(0);                    // highlighted option in the open list
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const options = useRef<(HTMLLIElement | null)[]>([]);
  const editable = format.slots.map((s, i) => (s.fixed ? -1 : i)).filter((i) => i >= 0);

  useEffect(() => { setOpen(null); }, [format]);
  useEffect(() => { if (open !== null) options.current[active]?.scrollIntoView?.({ block: "nearest" }); }, [open, active]);

  const focusSlot = (i: number) => buttons.current[i]?.focus();
  const step = (i: number, d: 1 | -1) => {
    const k = editable.indexOf(i) + d;
    return editable[Math.max(0, Math.min(editable.length - 1, k))];
  };
  // Latest values, also between keystrokes that arrive before a re-render (fast typing, scripted input).
  const latest = useRef(values);
  latest.current = values;
  function set(i: number, c: CharClass | null) {
    const v = latest.current.slice(); v[i] = c; latest.current = v; onChange(v); onError(null);
  }
  function openList(i: number) {
    const cur = values[i];
    setActive(Math.max(0, cur ? format.slots[i].options.findIndex((o) => o.id === cur.id) + 1 : 0));
    setOpen(i);
  }
  function choose(i: number, c: CharClass | null) {
    set(i, c); setOpen(null);
    focusSlot(c && i !== editable[editable.length - 1] ? step(i, 1) : i);
  }

  function onSlotKey(i: number, e: KeyboardEvent<HTMLButtonElement>) {
    const opts = format.slots[i].options;
    if (open === i) {                                       // list navigation (index 0 = "empty")
      const n = opts.length + 1;
      if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(n - 1, a + 1)); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); return; }
      if (e.key === "Home") { e.preventDefault(); setActive(0); return; }
      if (e.key === "End") { e.preventDefault(); setActive(n - 1); return; }
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(i, active === 0 ? null : opts[active - 1]); return; }
      if (e.key === "Escape" || e.key === "Tab") { if (e.key === "Escape") e.preventDefault(); setOpen(null); return; }
    }
    if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown") {
      e.preventDefault(); openList(i); return;
    }
    if (e.key === "ArrowRight") { e.preventDefault(); setOpen(null); focusSlot(step(i, 1)); return; }
    if (e.key === "ArrowLeft") { e.preventDefault(); setOpen(null); focusSlot(step(i, -1)); return; }
    if (e.key === "Home") { e.preventDefault(); focusSlot(editable[0]); return; }
    if (e.key === "End") { e.preventDefault(); focusSlot(editable[editable.length - 1]); return; }
    if (e.key === "Backspace" || e.key === "Delete") {
      e.preventDefault();
      if (values[i]) set(i, null); else if (e.key === "Backspace") { const p = step(i, -1); set(p, null); focusSlot(p); }
      return;
    }
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      if (e.key === " ") return;
      const c = parseChar(e.key, opts);
      if (!c) {
        onError(t(format.slots[i].kind === "digit" ? "plate.badDigit" : "plate.badLetter", { v: e.key }));
        return;
      }
      setOpen(null); set(i, c);
      if (i !== editable[editable.length - 1]) focusSlot(step(i, 1));
    }
  }

  const listId = (i: number) => `${id}-list-${i}`;
  const openSlot = open !== null ? format.slots[open] : null;
  return (
    <div className="lp-editor">
      <PlateFrame format={format} values={values} zone={zone} label={label} slot={(i) => {
        const s = format.slots[i];
        const v = values[i];
        const name = slotLabel(format, i, t);
        if (s.fixed) return <span className="lp-glyph lp-fixed" lang="fa" title={t("plate.fixed")} aria-label={`${name}: ${s.fixed.glyph}`}>{s.fixed.glyph}</span>;
        return (
          <button ref={(el) => { buttons.current[i] = el; }} type="button" role="combobox" className={`lp-slot${v ? "" : " empty"}`}
            aria-label={name} aria-haspopup="listbox" aria-expanded={open === i} aria-controls={listId(i)}
            aria-activedescendant={open === i ? `${listId(i)}-${active}` : undefined}
            onClick={() => (open === i ? setOpen(null) : openList(i))} onKeyDown={(e) => onSlotKey(i, e)}>
            <span lang="fa">{v ? v.glyph : "–"}</span>
          </button>
        );
      }} />
      {openSlot && open !== null && (
        <ul id={listId(open)} role="listbox" className={`lp-list raised${openSlot.kind === "letter" ? " letters" : ""}`}
          aria-label={t("plate.pick", { slot: slotLabel(format, open, t) })}>
          {[null, ...openSlot.options].map((o, k) => (
            <li key={o ? o.id : "none"} id={`${listId(open)}-${k}`} ref={(el) => { options.current[k] = el; }} role="option"
              aria-selected={(values[open]?.id ?? null) === (o?.id ?? null)} className={k === active ? "active" : undefined}
              onMouseDown={(e) => e.preventDefault()} onClick={() => choose(open, o)}>
              {o ? <><span className="lp-opt-glyph" lang="fa">{o.glyph}</span>{o.id >= 10 && <span className="lp-opt-name" dir="ltr">{o.name}</span>}</>
                : <span className="muted">{t("plate.empty")}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
