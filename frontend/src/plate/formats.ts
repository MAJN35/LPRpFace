// Plate formats for search, derived from the reader library's verified rules (reader/lpr_reader/reader.py) and the
// test-set labels (tests/data/private/agent_testset_v2/manifest.json), never invented:
//   standard   2 digits + letter + 3 digits | 2-digit code ("ایران" panel); colour types (taxi, police, government,
//              ...) share this layout and are stored as plate_type "standard" (the model cannot see colours)
//   disabled   standard layout, letter = Zhe (wheelchair symbol)
//   diplomatic standard layout, letter = D or S (Latin markers)
//   transit    standard layout, letter = Gaf; the small expiry digits are reported separately, not searchable here
//   freezone   one 5-digit number written twice (Persian row above, Latin row below) + zone (fz_* class)
//   protocol   4–5 digits next to the protocol badge; no validated format rule exists (A.7: not_applicable)
// `verified: false` marks layouts drawn from these rules without a checked visual reference (shown as approximate).
import { CharClass, DIGITS, DIPLOMATIC, GAF, LETTERS, ZHE } from "./charset";

export type SlotDef = { kind: "digit" | "letter"; options: CharClass[]; fixed?: CharClass };
export type PlateFormat = {
  id: "standard" | "disabled" | "diplomatic" | "transit" | "freezone" | "protocol";
  plateType: string;                          // backend plate_type filter
  layout: "standard" | "freezone" | "protocol"; // backend key layout for slot search
  slots: SlotDef[];
  verified: boolean;
  zone?: boolean;                             // free-zone selector
};

const d: SlotDef = { kind: "digit", options: DIGITS };
// Letters of standard-layout plates. Gaf, Zhe, D and S are left out: the reader classifies those plates as transit,
// disabled and diplomatic, so they are selected through the plate type.
const STANDARD_LETTERS = LETTERS.filter((c) => c.name !== "Gaf");

export const FORMATS: PlateFormat[] = [
  { id: "standard", plateType: "standard", layout: "standard", verified: true,
    slots: [d, d, { kind: "letter", options: STANDARD_LETTERS }, d, d, d, d, d] },
  { id: "disabled", plateType: "disabled", layout: "standard", verified: false,
    slots: [d, d, { kind: "letter", options: [ZHE], fixed: ZHE }, d, d, d, d, d] },
  { id: "diplomatic", plateType: "diplomatic", layout: "standard", verified: false,
    slots: [d, d, { kind: "letter", options: DIPLOMATIC }, d, d, d, d, d] },
  { id: "transit", plateType: "transit", layout: "standard", verified: false,
    slots: [d, d, { kind: "letter", options: [GAF], fixed: GAF }, d, d, d, d, d] },
  { id: "freezone", plateType: "freezone", layout: "freezone", verified: false, zone: true, slots: [d, d, d, d, d] },
  { id: "protocol", plateType: "protocol", layout: "protocol", verified: false, slots: [d, d, d, d, d] },
];

export const formatById = (id: string) => FORMATS.find((f) => f.id === id) ?? FORMATS[0];

export type SlotValues = (CharClass | null)[];

export const emptySlots = (f: PlateFormat): SlotValues => f.slots.map((s) => s.fixed ?? null);

// Canonical tokens for the backend (plate_key parts: digits "0"–"9", letters = class names; "" = any).
export const slotTokens = (values: SlotValues) => values.map((v) => (v ? v.name : ""));
export const isComplete = (values: SlotValues) => values.every(Boolean);

export type Match = "exact" | "partial";

// Search parameters for GET /events. The plate type is a filter only when the plate says something (a position
// filled, an exact match, a zone) or a non-standard type is chosen, so the untouched form lists every event.
export function plateQuery(f: PlateFormat, values: SlotValues, match: Match, zone: string) {
  const filled = values.some((v, i) => v && !f.slots[i].fixed);
  const out: Record<string, string> = {};
  if (filled || match === "exact" || zone || f.id !== "standard") out.plate_type = f.plateType;
  if (filled || match === "exact") Object.assign(out, { slots: slotTokens(values).join(","), layout: f.layout, match });
  if (f.zone && zone) out.zone = zone;
  return out;
}

// Back from URL tokens (class names) to positions; unknown tokens become empty.
export function valuesFromTokens(f: PlateFormat, tokens: string[]): SlotValues {
  return f.slots.map((s, i) => s.fixed ?? s.options.find((o) => o.name === tokens[i]) ?? null);
}

const ALL_LETTERS: CharClass[] = [...LETTERS, ZHE, ...DIPLOMATIC];

// A stored event as plate positions (results table), or null when the read does not fit a known layout
// (invalid reads, protocol plates without a validated format): those are shown as text.
// Plate type from the letter when a record has none (watchlist entries): Zhe -> disabled, D/S -> diplomatic,
// Gaf -> transit, 5 digits -> free zone; the reader classifies the same way.
function inferType(latin: string): string {
  const m = /^\d\d (\S+) \d{3} \| \d\d$/.exec(latin);
  if (m) return m[1] === "Zhe" ? "disabled" : m[1] === "D" || m[1] === "S" ? "diplomatic" : m[1] === "Gaf" ? "transit" : "standard";
  return /^\d{5}$/.test(latin) ? "freezone" : "";
}

export function eventPlate(e: { plate_type?: string; plate_string_latin: string; zone?: string | null; is_valid?: boolean | null }):
  { format: PlateFormat; values: SlotValues } | null {
  if (e.is_valid === false || (e.is_valid === null && e.plate_type !== undefined)) return null;
  const type = e.plate_type && e.plate_type !== "unknown" ? e.plate_type : inferType(e.plate_string_latin);
  const f = FORMATS.find((x) => x.plateType === type);
  if (!f) return null;
  if (f.layout === "standard") {
    const m = /^(\d)(\d) (\S+) (\d)(\d)(\d) \| (\d)(\d)$/.exec(e.plate_string_latin);
    const letter = m && ALL_LETTERS.find((c) => c.name === m[3]);
    if (!m || !letter) return null;
    const d = (k: number) => DIGITS[Number(m[k])];
    return { format: f, values: [d(1), d(2), letter, d(4), d(5), d(6), d(7), d(8)] };
  }
  if (f.layout === "freezone" && /^\d{5}$/.test(e.plate_string_latin)) {
    return { format: f, values: [...e.plate_string_latin].map((c) => DIGITS[Number(c)]) };
  }
  return null;
}
