// The UI character mapping must match the model's class table (models/v2/class_names.json, AGENTS.md A.4).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { DIGITS, DIPLOMATIC, LETTERS, ZHE, ZONES, parseChar, toLatinDigits } from "../plate/charset";

const classes = JSON.parse(readFileSync(resolve(__dirname, "../../../models/v2/class_names.json"), "utf8"));

describe("plate charset vs model classes", () => {
  it("ids and names match class_names.json", () => {
    for (const c of [...DIGITS, ...LETTERS, ZHE, ...DIPLOMATIC]) expect(classes.names[String(c.id)]).toBe(c.name);
    for (const z of ZONES) expect(classes.names[String(z.id)]).toBe(`fz_${z.code}`);
  });
  it("glyphs match char_glyphs where the model defines one", () => {
    for (const c of [...DIGITS, ...LETTERS]) {
      const g = classes.char_glyphs[String(c.id)];
      if (g !== undefined) expect(c.glyph).toBe(g);
    }
  });
  it("never offers object, region or marker labels as characters", () => {
    const names = [...DIGITS, ...LETTERS, ZHE, ...DIPLOMATIC].map((c) => c.name);
    for (const bad of ["plate", "face", "freezone", "protocol", "fz_KISH"]) expect(names).not.toContain(bad);
  });
  it("normalizes typed input", () => {
    expect(parseChar("۷", DIGITS)?.id).toBe(7);
    expect(parseChar("٧", DIGITS)?.id).toBe(7);
    expect(parseChar("7", DIGITS)?.id).toBe(7);
    expect(parseChar("ي", LETTERS)?.name).toBe("Ye");
    expect(parseChar("ك", LETTERS)?.name).toBe("Kaf");
    expect(parseChar("ا", LETTERS)?.name).toBe("Alef");
    expect(parseChar("be", LETTERS)?.name).toBe("Be");
    expect(parseChar("ب", DIGITS)).toBeNull();
    expect(parseChar("x", LETTERS)).toBeNull();
    expect(toLatinDigits("۱۲٣")).toBe("123");
  });
});
