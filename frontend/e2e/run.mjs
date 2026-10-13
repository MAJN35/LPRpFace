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
    timestamp: new Date(Date.now() - minutesAgo * 60000).toISOString(), track_id: 1,
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

for (const [i, d] of demo.entries()) await ingest(ev(d, 30 - i * 5));
const browser = await puppeteer.launch({ executablePath: process.env.CHROME ?? "/usr/bin/chromium",
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"], headless: true });
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });
const shot = async (name) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true }); };
const text = () => page.evaluate(() => document.body.innerText);
try {
  await page.goto(URL_, { waitUntil: "networkidle0" });
  await shot("login");
  await page.type("input[autocomplete=username]", process.env.ADMIN_USERNAME ?? "admin");
  await page.type("input[type=password]", process.env.ADMIN_PASSWORD ?? "");
  await Promise.all([page.click("button[type=submit]"), page.waitForSelector("nav.side")]);
  check(true, "login");
  await page.waitForFunction(() => document.body.innerText.includes("Recent plates"));
  await new Promise((r) => setTimeout(r, 1500));
  check((await text()).includes("27 Jim 814 | 55"), "overview lists real API data");
  await shot("overview");

  await page.goto(`${URL_}/history?`, { waitUntil: "networkidle0" });
  await page.type("input[placeholder^='۱۲ب']", "ل۲۰۹");
  await page.click("button[type=submit]");
  await page.waitForFunction(() => document.body.innerText.includes("63 Lam 209 | 11"), { timeout: 10000 });
  const t = await text();
  check(t.includes("63 Lam 209 | 11") && !t.includes("27 Jim 814 | 55"), "history: Persian partial search finds only the matching plate");
  const dir = await page.$eval(".plate .fa", (el) => getComputedStyle(el).direction);
  check(dir === "rtl", "Persian plate rendered right-to-left");
  await page.click("button[type=button]");          // Clear
  await page.waitForFunction(() => document.body.innerText.includes("27 Jim 814 | 55"));
  await shot("history");

  await page.click("tbody tr a");
  await page.waitForFunction(() => document.body.innerText.includes("Characters"));
  check((await text()).includes("frame(s) voted"), "event detail");
  await shot("event_detail");

  await page.goto(`${URL_}/live`, { waitUntil: "networkidle0" });
  await page.waitForFunction(() => !document.body.innerText.includes("Connecting to live"), { timeout: 10000 });
  const liveEv = ev(["۹۱ ق ۴۴۵ | ۲۲", "91 Ghaf 445 | 22", "91Ghaf44522", "standard", null, true, null], 0);
  await ingest(liveEv);
  await page.waitForFunction(() => document.body.innerText.includes("91 Ghaf 445 | 22"), { timeout: 10000 });
  check(true, "live: new event arrives over WebSocket through nginx");
  await shot("live");

  await page.goto(`${URL_}/health`, { waitUntil: "networkidle0" });
  await page.waitForFunction(() => document.body.innerText.includes("Events stored"));
  check(true, "system health page");
  await shot("health");

  await page.goto(`${URL_}/settings`, { waitUntil: "networkidle0" });
  await page.waitForFunction(() => document.body.innerText.includes("Appearance"));
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
