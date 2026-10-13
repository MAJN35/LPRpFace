// Class labels of the model (AGENTS.md A.4 / models/<ver>/class_names.json) that can appear in a plate's character
// positions, with the glyph shown to users. Verified against class_names.json by src/test/plate_charset.test.ts.
// Object/region/marker labels (plate, face, freezone, fz_*, protocol) are deliberately absent: they are never
// selectable characters.
export type CharClass = { id: number; name: string; glyph: string };

export const DIGITS: CharClass[] = Array.from({ length: 10 }, (_, i) => ({ id: i, name: String(i), glyph: "۰۱۲۳۴۵۶۷۸۹"[i] }));

// Plate letters (ids 10–28, 31, 32, 42–44) with the glyphs of class_names.json char_glyphs; Gaf (43) has no glyph
// there and takes گ from A.4. Zhe (29) is the wheelchair symbol of disabled plates; D (45) and S (46) are the Latin
// markers of diplomatic plates.
export const LETTERS: CharClass[] = [
  { id: 10, name: "Alef", glyph: "الف" }, { id: 11, name: "Be", glyph: "ب" }, { id: 12, name: "Te", glyph: "ت" },
  { id: 13, name: "Se", glyph: "ث" }, { id: 14, name: "Jim", glyph: "ج" }, { id: 15, name: "Dal", glyph: "د" },
  { id: 16, name: "Sin", glyph: "س" }, { id: 17, name: "Shin", glyph: "ش" }, { id: 18, name: "Sad", glyph: "ص" },
  { id: 19, name: "Ta", glyph: "ط" }, { id: 20, name: "Za", glyph: "ظ" }, { id: 21, name: "Eyn", glyph: "ع" },
  { id: 22, name: "Ghaf", glyph: "ق" }, { id: 23, name: "Lam", glyph: "ل" }, { id: 24, name: "Mim", glyph: "م" },
  { id: 25, name: "Nun", glyph: "ن" }, { id: 26, name: "He", glyph: "ه" }, { id: 27, name: "Vav", glyph: "و" },
  { id: 28, name: "Pe", glyph: "پ" }, { id: 31, name: "Ye", glyph: "ی" }, { id: 32, name: "Ze", glyph: "ز" },
  { id: 42, name: "Kaf", glyph: "ک" }, { id: 43, name: "Gaf", glyph: "گ" }, { id: 44, name: "Fe", glyph: "ف" },
];
export const ZHE: CharClass = { id: 29, name: "Zhe", glyph: "♿" };
export const DIPLOMATIC: CharClass[] = [{ id: 45, name: "D", glyph: "D" }, { id: 46, name: "S", glyph: "S" }];
export const GAF = LETTERS.find((c) => c.name === "Gaf")!;

// Free-zone name classes (fz_*): region of a free-zone plate, not characters.
export const ZONES = [
  { id: 35, code: "KISH", fa: "کیش" }, { id: 36, code: "QESHM", fa: "قشم" }, { id: 37, code: "CHABAHAR", fa: "چابهار" },
  { id: 38, code: "ARVAND", fa: "اروند" }, { id: 39, code: "ARAS", fa: "ارس" }, { id: 40, code: "ANZALI", fa: "انزلی" },
  { id: 41, code: "MAKU", fa: "ماکو" },
] as const;

const FA = "۰۱۲۳۴۵۶۷۸۹", AR = "٠١٢٣٤٥٦٧٨٩";
export const toLatinDigits = (s: string) => s.replace(/[۰-۹]/g, (d) => String(FA.indexOf(d))).replace(/[٠-٩]/g, (d) => String(AR.indexOf(d)));
export const toPersianDigits = (s: string) => s.replace(/[0-9]/g, (d) => FA[Number(d)]);

// Typed input -> class for a slot, or null when the value is not allowed there. Accepts Persian, Arabic-Indic and
// Western digits; Persian letters (Arabic ي/ك/ى normalized to ی/ک), "ا"/"آ" for Alef, and the Latin class names.
export function parseChar(raw: string, allowed: CharClass[]): CharClass | null {
  const t = toLatinDigits(raw.trim()).replace(/[يى]/g, "ی").replace(/ك/g, "ک");
  if (!t) return null;
  const hit = allowed.find((c) => c.glyph === t || c.name.toLowerCase() === t.toLowerCase() || String(c.id) === t && c.id < 10);
  if (hit) return hit;
  if (t === "ا" || t === "آ") return allowed.find((c) => c.name === "Alef") ?? null;
  return null;
}
