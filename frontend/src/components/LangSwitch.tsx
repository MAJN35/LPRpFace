import { Languages } from "lucide-react";
import { Key, Lang, useI18n } from "../i18n";

// fa/en switch; stored like the theme (localStorage "lpr.lang"), applied to <html lang dir>. Compact (collapsed
// sidebar): one icon button that switches to the other language.
export function LangSwitch({ compact = false }: { compact?: boolean }) {
  const { lang, setLang, t } = useI18n();
  if (compact) {
    const other: Lang = lang === "fa" ? "en" : "fa";
    return (
      <button type="button" className="btn-x v-ghost icon-only has-tip" lang={other} data-tip={t(`lang.${other}` as Key)}
        aria-label={`${t("lang.label")}: ${t(`lang.${other}` as Key)}`} onClick={() => setLang(other)}>
        <span className="btn-icon" aria-hidden="true"><Languages size={18} /></span>
      </button>
    );
  }
  return (
    <div role="group" aria-label={t("lang.label")} className="row lang-switch">
      <Languages size={18} className="muted" aria-hidden="true" />
      {(["fa", "en"] as Lang[]).map((l) => (
        <button key={l} type="button" lang={l} aria-pressed={lang === l} onClick={() => setLang(l)}>{t(`lang.${l}` as Key)}</button>
      ))}
    </div>
  );
}
