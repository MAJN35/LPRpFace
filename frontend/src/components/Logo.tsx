// EdgeTech brand (from the company logo: "Edge" in the text colour, "Tech" in brand blue, italic heavy) with the LPR
// mark: a licence plate inside a scan viewfinder, crossed by a scan line. The mark uses theme tokens, so it stays
// legible in light and dark mode; public/favicon.svg is the same mark on a fixed dark tile for browser tabs.
import { useI18n } from "../i18n";

export function LogoMark({ size = 36 }: { size?: number }) {
  return (
    <svg className="logo-mark" width={size} height={size} viewBox="0 0 48 48" aria-hidden="true" focusable="false">
      <path d="M5 14V9a4 4 0 0 1 4-4h5M34 5h5a4 4 0 0 1 4 4v5M43 34v5a4 4 0 0 1-4 4h-5M14 43H9a4 4 0 0 1-4-4v-5"
        fill="none" stroke="var(--brand)" strokeWidth="3.4" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="10" y="15.5" width="28" height="17" rx="3" fill="var(--plate-bg)" stroke="var(--text)" strokeWidth="2.2" />
      <path d="M13.1 16.6h3.6v14.8h-3.6a2 2 0 0 1-2-2V18.6a2 2 0 0 1 2-2z" fill="var(--plate-blue)" />
      <path d="M21.5 20v8M26.2 20v8M30.9 20v8" stroke="var(--plate-ink)" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M7.5 24h33" stroke="var(--brand)" strokeWidth="1.6" strokeLinecap="round" className="logo-scan" />
    </svg>
  );
}

export function Logo({ compact = false, size = 36 }: { compact?: boolean; size?: number }) {
  const { t } = useI18n();
  return (
    <span className="logo" aria-label={`EdgeTech · ${t("app.brand")}`} role="img">
      <LogoMark size={size} />
      {!compact && (
        <span className="logo-text" aria-hidden="true">
          <span className="logo-word" dir="ltr">Edge<span className="logo-tech">Tech</span></span>
          <span className="logo-sub">{t("app.brand")}</span>
        </span>
      )}
    </span>
  );
}
