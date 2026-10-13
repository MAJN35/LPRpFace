// End-to-end test against the running stack (frontend -> nginx -> backend) with real Chromium, plus screenshots.
//   E2E_URL=http://frontend:8080 BACKEND_URL=http://backend:8000 ADMIN_USERNAME=admin ADMIN_PASSWORD=... \
//   INGEST_KEY=... CHROME=/usr/bin/chromium SHOTS=/out node e2e/run.mjs
// Uses invented demo plates only (no real plates or crops in screenshots).
import puppeteer from "puppeteer-core";
import { randomUUID } from "node:crypto";

const URL_ = process.env.E2E_URL ?? "http://frontend:8080";
const BACKEND = process.env.BACKEND_URL ?? "http://backend:8000";
const SHOTS = process.env.SHOTS ?? "";
const run = randomUUID().slice(0, 8);
const cam = `e2e-${run}`;
const fa = (n) => String(n).replace(/[0-9]/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);
const d3 = 100 + Math.floor(Math.random() * 900);   // unique plate per run (lists are persistent)
const listPlate = { fa: `۳۸ ج ${fa(d3)} | ۵۵`, latin: `38 Jim ${d3} | 55` };
let failures = 0;
const check = (ok, what) => { console.log(`${ok ? "PASS" : "FAIL"} ${what}`); if (!ok) failures++; };

const demo = [
  ["۲۷ ج ۸۱۴ | ۵۵", "27 Jim 814 | 55", "27Jim81455", "standard", null, true, null],
  ["۶۳ ل ۲۰۹ | ۱۱", "63 Lam 209 | 11", "63Lam20911", "standard", null, true, null],
  ["۸۸۴۲۰", "88420", "88420", "freezone", "QESHM", true, null],
  ["۴۱ ♿ ۷۷۳ | ۲۹", "41 Zhe 773 | 29", "41Zhe77329", "disabled", null, true, null],
  ["۵۰ م ۱۲", "5 0 Mim 1 2", "50Mim12", "unknown", null, false, "expected 8 characters, found 5"],
];
function ev([fa, lat, key, type, zone, valid, reason], minutesAgo) {
  return { schema_version: "2.0", event_id: randomUUID(), event_type: "plate.recognized",
    source: { id: cam, type: "rtsp", uri_redacted: "rtsp://demo-camera/ch1", file_name: null }, camera_id: cam,
    timestamp: new Date(Date.now() - minutesAgo * 1000).toISOString(), track_id: 1,
    model: { version: "v2", sha256: "f".repeat(64), engine_sha256: null, precision: "fp16", batch_profile: [1, 2, 4] },
    plate_type: type, plate_string_fa: fa, plate_string_latin: lat, plate_key: key, zone, expiry: null,
    markers: type === "freezone" ? ["freezone"] : [], characters: [{ class_id: 2, name: "2", confidence: 0.97, margin: 0.9, box: [1, 2, 3, 4] }],
    confidence: 0.91, is_valid: valid, invalid_reason: reason, frames_voted: 5, plate_bbox: [10, 10, 120, 40],
    frame_size: [1920, 1080], best_frame_crop_path: null };
}
async function ingest(e) {
  const r = await fetch(`${BACKEND}/api/v1/ingest/events`, { method: "POST", body: JSON.stringify(e),
    headers: { "Content-Type": "application/json", "X-Ingest-Key": process.env.INGEST_KEY } });
  if (!r.ok) throw new Error(`ingest ${r.status}`);
}

