// Localization: Persian (default, RTL) and English. The choice is stored per browser like the theme
// (localStorage "lpr.lang") and applied to <html lang dir>. Plate characters keep their physical left-to-right
// order inside plates regardless of the page direction (see plate/PlateView).
import { ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

export type Lang = "fa" | "en";
const KEY = "lpr.lang";

const fa = {
  "app.brand": "پلاک‌خوان",
  "nav.overview": "نمای کلی", "nav.live": "زنده", "nav.history": "جستجوی پلاک", "nav.lists": "فهرست‌ها",
  "nav.health": "سلامت سامانه", "nav.settings": "تنظیمات", "nav.signout": "خروج", "nav.main": "منوی اصلی",
  "nav.collapse": "جمع کردن منو", "nav.expand": "باز کردن منو",
  "notify.region": "اعلان‌ها", "notify.plate": "پلاک جدید", "notify.on": "اعلان‌ها روشن", "notify.off": "اعلان‌ها خاموش",
  "notify.mute": "خاموش کردن اعلان پلاک‌ها", "notify.unmute": "روشن کردن اعلان پلاک‌ها",
  "notify.hint": "هشدار فهرست ممنوع همیشه نمایش داده می‌شود",
  "lang.label": "زبان", "lang.fa": "فارسی", "lang.en": "English",
  "common.loading": "در حال بارگذاری…", "common.retry": "تلاش دوباره", "common.refresh": "تازه‌سازی", "common.backendDown": "اتصال به سرور برقرار نیست.",
  "common.error": "خطای {status}: {message}", "common.empty": "هنوز موردی برای نمایش نیست.", "common.notFound": "صفحه پیدا نشد.",
  "common.stale": "قدیمی:", "common.staleText": "{what} {seconds} ثانیه پیش به‌روز شده است.", "common.noRead": "پلاکی خوانده نشد",
  "valid.ok": "معتبر", "valid.na": "نامشخص", "valid.naTitle": "قاعده قالب تأییدشده‌ای وجود ندارد", "valid.bad": "نامعتبر",
  "list.whitelist": "فهرست مجاز", "list.blocklist": "فهرست ممنوع", "list.unknown": "نامشخص", "list.for": "فهرست برای {label}",
  "login.title": "ورود", "login.user": "نام کاربری", "login.password": "رمز عبور", "login.submit": "ورود", "login.busy": "در حال ورود…",
  "login.wrong": "نام کاربری یا رمز عبور نادرست است.", "login.down": "اتصال به سرور برقرار نیست.",
  "pw.title": "تغییر رمز عبور", "pw.text": "این حساب هنوز رمز اولیه دارد. پیش از ادامه، رمز تازه‌ای (دست‌کم ۱۲ نویسه) انتخاب کنید.",
  "pw.current": "رمز فعلی", "pw.new": "رمز تازه", "pw.repeat": "تکرار رمز تازه", "pw.submit": "تغییر رمز", "pw.busy": "در حال ذخیره…",
  "pw.short": "رمز تازه باید دست‌کم ۱۲ نویسه باشد.", "pw.mismatch": "دو رمز تازه یکسان نیستند.", "pw.wrong": "رمز فعلی نادرست است.",
  "ov.title": "نمای کلی", "ov.sub": "۲۴ ساعت گذشته", "ov.model": "مدل {version} · {precision}", "ov.read": "پلاک‌های خوانده‌شده (۲۴ ساعت)",
  "ov.valid": "قالب معتبر", "ov.online": "منابع فعال", "ov.fps": "فریم ورودی", "ov.recent": "آخرین پلاک‌ها", "ov.noPlates": "هنوز پلاکی ثبت نشده است.",
  "ov.sources": "منابع", "ov.noSources": "منبعی تعریف نشده است.", "ov.lastEvent": "آخرین رویداد {time}",
  "ov.infDown": "سرویس تشخیص در دسترس نیست.", "ov.status": "وضعیت سامانه",
  "col.time": "زمان", "col.camera": "دوربین", "col.plate": "پلاک", "col.type": "نوع", "col.list": "فهرست", "col.status": "وضعیت",
  "col.model": "مدل", "col.confidence": "اطمینان",
  "live.title": "زنده", "live.sub": "تصویر زنده دوربین‌ها و پلاک‌های تازه‌خوانده‌شده.", "live.connecting": "در حال اتصال به به‌روزرسانی زنده…",
  "live.disconnected": "قطع شد.", "live.reconnecting": "اتصال خودکار دوباره برقرار می‌شود.", "live.waiting": "در انتظار پلاک بعدی…",
  "live.noData": "داده زنده‌ای نیست.", "live.feed": "پلاک‌های زنده", "live.noCams": "منبع ویدیویی فعالی نیست. در تنظیمات دوربین اضافه یا فعال کنید.",
  "live.camera": "دوربین", "live.layout": "چیدمان", "live.grid": "همه دوربین‌ها", "live.single": "یک دوربین", "live.viewOf": "نمای {camera}", "live.view": "نما", "live.osd": "تشخیص‌ها", "live.raw": "تصویر خام",
  "live.rawOnlyNet": "تصویر خام فقط برای دوربین‌های شبکه‌ای در دسترس است.",
  "live.osdNote": "تشخیص‌ها روی فریم‌هایی که مدل پردازش کرده رسم می‌شوند (حدود ۳٫۵ فریم در ثانیه در کل این دستگاه)؛ هم‌زمان فقط یک دوربین با تشخیص‌ها نمایش داده می‌شود و بقیه تصویر خام دارند.",
  "live.rawNote": "جریان اصلی دوربین (دوربین‌های H.265 فقط در مرورگرهای دارای پشتیبانی HEVC پخش می‌شوند).",
  "live.alert": "پلاک فهرست ممنوع", "live.alertOn": "روی {camera} در {time}:", "live.details": "جزئیات", "live.dismiss": "بستن",
  "video.connecting": "در حال اتصال…", "video.unavailable": "جریان هنوز در دسترس نیست؛ دوباره تلاش می‌شود.",
  "video.unsupported": "این مرورگر نمی‌تواند جریان زنده را پخش کند.", "video.withOsd": "با تشخیص‌ها", "video.raw": "خام",
  "hist.title": "جستجوی پلاک", "hist.sub": "نوع پلاک را انتخاب کنید و نویسه‌ها را مستقیم روی پلاک وارد کنید؛ خانه‌های خالی در جستجوی جزئی هر مقداری را می‌پذیرند.",
  "hist.freeText": "جستجوی متنی (هر شکلی از پلاک)", "hist.camera": "دوربین", "hist.from": "از", "hist.to": "تا", "hist.validity": "اعتبار",
  "hist.any": "همه", "hist.valid": "معتبر", "hist.invalid": "نامعتبر", "hist.list": "فهرست", "hist.model": "مدل",
  "hist.search": "جستجو", "hist.clear": "پاک کردن", "hist.results": "نتایج", "hist.count": "{n} رویداد", "hist.export": "خروجی CSV",
  "hist.noMatch": "رویدادی با این شرایط پیدا نشد.", "hist.prev": "قبلی", "hist.next": "بعدی", "hist.range": "{from}–{to} از {total}",
  "hist.pages": "صفحه‌ها", "hist.filters": "فیلترهای بیشتر",
  "plate.type": "نوع پلاک", "plate.standard": "شخصی و عمومی (استاندارد)", "plate.disabled": "معلولین", "plate.diplomatic": "سیاسی (D / S)",
  "plate.transit": "گذر موقت (ترانزیت)", "plate.freezone": "مناطق آزاد", "plate.protocol": "تشریفات",
  "plate.approx": "طرح تقریبی: چیدمان از قواعد تأییدشده خواننده پلاک است، نه از نمونه تصویری بررسی‌شده.",
  "plate.zone": "منطقه آزاد", "plate.anyZone": "همه مناطق", "plate.iran": "ایران",
  "plate.slot.digit": "رقم {n}", "plate.slot.letter": "حرف", "plate.slot.code": "کد منطقه {n}", "plate.slot.fz": "رقم {n}",
  "plate.pick": "انتخاب برای {slot}", "plate.empty": "خالی (هر مقدار)", "plate.fixed": "ثابت برای این نوع پلاک",
  "plate.badDigit": "«{v}» در این خانه مجاز نیست؛ این خانه فقط رقم می‌پذیرد.",
  "plate.badLetter": "«{v}» برای این خانه مجاز نیست؛ یکی از حروف فهرست را انتخاب کنید.",
  "plate.mode": "شیوه جستجو", "plate.exact": "جستجوی دقیق", "plate.partial": "جستجوی جزئی",
  "plate.exactNeedsAll": "جستجوی دقیق به همه خانه‌ها نیاز دارد؛ خانه‌های خالی را پر کنید یا جستجوی جزئی را برگزینید.",
  "plate.help.title": "راهنما",
  "plate.help.1": "روی هر خانه پلاک کلیک کنید و از فهرست انتخاب کنید، یا مستقیم تایپ کنید (ارقام فارسی و انگلیسی هر دو پذیرفته می‌شوند).",
  "plate.help.2": "با کلیدهای جهت بین خانه‌ها جابه‌جا شوید؛ Backspace خانه را پاک می‌کند.",
  "plate.help.3": "جستجوی جزئی: خانه‌های خالی هر مقداری را می‌پذیرند. جستجوی دقیق: همه خانه‌ها باید پر باشند.",
  "plate.help.4": "رنگ پلاک (تاکسی، دولتی و…) را مدل تشخیص نمی‌دهد؛ این پلاک‌ها با نوع «استاندارد» جستجو می‌شوند.",
  "plate.preview": "پلاک {type}",
  "ptype.standard": "استاندارد", "ptype.disabled": "معلولین", "ptype.diplomatic": "سیاسی", "ptype.transit": "ترانزیت",
  "ptype.freezone": "منطقه آزاد", "ptype.protocol": "تشریفات", "ptype.unknown": "نامشخص",
  "ev.title": "رویداد", "ev.sub": "مشاهده این رویداد در گزارش ممیزی ثبت می‌شود.", "ev.time": "زمان (UTC ثبت)", "ev.source": "دوربین / منبع",
  "ev.type": "نوع", "ev.status": "وضعیت", "ev.conf": "اطمینان", "ev.voted": "{conf} · {n} فریم رأی‌گیری‌شده", "ev.track": " · رد {id}",
  "ev.model": "مدل", "ev.listAt": "فهرست در زمان رویداد", "ev.putOnList": "قرار دادن این پلاک در فهرست", "ev.nowOn": "پلاک اکنون در «{list}» است.",
  "ev.chars": "نویسه‌ها", "ev.class": "کلاس", "ev.margin": "فاصله", "ev.evidence": "تصویر شاهد", "ev.noCrop": "تصویری ذخیره نشده است.",
  "ev.cropAlt": "تصویر پلاک {plate}", "ev.copy": "کپی پلاک", "ev.back": "بازگشت", "ev.expiry": "انقضا {v}", "ev.failed": "ناموفق: {m}",
  "health.title": "سلامت سامانه", "health.sub": "هر ۳ ثانیه به‌روز می‌شود.", "health.inference": "سرویس تشخیص", "health.up": "فعال",
  "health.down": "قطع", "health.events": "رویدادهای ذخیره‌شده", "health.cams": "حداکثر دوربین (اندازه‌گیری‌شده، ایمن از نظر حافظه)",
  "health.camsAt": "{n} دوربین با ≥ {fps} فریم بر ثانیه برای هر دوربین", "health.retention": "نگهداری", "health.days": "{n} روز",
  "health.unreachable": "سرویس تشخیص در دسترس نیست:", "health.sources": "منابع", "health.source": "منبع", "health.fpsIn": "فریم ورودی",
  "health.lastFrame": "آخرین فریم", "health.ago": "{s} ثانیه پیش", "health.reconnects": "اتصال دوباره", "health.lastError": "آخرین خطا",
  "health.pipeline": "خط پردازش", "health.modelLine": "مدل {v} · {p} · پروفایل دسته {b}",
  "set.title": "تنظیمات", "set.sub": "نقش شما: {role}. رمز دوربین‌ها در تنظیمات سرور نگه‌داری می‌شود، نه در نشانی نمایش‌داده‌شده.",
  "set.sources": "منابع", "set.noSources": "منبعی وجود ندارد.", "set.id": "شناسه", "set.name": "نام", "set.type": "نوع", "set.uri": "نشانی",
  "set.maxfps": "حداکثر فریم بر ثانیه", "set.faceblur": "پوشاندن چهره", "set.on": "روشن", "set.off": "خاموش", "set.actions": "عملیات",
  "set.enable": "فعال‌سازی", "set.disable": "غیرفعال‌سازی", "set.remove": "حذف", "set.add": "افزودن منبع", "set.added": "منبع {id} افزوده شد.",
  "set.enabled": "{id} فعال شد.", "set.disabled": "{id} غیرفعال شد.", "set.removed": "{id} حذف شد.", "set.failed": "ناموفق: {m}",
  "set.recognize": "تشخیص پلاک در یک تصویر", "set.fileHint": "JPEG یا PNG، حداکثر ۱۰ مگابایت", "set.upload": "بارگذاری",
  "set.processing": "در حال پردازش…", "set.noResult": "پس از ۳۰ ثانیه نتیجه‌ای نیامد", "set.appearance": "ظاهر",
  "set.theme.auto": "خودکار", "set.theme.light": "روشن", "set.theme.dark": "تیره",
  "lists.title": "فهرست‌ها", "lists.sub": "فهرست مجاز، ممنوع و نامشخص برای پلاک‌ها و اشخاص. شخص یک رکورد پیوندخورده به پلاک است؛ هیچ‌کس با چهره شناسایی نمی‌شود.",
  "lists.kind": "نوع", "lists.plates": "پلاک‌ها", "lists.persons": "اشخاص", "lists.list": "فهرست", "lists.search": "جستجو",
  "lists.searchPlate": "جستجوی پلاک (فارسی یا لاتین)", "lists.searchName": "جستجوی نام", "lists.bulk": "جابه‌جایی گروهی",
  "lists.selected": "{n} مورد انتخاب شده — انتقال به:", "lists.clear": "لغو انتخاب", "lists.select": "انتخاب {name}", "lists.person": "شخص",
  "lists.effective": "فهرست مؤثر", "lists.lastSeen": "آخرین مشاهده", "lists.never": "هرگز", "lists.name": "نام", "lists.notes": "یادداشت",
  "lists.delete": "حذف", "lists.deleteName": "حذف {name}", "lists.empty": "موردی در «{list}» نیست.", "lists.moved": "{name} به «{list}» منتقل شد.",
  "lists.movedN": "{n} مورد به «{list}» منتقل شد.", "lists.deleted": "{name} حذف شد.", "lists.linkUpdated": "پیوند شخص به‌روز شد.",
  "lists.unreg": "مشاهده‌شده در ۷ روز گذشته و خارج از همه فهرست‌ها", "lists.unregEmpty": "همه پلاک‌های اخیر در یکی از فهرست‌ها هستند.",
  "lists.sightings": "دفعات مشاهده", "lists.putOn": "قرار دادن در فهرست", "lists.addedTo": "{name} به «{list}» افزوده شد.",
  "lists.addPlate": "افزودن پلاک", "lists.addPerson": "افزودن شخص", "lists.plateInput": "پلاک (فارسی یا لاتین)", "lists.addTo": "افزودن به «{list}»",
  "lists.personFor": "شخص برای {plate}",
} as const;

export type Key = keyof typeof fa;

const en: Record<Key, string> = {
  "app.brand": "Plate recognition",
  "nav.overview": "Overview", "nav.live": "Live", "nav.history": "Plate search", "nav.lists": "Lists", "nav.health": "System health",
  "nav.settings": "Settings", "nav.signout": "Sign out", "nav.main": "Main",
  "nav.collapse": "Collapse menu", "nav.expand": "Expand menu",
  "notify.region": "Notifications", "notify.plate": "New plate", "notify.on": "Notifications on", "notify.off": "Notifications off",
  "notify.mute": "Mute plate notifications", "notify.unmute": "Unmute plate notifications",
  "notify.hint": "Blocklist alerts are always shown",
  "lang.label": "Language", "lang.fa": "فارسی", "lang.en": "English",
  "common.loading": "Loading…", "common.retry": "Retry", "common.refresh": "Refresh", "common.backendDown": "Cannot reach the backend.",
  "common.error": "Error {status}: {message}", "common.empty": "Nothing to show yet.", "common.notFound": "Page not found.",
  "common.stale": "Stale:", "common.staleText": "{what} last updated {seconds} s ago.", "common.noRead": "no plate read",
  "valid.ok": "valid", "valid.na": "not applicable", "valid.naTitle": "No validated format rule", "valid.bad": "invalid",
  "list.whitelist": "Whitelist", "list.blocklist": "Blocklist", "list.unknown": "Unknown", "list.for": "List for {label}",
  "login.title": "Sign in", "login.user": "Username", "login.password": "Password", "login.submit": "Sign in", "login.busy": "Signing in…",
  "login.wrong": "Wrong username or password.", "login.down": "Cannot reach the backend.",
  "pw.title": "Change your password", "pw.text": "This account still uses its initial password. Choose a new one (at least 12 characters) before continuing.",
  "pw.current": "Current password", "pw.new": "New password", "pw.repeat": "Repeat new password", "pw.submit": "Change password", "pw.busy": "Saving…",
  "pw.short": "The new password needs at least 12 characters.", "pw.mismatch": "The two new passwords differ.", "pw.wrong": "The current password is wrong.",
  "ov.title": "Overview", "ov.sub": "Last 24 hours", "ov.model": "model {version} · {precision}", "ov.read": "Plates read (24 h)",
  "ov.valid": "Valid format", "ov.online": "Sources online", "ov.fps": "Frames in", "ov.recent": "Recent plates", "ov.noPlates": "No plates recorded yet.",
  "ov.sources": "Sources", "ov.noSources": "No sources configured.", "ov.lastEvent": "Last event {time}",
  "ov.infDown": "Inference service unreachable.", "ov.status": "System status",
  "col.time": "Time", "col.camera": "Camera", "col.plate": "Plate", "col.type": "Type", "col.list": "List", "col.status": "Status",
  "col.model": "Model", "col.confidence": "Confidence",
  "live.title": "Live", "live.sub": "Live camera views and plates as they are recognized.", "live.connecting": "Connecting to live updates…",
  "live.disconnected": "Disconnected.", "live.reconnecting": "Reconnecting automatically.", "live.waiting": "Waiting for the next plate…",
  "live.noData": "No live data.", "live.feed": "Live plates", "live.noCams": "No enabled video sources. Add or enable a camera in Settings.",
  "live.camera": "Camera", "live.layout": "Layout", "live.grid": "All cameras", "live.single": "One camera", "live.viewOf": "View of {camera}", "live.view": "View", "live.osd": "Detections", "live.raw": "Raw",
  "live.rawOnlyNet": "Raw view is available for network cameras.",
  "live.osdNote": "Detections are drawn on the frames the model processed (about 3.5 per second in total on this device); one camera at a time shows detections, the others play raw.",
  "live.rawNote": "Original camera stream (H.265 cameras play only in browsers with HEVC support).",
  "live.alert": "Blocklisted plate", "live.alertOn": "on {camera} at {time}:", "live.details": "Details", "live.dismiss": "Dismiss",
  "video.connecting": "Connecting…", "video.unavailable": "Stream not available yet — retrying.",
  "video.unsupported": "This browser cannot play the live stream.", "video.withOsd": "with detections", "video.raw": "raw",
  "hist.title": "Plate search", "hist.sub": "Choose the plate type and enter characters directly on the plate; in a partial search empty positions match anything.",
  "hist.freeText": "Free-text search (any plate form)", "hist.camera": "Camera", "hist.from": "From", "hist.to": "To", "hist.validity": "Validity",
  "hist.any": "any", "hist.valid": "valid", "hist.invalid": "invalid", "hist.list": "List", "hist.model": "Model",
  "hist.search": "Search", "hist.clear": "Clear", "hist.results": "Results", "hist.count": "{n} events", "hist.export": "Export CSV",
  "hist.noMatch": "No events match these filters.", "hist.prev": "Previous", "hist.next": "Next", "hist.range": "{from}–{to} of {total}",
  "hist.pages": "Pages", "hist.filters": "More filters",
  "plate.type": "Plate type", "plate.standard": "Private & public (standard)", "plate.disabled": "Disabled", "plate.diplomatic": "Diplomatic (D / S)",
  "plate.transit": "Transit", "plate.freezone": "Free zones", "plate.protocol": "Protocol",
  "plate.approx": "Approximate design: the layout follows the plate reader's verified rules, not a checked visual reference.",
  "plate.zone": "Free zone", "plate.anyZone": "All zones", "plate.iran": "IRAN",
  "plate.slot.digit": "digit {n}", "plate.slot.letter": "letter", "plate.slot.code": "region code {n}", "plate.slot.fz": "digit {n}",
  "plate.pick": "Choose {slot}", "plate.empty": "Empty (any)", "plate.fixed": "Fixed for this plate type",
  "plate.badDigit": "“{v}” is not allowed here: this position takes a digit.",
  "plate.badLetter": "“{v}” is not allowed here: pick one of the listed letters.",
  "plate.mode": "Match", "plate.exact": "Exact match", "plate.partial": "Partial match",
  "plate.exactNeedsAll": "An exact search needs every position; fill the empty ones or use a partial search.",
  "plate.help.title": "Help",
  "plate.help.1": "Click a position on the plate and choose from the list, or type directly (Persian and Western digits both work).",
  "plate.help.2": "Arrow keys move between positions; Backspace clears one.",
  "plate.help.3": "Partial match: empty positions match anything. Exact match: every position must be filled.",
  "plate.help.4": "The model cannot see plate colours (taxi, government, …); such plates are searched as “standard”.",
  "plate.preview": "{type} plate",
  "ptype.standard": "standard", "ptype.disabled": "disabled", "ptype.diplomatic": "diplomatic", "ptype.transit": "transit",
  "ptype.freezone": "free zone", "ptype.protocol": "protocol", "ptype.unknown": "unknown",
  "ev.title": "Event", "ev.sub": "Viewing this event is recorded in the audit log.", "ev.time": "Time (UTC capture)", "ev.source": "Camera / source",
  "ev.type": "Type", "ev.status": "Status", "ev.conf": "Confidence", "ev.voted": "{conf} · {n} frame(s) voted", "ev.track": " · track {id}",
  "ev.model": "Model", "ev.listAt": "List at event time", "ev.putOnList": "Put this plate on a list", "ev.nowOn": "Plate is now on the {list}.",
  "ev.chars": "Characters", "ev.class": "Class", "ev.margin": "Margin", "ev.evidence": "Evidence", "ev.noCrop": "No crop stored.",
  "ev.cropAlt": "Plate crop {plate}", "ev.copy": "Copy plate", "ev.back": "Back", "ev.expiry": "expiry {v}", "ev.failed": "Failed: {m}",
  "health.title": "System health", "health.sub": "Refreshes every 3 s.", "health.inference": "Inference", "health.up": "up",
  "health.down": "down", "health.events": "Events stored", "health.cams": "Max cameras (measured, memory-safe)",
  "health.camsAt": "{n} at ≥ {fps} fps per camera", "health.retention": "Retention", "health.days": "{n} d",
  "health.unreachable": "Inference unreachable:", "health.sources": "Sources", "health.source": "Source", "health.fpsIn": "fps in",
  "health.lastFrame": "Last frame", "health.ago": "{s} s ago", "health.reconnects": "Reconnects", "health.lastError": "Last error",
  "health.pipeline": "Pipeline", "health.modelLine": "Model {v} · {p} · batch profile {b}",
  "set.title": "Settings", "set.sub": "Signed in as {role}. Camera passwords belong in the server environment, never in the URL shown here.",
  "set.sources": "Sources", "set.noSources": "No sources.", "set.id": "ID", "set.name": "Name", "set.type": "Type", "set.uri": "URI",
  "set.maxfps": "Max fps", "set.faceblur": "Face blur", "set.on": "on", "set.off": "off", "set.actions": "Actions",
  "set.enable": "Enable", "set.disable": "Disable", "set.remove": "Remove", "set.add": "Add source", "set.added": "Source {id} added.",
  "set.enabled": "{id} enabled.", "set.disabled": "{id} disabled.", "set.removed": "{id} removed.", "set.failed": "Failed: {m}",
  "set.recognize": "Recognize an image", "set.fileHint": "JPEG or PNG, max 10 MB", "set.upload": "Upload",
  "set.processing": "Processing…", "set.noResult": "no result after 30 s", "set.appearance": "Appearance",
  "set.theme.auto": "auto", "set.theme.light": "light", "set.theme.dark": "dark",
  "lists.title": "Lists", "lists.sub": "Whitelist, blocklist and unknown for plates and persons. Persons are records linked to plates; nobody is identified by face.",
  "lists.kind": "Kind", "lists.plates": "Plates", "lists.persons": "Persons", "lists.list": "List", "lists.search": "Search",
  "lists.searchPlate": "Search plate (Persian or Latin)", "lists.searchName": "Search name", "lists.bulk": "Bulk move",
  "lists.selected": "{n} selected — move to:", "lists.clear": "Clear", "lists.select": "Select {name}", "lists.person": "Person",
  "lists.effective": "Effective", "lists.lastSeen": "Last seen", "lists.never": "never", "lists.name": "Name", "lists.notes": "Notes",
  "lists.delete": "Delete", "lists.deleteName": "Delete {name}", "lists.empty": "Nothing on the {list}.", "lists.moved": "{name} moved to {list}.",
  "lists.movedN": "{n} moved to {list}.", "lists.deleted": "{name} deleted.", "lists.linkUpdated": "Person link updated.",
  "lists.unreg": "Seen in the last 7 days, not on any list", "lists.unregEmpty": "Every recently seen plate is on a list.",
  "lists.sightings": "Sightings", "lists.putOn": "Put on list", "lists.addedTo": "{name} added to {list}.",
  "lists.addPlate": "Add plate", "lists.addPerson": "Add person", "lists.plateInput": "Plate (Persian or Latin)", "lists.addTo": "Add to {list}",
  "lists.personFor": "Person for {plate}",
};

const DICTS: Record<Lang, Record<Key, string>> = { fa, en };

function initial(): Lang {
  try { const v = localStorage.getItem(KEY); if (v === "fa" || v === "en") return v; } catch { /* storage blocked */ }
  return "fa";                                     // Persian is the default
}

export function applyDocumentLang(lang: Lang) {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "fa" ? "rtl" : "ltr";
  document.title = lang === "fa" ? "EdgeTech · پلاک‌خوان" : "EdgeTech · Plate recognition";
}

type Ctx = { lang: Lang; setLang: (l: Lang) => void; t: (k: Key, vars?: Record<string, string | number>) => string;
  num: (n: number | string) => string; time: (iso: string) => string };
const I18n = createContext<Ctx | null>(null);

const FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹";
export const faDigits = (s: string) => s.replace(/[0-9]/g, (d) => FA_DIGITS[Number(d)]);

export function I18nProvider({ children, lang: forced }: { children: ReactNode; lang?: Lang }) {
  const [lang, setLangState] = useState<Lang>(forced ?? initial);
  useEffect(() => { applyDocumentLang(lang); }, [lang]);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try { localStorage.setItem(KEY, l); } catch { /* storage blocked */ }
  }, []);
  const value = useMemo<Ctx>(() => {
    const num = (n: number | string) => (lang === "fa" ? faDigits(String(n)) : String(n));
    return {
      lang, setLang, num,
      t: (k, vars) => {
        let s = DICTS[lang][k] ?? DICTS.en[k] ?? k;
        if (vars) for (const [name, v] of Object.entries(vars)) s = s.split(`{${name}}`).join(typeof v === "number" ? num(v) : v);
        return s;
      },
      time: (iso) => new Date(iso).toLocaleString(lang === "fa" ? "fa-IR" : undefined, { hour12: false }),
    };
  }, [lang, setLang]);
  return <I18n.Provider value={value}>{children}</I18n.Provider>;
}

export function useI18n(): Ctx {
  const c = useContext(I18n);
  if (!c) throw new Error("useI18n outside I18nProvider");
  return c;
}
