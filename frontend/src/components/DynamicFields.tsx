import { useTranslation } from "react-i18next";

import type { FieldSpec, FieldValue } from "../types";

export type Values = Record<string, FieldValue>;

export function defaults(fields: FieldSpec[]): Values {
  return Object.fromEntries(fields.map((f) => [f.name, f.secret ? "" : f.default]));
}

interface Props {
  fields: FieldSpec[];
  values: Values;
  onChange: (values: Values) => void;
  secretsSet?: string[];
}

/** Renders provider-defined fields; a new provider needs no changes here. */
export function DynamicFields({ fields, values, onChange, secretsSet = [] }: Props) {
  const { t } = useTranslation();
  const set = (name: string, v: FieldValue) => onChange({ ...values, [name]: v });

  return (
    <>
      {fields.map((f) => {
        const label = t(`fields.${f.name}`, { defaultValue: f.name });
        const help = t(`fields_help.${f.name}`, { defaultValue: "" });
        const stored = f.secret && secretsSet.includes(f.name);
        const v = values[f.name];
        if (f.kind === "checkbox") {
          return (
            <label key={f.name} className="check">
              <input type="checkbox" checked={Boolean(v)} onChange={(e) => set(f.name, e.target.checked)} />
              {label}
              {help && <small>{help}</small>}
            </label>
          );
        }
        return (
          <label key={f.name}>
            {label}
            {f.required && !stored && " *"}
            {f.kind === "select" ? (
              <select value={String(v ?? "")} onChange={(e) => set(f.name, e.target.value)}>
                {f.options.map((o) => (
                  <option key={o} value={o}>
                    {t(`options.${f.name}.${o}`, { defaultValue: o })}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type={f.kind === "password" ? "password" : f.kind === "number" ? "number" : "text"}
                inputMode={f.kind === "number" ? "numeric" : undefined}
                min={f.min ?? undefined}
                max={f.max ?? undefined}
                autoComplete={f.secret ? "new-password" : "off"}
                autoCapitalize="none"
                spellCheck={false}
                placeholder={stored ? t("form.secret_stored") : undefined}
                value={v === null || v === undefined ? "" : String(v)}
                onChange={(e) =>
                  set(f.name, f.kind === "number" ? (e.target.value === "" ? null : Number(e.target.value)) : e.target.value)
                }
              />
            )}
            {help && <small>{help}</small>}
          </label>
        );
      })}
    </>
  );
}

export function splitValues(fields: FieldSpec[], values: Values): { config: Values; secrets: Values } {
  const config: Values = {};
  const secrets: Values = {};
  for (const f of fields) (f.secret ? secrets : config)[f.name] = values[f.name] ?? null;
  return { config, secrets };
}
