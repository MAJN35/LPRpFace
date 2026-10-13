// Plate part of the search form: plate type, free zone, the editable plate and the match mode, plus help.
import { useId, useState } from "react";
import { Key, useI18n } from "../i18n";
import { ZONES } from "./charset";
import { FORMATS, Match, PlateFormat, SlotValues, emptySlots, formatById } from "./formats";
import { PlateEditor } from "./PlateEditor";

export type PlateDraft = { type: PlateFormat["id"]; values: SlotValues; match: Match; zone: string };
export const emptyDraft = (type: PlateFormat["id"] = "standard"): PlateDraft =>
  ({ type, values: emptySlots(formatById(type)), match: "partial", zone: "" });

export function PlateSearch({ draft, onChange, error, onError }: {
  draft: PlateDraft; onChange: (d: PlateDraft) => void; error: string | null; onError: (m: string | null) => void;
}) {
  const { t } = useI18n();
  const id = useId();
  const [help, setHelp] = useState(false);
  const f = formatById(draft.type);
  const typeName = t(`plate.${f.id}` as Key);
  return (
    <div className="plate-search">
      <div className="row plate-search-top">
        <label>{t("plate.type")}
          <select className="inset" value={f.id} onChange={(e) => { onError(null); onChange(emptyDraft(e.target.value as PlateFormat["id"])); }}>
            {FORMATS.map((x) => <option key={x.id} value={x.id}>{t(`plate.${x.id}` as Key)}</option>)}
          </select>
        </label>
        {f.zone && (
          <label>{t("plate.zone")}
            <select className="inset" value={draft.zone} onChange={(e) => onChange({ ...draft, zone: e.target.value })}>
              <option value="">{t("plate.anyZone")}</option>
              {ZONES.map((z) => <option key={z.code} value={z.code}>{z.fa} · {z.code}</option>)}
            </select>
          </label>
        )}
        <div role="radiogroup" aria-label={t("plate.mode")} className="row seg">
          {(["partial", "exact"] as Match[]).map((m) => (
            <button key={m} type="button" role="radio" aria-checked={draft.match === m} className={draft.match === m ? "inset" : ""}
              onClick={() => { onError(null); onChange({ ...draft, match: m }); }}>{t(m === "exact" ? "plate.exact" : "plate.partial")}</button>
          ))}
        </div>
      </div>
      <PlateEditor format={f} values={draft.values} zone={draft.zone} label={t("plate.preview", { type: typeName })}
        onChange={(values) => onChange({ ...draft, values })} onError={onError} />
      {error ? <p className="plate-msg" role="alert">{error}</p> : <p className="plate-msg" aria-hidden="true" />}
      {!f.verified && <p className="muted plate-note">{t("plate.approx")}</p>}
      <button type="button" className="link-btn" aria-expanded={help} aria-controls={`${id}-help`} onClick={() => setHelp(!help)}>
        {t("plate.help.title")}</button>
      {help && (
        <ul id={`${id}-help`} className="plate-help muted">
          {(["plate.help.1", "plate.help.2", "plate.help.3", "plate.help.4"] as Key[]).map((k) => <li key={k}>{t(k)}</li>)}
        </ul>
      )}
    </div>
  );
}
