// Persian-first plate search: default language, the editable plate (typing, list, validation) and the request.
import { render as rtl, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LangSwitch } from "../components/LangSwitch";
import { I18nProvider } from "../i18n";
import { History } from "../pages/History";
import { DIGITS, LETTERS } from "../plate/charset";
import { eventPlate, formatById, plateQuery, valuesFromTokens } from "../plate/formats";
import { render } from "./render";

const PAGE = { items: [], total: 0, limit: 25, offset: 0 };
const urls = () => vi.mocked(fetch).mock.calls.map(([u]) => decodeURIComponent(String(u)));
beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(PAGE), { status: 200, headers: { "Content-Type": "application/json" } })));
});
afterEach(() => { vi.unstubAllGlobals(); });

const renderFa = () => render(<MemoryRouter><History /></MemoryRouter>, { lang: "fa" });

describe("language", () => {
  it("defaults to Persian, right-to-left", async () => {
    rtl(<MemoryRouter><I18nProvider><History /></I18nProvider></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "جستجوی پلاک" })).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("fa");
    expect(document.documentElement.dir).toBe("rtl");
  });
  it("switches to English and remembers the choice", async () => {
    rtl(<I18nProvider><LangSwitch /></I18nProvider>);
    await userEvent.click(screen.getByRole("button", { name: "English" }));
    expect(localStorage.getItem("lpr.lang")).toBe("en");
    expect(document.documentElement.dir).toBe("ltr");
    await userEvent.click(screen.getByRole("button", { name: "فارسی" }));
    expect(localStorage.getItem("lpr.lang")).toBe("fa");
    expect(document.documentElement.dir).toBe("rtl");
  });
});

describe("plate editor", () => {
  it("fills positions by typing (any digit script) and moves on", async () => {
    renderFa();
    const first = screen.getByRole("combobox", { name: "رقم ۱" });
    first.focus();
    await userEvent.keyboard("۱2ب");
    expect(first).toHaveTextContent("۱");
    expect(screen.getByRole("combobox", { name: "رقم ۲" })).toHaveTextContent("۲");
    expect(screen.getByRole("combobox", { name: "حرف" })).toHaveTextContent("ب");
    expect(screen.getByRole("combobox", { name: "رقم ۳" })).toHaveFocus();
  });
  it("rejects a letter in a digit position with a Persian message", async () => {
    renderFa();
    screen.getByRole("combobox", { name: "رقم ۱" }).focus();
    await userEvent.keyboard("ب");
    expect(screen.getByRole("alert")).toHaveTextContent("این خانه فقط رقم می‌پذیرد");
    expect(screen.getByRole("combobox", { name: "رقم ۱" })).toHaveTextContent("–");
  });
  it("offers only plate letters in the letter list and sets the chosen one", async () => {
    renderFa();
    await userEvent.click(screen.getByRole("combobox", { name: "حرف" }));
    const list = screen.getByRole("listbox");
    const opts = within(list).getAllByRole("option").map((o) => o.textContent);
    for (const bad of ["plate", "face", "freezone", "protocol", "fz_KISH", "Gaf", "Zhe"]) expect(opts.join(" ")).not.toContain(bad);
    expect(opts.length).toBe(1 + LETTERS.length - 1);             // "empty" + letters without Gaf (transit type)
    await userEvent.click(within(list).getByRole("option", { name: /ص/ }));
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.getByRole("combobox", { name: "حرف" })).toHaveTextContent("ص");
  });
  it("supports keyboard selection in the list", async () => {
    renderFa();
    const slot = screen.getByRole("combobox", { name: "رقم ۱" });
    slot.focus();
    await userEvent.keyboard("{Enter}{ArrowDown}{ArrowDown}{ArrowDown}{Enter}");   // empty, ۰, ۱, ۲
    expect(slot).toHaveTextContent("۲");
    expect(slot).toHaveAttribute("aria-expanded", "false");
  });
});

describe("search request", () => {
  it("sends a partial slot search", async () => {
    renderFa();
    screen.getByRole("combobox", { name: "رقم ۱" }).focus();
    await userEvent.keyboard("12ب");
    await userEvent.click(screen.getByRole("button", { name: "جستجو" }));
    await waitFor(() => expect(urls().some((u) => u.includes("slots=1,2,Be,,,,,") && u.includes("match=partial")
      && u.includes("layout=standard") && u.includes("plate_type=standard"))).toBe(true));
  });
  it("blocks an incomplete exact search with a message", async () => {
    renderFa();
    await userEvent.click(screen.getByRole("radio", { name: "جستجوی دقیق" }));
    await userEvent.click(screen.getByRole("button", { name: "جستجو" }));
    expect(screen.getByRole("alert")).toHaveTextContent("جستجوی دقیق به همه خانه‌ها نیاز دارد");
    expect(urls().some((u) => u.includes("match=exact"))).toBe(false);
  });
  it("searches free-zone plates by zone", async () => {
    renderFa();
    await userEvent.selectOptions(screen.getByLabelText("نوع پلاک"), "freezone");
    expect(screen.getAllByRole("combobox", { name: /^رقم/ })).toHaveLength(5);
    await userEvent.selectOptions(screen.getByLabelText("منطقه آزاد"), "KISH");
    await userEvent.click(screen.getByRole("button", { name: "جستجو" }));
    await waitFor(() => expect(urls().some((u) => u.includes("plate_type=freezone") && u.includes("zone=KISH"))).toBe(true));
  });
  it("clears the form", async () => {
    renderFa();
    screen.getByRole("combobox", { name: "رقم ۱" }).focus();
    await userEvent.keyboard("7");
    await userEvent.click(screen.getByRole("button", { name: "پاک کردن" }));
    expect(screen.getByRole("combobox", { name: "رقم ۱" })).toHaveTextContent("–");
  });
});

describe("formats", () => {
  const std = formatById("standard");
  it("builds the query only from what the plate says", () => {
    expect(plateQuery(std, valuesFromTokens(std, []), "partial", "")).toEqual({});
    const v = valuesFromTokens(std, ["1", "2", "Be", "", "", "", "6", "7"]);
    expect(plateQuery(std, v, "partial", "")).toEqual({ plate_type: "standard", slots: "1,2,Be,,,,6,7", layout: "standard", match: "partial" });
    const dis = formatById("disabled");
    expect(plateQuery(dis, valuesFromTokens(dis, []), "partial", "")).toEqual({ plate_type: "disabled" });
  });
  it("turns stored reads into plate positions", () => {
    const p = eventPlate({ plate_type: "standard", plate_string_latin: "12 Be 345 | 67", is_valid: true });
    expect(p?.values.map((c) => c?.name)).toEqual(["1", "2", "Be", "3", "4", "5", "6", "7"]);
    expect(eventPlate({ plate_type: "diplomatic", plate_string_latin: "12 D 345 | 67", is_valid: true })?.values[2]?.name).toBe("D");
    expect(eventPlate({ plate_type: "freezone", plate_string_latin: "96213", is_valid: true })?.values).toEqual([9, 6, 2, 1, 3].map((d) => DIGITS[d]));
    expect(eventPlate({ plate_type: "standard", plate_string_latin: "1 2 Be", is_valid: false })).toBeNull();
    expect(eventPlate({ plate_type: "protocol", plate_string_latin: "1 2 3 4", is_valid: null })).toBeNull();
  });
});