for (const [i, d] of demo.entries()) await ingest(ev(d, 10 - i));   // seconds ago: newest on the Overview
const browser = await puppeteer.launch({ executablePath: process.env.CHROME ?? "/usr/bin/chromium",
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"], headless: true, acceptInsecureCerts: true, ignoreHTTPSErrors: true });
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });
const shot = async (name) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true }); };
// Plates are drawn as plate shapes (no Latin text on screen); their accessible names carry the Latin form, so the
// checks read the page text plus every aria-label.
await page.evaluateOnNewDocument(() => {
  window.__all = () => document.body.innerText + "\n" + [...document.querySelectorAll("[aria-label]")].map((e) => e.getAttribute("aria-label")).join("\n");
});
const text = () => page.evaluate(() => window.__all());
try {
  await page.goto(URL_, { waitUntil: "networkidle0" });
  const htmlLang = await page.evaluate(() => [document.documentElement.lang, document.documentElement.dir].join(" "));
  check(htmlLang === "fa rtl", `Persian is the default language (html lang/dir: ${htmlLang})`);
  // branding: favicons and manifest are served by the production build, the logo is on the login page
  for (const [path, type] of [["/favicon.svg", "image/svg+xml"], ["/favicon.ico", "image/"], ["/apple-touch-icon.png", "image/png"],
    ["/icon-192.png", "image/png"], ["/manifest.webmanifest", "application/manifest+json"]]) {
    const r = await fetch(`${URL_}${path}`);
    check(r.ok && (r.headers.get("content-type") ?? "").includes(type), `${path} served (${r.status} ${r.headers.get("content-type")})`);
  }
  check(await page.$eval("link[rel=icon][type='image/svg+xml']", (l) => l.href.endsWith("/favicon.svg")), "favicon linked in the document");
  check(!!(await page.$(".login-logo .logo-mark")), "logo on the login page");
  await shot("login");
  // Sign in; the bootstrap admin is forced to change its password first (E2E_NEW_PASSWORD), and later runs sign in
  // with that new password.
  const signIn = async (pw) => {
    await page.goto(URL_, { waitUntil: "networkidle0" });
    await page.type("input[autocomplete=username]", process.env.ADMIN_USERNAME ?? "admin");
    await page.type("input[type=password]", pw);
    await page.click("button[type=submit]");
    await page.waitForFunction(() => document.querySelector("nav.side") || document.querySelector("input[autocomplete=new-password]")
      || document.querySelector("[role=alert]"), { timeout: 15000 });
    return page.evaluate(() => document.querySelector("nav.side") ? "app" : document.querySelector("input[autocomplete=new-password]") ? "change" : "error");
  };
  let state = await signIn(process.env.ADMIN_PASSWORD ?? "");
  if (state === "error") state = await signIn(process.env.E2E_NEW_PASSWORD ?? "");
  if (state === "change") {
    check(true, "forced password change shown for the default admin");
    await shot("change_password");
    await page.type("input[autocomplete=current-password]", process.env.ADMIN_PASSWORD ?? "");
    const fields = await page.$$("input[autocomplete=new-password]");
    for (const f of fields) await f.type(process.env.E2E_NEW_PASSWORD ?? "");
    await Promise.all([page.click("button[type=submit]"), page.waitForSelector("nav.side", { timeout: 15000 })]);
    state = "app";
  }
  check(state === "app", "login");
  await page.waitForFunction(() => __all().includes("آخرین پلاک‌ها"));
  check(true, "dashboard in Persian after sign-in");

  // Persian plate search on the realistic plate editor (demo plates only)
  const slot = (name) => `button[role=combobox][aria-label='${name}']`;
  // Real keydown events with the typed character as `key`, as a Persian keyboard sends them (puppeteer's type() sends
  // characters outside the US layout as text input without keydown).
  const keys = (str) => page.evaluate((str) => { for (const k of str) document.activeElement.dispatchEvent(
    new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true })); }, str);
  const searchFa = async () => {
    await page.evaluate(() => [...document.querySelectorAll("form[role=search] button")].find((b) => b.textContent === "جستجو").click());
    await new Promise((r) => setTimeout(r, 300));
    await page.waitForFunction(() => !document.querySelector("[aria-busy=true]"), { timeout: 10000 });
  };
  await page.goto(`${URL_}/history?camera_id=${cam}`, { waitUntil: "networkidle0" });
  await page.focus(slot("رقم ۱"));
  await keys("۶3ل");                       // Persian and Western digits, Persian letter
  await searchFa();
  await page.waitForFunction(() => __all().includes("63 Lam 209 | 11"), { timeout: 10000 });
  let t0 = await text();
  check(t0.includes("63 Lam 209 | 11") && !t0.includes("27 Jim 814 | 55"), "plate search (partial): typed ۶3ل on the plate finds only 63 Lam 209 | 11");
  const order = await page.$eval("tbody .lp", (el) => [getComputedStyle(el).direction, el.innerText.replace(/\s+/g, "")]);
  check(order[0] === "ltr" && order[1].indexOf("۶۳") < order[1].indexOf("ل"), "result drawn as a realistic plate in physical left-to-right order");
  await shot("history_fa");
  await page.click("[role=radio][aria-checked=false]");    // -> exact
  await searchFa();
  t0 = await text();
  check(t0.includes("جستجوی دقیق به همه خانه‌ها نیاز دارد"), "exact search with empty positions is refused with a Persian message");
  await page.focus(slot("رقم ۳"));
  await keys("20911");
  await searchFa();
  await page.waitForFunction(() => __all().includes("63 Lam 209 | 11"), { timeout: 10000 });
  check((await text()).includes("1 رویداد") || (await text()).includes("۱ رویداد"), "plate search (exact) finds exactly one event");
  await page.focus(slot("رقم ۱"));
  await page.keyboard.press("Backspace");
  await keys("ب");
  t0 = await text();
  check(t0.includes("این خانه فقط رقم می‌پذیرد"), "a letter in a digit position is rejected in Persian");
  await page.select("form[role=search] select", "freezone");
  await page.waitForSelector(slot("رقم ۵"));
  const zoneSel = await page.$$("form[role=search] .plate-search-top select");
  await zoneSel[1].select("QESHM");
  await searchFa();
  await page.waitForFunction(() => __all().includes("88420"), { timeout: 10000 });
  t0 = await text();
  check(t0.includes("88420") && !t0.includes("63 Lam 209 | 11"), "free-zone search by zone (Qeshm)");
  await shot("history_freezone_fa");

  // the rest in English (language switch, remembered)
  // language and notification switches live in Settings
  await page.goto(`${URL_}/settings`, { waitUntil: "networkidle0" });
  check(!(await page.$("nav.side [role=group][aria-label='زبان']")), "language switch is in Settings, not the sidebar");
  await page.evaluate(() => [...document.querySelectorAll("main button")].find((b) => b.textContent === "English").click());
  await page.goto(URL_, { waitUntil: "networkidle0" });
  const htmlEn = await page.evaluate(() => [document.documentElement.lang, document.documentElement.dir, localStorage.getItem("lpr.lang")].join(" "));
  check(htmlEn === "en ltr en", `language switch to English is remembered (${htmlEn})`);
  await page.waitForFunction(() => __all().includes("Recent plates"));
  check((await text()).includes("Recent people"), "overview shows the recent people log");
  await new Promise((r) => setTimeout(r, 1500));
  // real API data: the recent table has rows (with a live camera the newest rows are camera events, not demo plates)
  const recentRows = await page.$$eval("section[aria-labelledby=recent-h] tbody tr", (r) => r.length);
  check(recentRows > 0, `overview lists real API data (${recentRows} recent rows)`);
  await shot("overview");

  await page.goto(`${URL_}/history?`, { waitUntil: "networkidle0" });
  await page.click("form[role=search] details summary");
  await page.type("form[role=search] details input", "ل۲۰۹");
  await page.click("form[role=search] button[type=submit]");
  await page.waitForFunction(() => __all().includes("63 Lam 209 | 11") && !__all().includes("27 Jim 814 | 55")
    && !document.querySelector("[aria-busy=true]"), { timeout: 10000 });
  const t = await text();
  check(t.includes("63 Lam 209 | 11") && !t.includes("27 Jim 814 | 55"), "history: Persian partial search finds only the matching plate");
  const dir = await page.$eval("tbody .lp", (el) => getComputedStyle(el).direction);
  check(dir === "ltr", "plate drawn in its physical left-to-right order inside the page");
  await page.evaluate(() => [...document.querySelectorAll("form[role=search] button")].find((b) => b.textContent === "Clear").click());
  await page.waitForFunction(() => __all().includes("27 Jim 814 | 55"));
  await shot("history");

  await page.click("tbody tr a");
  await page.waitForFunction(() => __all().includes("Characters"));
  check((await text()).includes("frame(s) voted"), "event detail");
  await shot("event_detail");

  await page.goto(`${URL_}/live`, { waitUntil: "networkidle0" });
  await page.waitForFunction(() => !__all().includes("Connecting to live"), { timeout: 10000 });
  const liveEv = ev(["۹۱ ق ۴۴۵ | ۲۲", "91 Ghaf 445 | 22", "91Ghaf44522", "standard", null, true, null], 0);
  await ingest(liveEv);
  await page.waitForFunction(() => __all().includes("91 Ghaf 445 | 22"), { timeout: 10000 });
  check(true, "live: new event arrives over WebSocket through nginx");
  await page.waitForSelector(".toasts .toast", { timeout: 5000 });
  check(true, "notification shown for the detection");
  await shot("notification");
  for (const b of await page.$$(".toasts .toast-close")) await b.click();
  await shot("live");

  await page.goto(`${URL_}/lists`, { waitUntil: "networkidle0" });
  await page.type("form[aria-label='Add plate'] input", listPlate.fa);
  await page.click("form[aria-label='Add plate'] button[type=submit]");
  await page.waitForFunction(() => __all().includes("added to Blocklist"), { timeout: 10000 });
  const grp = `[role=group][aria-label='List for ${listPlate.latin}']`;
  await page.waitForSelector(grp);
  await page.click(`${grp} button:first-child`);   // -> Whitelist
  await page.waitForFunction(() => __all().includes("moved to Whitelist"), { timeout: 10000 });
  check(true, "lists: add a plate in Persian to the blocklist, move it to the whitelist in one click");
  await page.click("[role=tablist][aria-label=List] button:first-child");
  await page.waitForSelector(`${grp} button[aria-pressed=true]`);
  await new Promise((r) => setTimeout(r, 800));
  await shot("lists");

  await page.goto(`${URL_}/health`, { waitUntil: "networkidle0" });
  await page.waitForFunction(() => __all().includes("Events stored"));
  check(true, "system health page");
  await shot("health");

  // face recognition: an ingested face of an unknown person appears as "Unknown #n" and can be named in place
  // a random direction: unrelated to any earlier person (random 512-d vectors have cosine ~0)
  const raw = Array.from({ length: 512 }, () => Math.random() - 0.5);
  const norm = Math.hypot(...raw);
  const emb = Buffer.from(new Float32Array(raw.map((v) => v / norm)).buffer).toString("base64");
  const fid = randomUUID();
  const fr = await fetch(`${BACKEND}/api/v1/ingest/faces`, { method: "POST", headers: { "Content-Type": "application/json", "X-Ingest-Key": process.env.INGEST_KEY },
    body: JSON.stringify({ event: { schema_version: "1.0", event_id: fid, event_type: "face.detected",
      source: { id: cam, type: "rtsp", uri_redacted: "rtsp://demo-camera/ch1", file_name: null }, camera_id: cam,
      timestamp: new Date().toISOString(), track_id: 4, face_bbox: [10, 10, 110, 130], frame_size: [1920, 1080], det_score: 0.9,
      frames_seen: 5, snapshot_path: `faces/${cam}/demo/${fid}.jpg`, snapshot_face_box: [5, 5, 105, 125], model: { version: "v2" } },
      embed_model: "arcface_r50_w600k", embedding_b64: emb, embed_det_score: 0.9, sharpness: 50 }) }).then((r) => r.json());
  check(fr.match === "new_person" && fr.person_id > 0, `face ingest starts a new unnamed person (#${fr.person_id})`);
  await page.goto(`${URL_}/people`, { waitUntil: "networkidle0" });
  await page.waitForFunction((id) => __all().includes(`Unknown #${id}`), { timeout: 10000 }, fr.person_id);
  await page.click(`button[aria-label='Rename']`);
  const newName = `Demo Person ${d3}`;
  await page.type("form.rename input", newName);
  await page.keyboard.press("Enter");
  await page.waitForFunction((n) => __all().includes(n), { timeout: 10000 }, newName);
  check(true, "people: an unknown person is renamed in place");
  await page.type("form[role=search] input", "Demo Person");
  await page.keyboard.press("Enter");
  await page.waitForFunction((n) => __all().includes(n), { timeout: 10000 }, newName);
  check(true, "people: search by name finds the renamed person");
  await shot("people");
  await page.goto(`${URL_}/people/${fr.person_id}`, { waitUntil: "networkidle0" });
  await page.waitForFunction(() => document.querySelectorAll(".face-tile").length > 0, { timeout: 10000 });
  check(true, "person detail lists the face");
  await page.goto(`${URL_}/people/register`, { waitUntil: "networkidle0" });
  await page.waitForFunction(() => __all().includes("Register people") && !!document.querySelector(".reg-row input"), { timeout: 10000 });
  check(true, "register-people page (rows of name, list, photos)");
  await shot("register_people");
  await page.goto(`${URL_}/library`, { waitUntil: "networkidle0" });
  check(!!(await page.$("[role=radiogroup] button")), "snapshot library page");
  await shot("library");
  // HTTPS on 8443 (self-signed for the LAN): a secure context, so OS notifications are available
  if (process.env.E2E_TLS_URL) {
    const tls = await browser.newPage();
    await tls.goto(process.env.E2E_TLS_URL, { waitUntil: "networkidle0" });
    const ctx = await tls.evaluate(() => [window.isSecureContext, "Notification" in window, location.protocol].join(" "));
    check(ctx === "true true https:", `dashboard over HTTPS is a secure context with notifications (${ctx})`);
    await tls.close();
  }

  // sidebar: icons on every item, collapse with tooltips, state remembered
  const navIcons = await page.$$eval("nav.side a.nav-item", (as) => as.map((a) => !!a.querySelector("svg")));
  check(navIcons.length === 8 && navIcons.every(Boolean), `every menu item has an icon (${navIcons.length})`);
  // liquid menu indicator: flows to the clicked item and settles exactly on it
  await page.click("nav.side a[href='/people']");
  await new Promise((r) => setTimeout(r, 900));
  const lq = await page.evaluate(() => {
    const d = document.querySelector("nav.side .liquid").getBoundingClientRect(), a = document.querySelector("nav.side a.active").getBoundingClientRect();
    return [d.top, d.height, d.width].map(Math.round).join() === [a.top, a.height, a.width].map(Math.round).join();
  });
  check(lq, "liquid menu indicator settles on the selected item");
  const w0 = await page.$eval("nav.side", (n) => n.getBoundingClientRect().width);
  await page.click("nav.side .nav-toggle");
  await new Promise((r) => setTimeout(r, 500));
  const w1 = await page.$eval("nav.side", (n) => n.getBoundingClientRect().width);
  const tips = await page.$$eval("nav.side a.nav-item", (as) => as.every((a) => a.dataset.tip && a.textContent.trim()));
  check(w1 < w0 / 2 && tips, `sidebar collapses (${Math.round(w0)} -> ${Math.round(w1)} px) with tooltips and accessible names`);
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "dark"));
  await new Promise((r) => setTimeout(r, 600));            // let the theme transition finish
  await shot("collapsed_dark");
  await page.click("nav.side .nav-toggle");
  await page.evaluate(() => document.documentElement.removeAttribute("data-theme"));

  await page.goto(`${URL_}/settings`, { waitUntil: "networkidle0" });
  await page.waitForFunction(() => __all().includes("Appearance"));
  check(true, "settings page");
  await shot("settings");
} catch (e) {
  console.log(`FAIL ${e.message}`);
  failures++;
  await shot("failure");
} finally {
  await browser.close();
}
console.log(failures ? `E2E FAILED (${failures})` : "E2E OK");
process.exit(failures ? 1 : 0);
