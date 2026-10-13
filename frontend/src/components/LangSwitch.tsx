import { Key, Lang, useI18n } from "../i18n";

// fa/en switch; stored like the theme (localStorage "lpr.lang"), applied to <html lang dir>.
export function LangSwitch() {
  const { lang, setLang, t } = useI18n();
  return (
    <div role="group" aria-label={t("lang.label")} className="row lang-switch">
      {(["fa", "en"] as Lang[]).map((l) => (
        <button key={l} type="button" lang={l} aria-pressed={lang === l} onClick={() => setLang(l)}>{t(`lang.${l}` as Key)}</button>
      ))}
    </div>
  );
}
