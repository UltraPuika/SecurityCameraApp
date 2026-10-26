import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "../../api";
import { DiagnosticsView } from "../../components/DiagnosticsView";
import { defaults, DynamicFields, splitValues, type Values } from "../../components/DynamicFields";
import { errorMessage } from "../../errors";
import { useAccounts, useCameras, useProviders } from "../../hooks";
import type { Account, Camera, CameraProviderSpec, Diagnostics, ProvidersResponse } from "../../types";

interface Meta {
  name: string;
  location: string;
  group: string;
  favourite: boolean;
  account_id: number | null;
}

function initialValues(spec: CameraProviderSpec | undefined, existing?: Camera, params?: URLSearchParams): Values {
  if (!spec) return {};
  const base = defaults(spec.fields);
  if (existing) return { ...base, ...(existing.config ?? {}) };
  for (const f of spec.fields) {
    const p = params?.get(f.name);
    if (p != null && !f.secret) base[f.name] = p;
  }
  return base;
}

export function CameraEditor() {
  const { t } = useTranslation();
  const { id } = useParams();
  const [params] = useSearchParams();
  const editing = id !== undefined && id !== "new";
  const { data: providers } = useProviders();
  const { data: accounts } = useAccounts();
  const { data: cameras } = useCameras();
  const existing = editing ? cameras?.find((c) => String(c.id) === id) : undefined;

  if (!providers || (editing && !existing)) return <p className="muted">{t("app.loading")}</p>;
  return (
    <CameraForm
      key={existing?.id ?? "new"}
      providers={providers}
      accounts={accounts ?? []}
      existing={existing}
      params={params}
    />
  );
}

function CameraForm({
  providers,
  accounts,
  existing,
  params,
}: {
  providers: ProvidersResponse;
  accounts: Account[];
  existing?: Camera;
  params: URLSearchParams;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const editing = existing !== undefined;
  const id = existing?.id;

  const [providerId, setProviderId] = useState(existing?.provider ?? params.get("provider") ?? "bitvision");
  const [meta, setMeta] = useState<Meta>(
    existing
      ? {
          name: existing.name,
          location: existing.location,
          group: existing.group,
          favourite: existing.favourite,
          account_id: existing.account_id,
        }
      : {
          name: params.get("name") ?? "",
          location: "",
          group: "",
          favourite: false,
          account_id: params.get("account") ? Number(params.get("account")) : null,
        },
  );
  const spec = providers.cameras.find((p) => p.id === providerId);
  const [values, setValues] = useState<Values>(() => initialValues(spec, existing, params));
  const [diag, setDiag] = useState<Diagnostics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"test" | "save" | "delete" | null>(null);

  function changeProvider(next: string) {
    setProviderId(next);
    setValues(initialValues(providers.cameras.find((p) => p.id === next)));
    setDiag(null);
  }

  const accountOptions = accounts.filter((a) => a.provider === spec?.account_provider);

  function body() {
    const { config, secrets } = splitValues(spec?.fields ?? [], values);
    return { ...meta, provider: providerId, config, secrets };
  }

  async function onTest() {
    setBusy("test");
    setError(null);
    setDiag(null);
    try {
      const b = { ...body(), camera_id: existing?.id ?? null };
      setDiag(await api<Diagnostics>("/api/cameras/test", { method: "POST", body: b }));
    } catch (err) {
      setError(errorMessage(t, err));
    } finally {
      setBusy(null);
    }
  }

  async function onSave(e: FormEvent) {
    e.preventDefault();
    setBusy("save");
    setError(null);
    try {
      await api(editing ? `/api/cameras/${id}` : "/api/cameras", { method: editing ? "PUT" : "POST", body: body() });
      navigate("/settings/cameras");
    } catch (err) {
      setError(errorMessage(t, err));
    } finally {
      setBusy(null);
    }
  }

  async function onDelete() {
    if (!existing || !window.confirm(t("cameras.confirm_delete", { name: existing.name }))) return;
    setBusy("delete");
    try {
      await api(`/api/cameras/${existing.id}`, { method: "DELETE" });
      navigate("/settings/cameras");
    } catch (err) {
      setError(errorMessage(t, err));
      setBusy(null);
    }
  }

  const tested = diag !== null;
  return (
    <section>
      <h1>{editing ? t("cameras.edit") : t("cameras.add")}</h1>
      <form className="card form" onSubmit={onSave} noValidate>
        <label>
          {t("camera.provider")}
          <select value={providerId} disabled={editing} onChange={(e) => changeProvider(e.target.value)}>
            {providers.cameras.map((p) => (
              <option key={p.id} value={p.id}>
                {t(`providers.${p.id}`, { defaultValue: p.id })}
              </option>
            ))}
          </select>
          <small>{t(`providers_help.${providerId}`, { defaultValue: "" })}</small>
        </label>
        <label>
          {t("camera.name")} *
          <input value={meta.name} maxLength={100} onChange={(e) => setMeta({ ...meta, name: e.target.value })} />
        </label>
        <label>
          {t("camera.location")}
          <input
            value={meta.location}
            maxLength={100}
            onChange={(e) => setMeta({ ...meta, location: e.target.value })}
          />
        </label>
        <label>
          {t("camera.group")}
          <input value={meta.group} maxLength={100} onChange={(e) => setMeta({ ...meta, group: e.target.value })} />
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={meta.favourite}
            onChange={(e) => setMeta({ ...meta, favourite: e.target.checked })}
          />
          {t("camera.favourite")}
        </label>
        {spec?.account_provider && (
          <label>
            {t("camera.account")} *
            <select
              value={meta.account_id ?? ""}
              onChange={(e) => setMeta({ ...meta, account_id: e.target.value ? Number(e.target.value) : null })}
            >
              <option value="">{t("form.choose")}</option>
              {accountOptions.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
            {accountOptions.length === 0 && <small>{t("accounts.none_yet")}</small>}
          </label>
        )}
        {spec && (
          <fieldset>
            <legend>{t("form.connection")}</legend>
            <DynamicFields
              fields={spec.fields}
              values={values}
              onChange={(v) => {
                setValues(v);
                setDiag(null);
              }}
              secretsSet={existing?.secrets_set}
            />
          </fieldset>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {diag && <DiagnosticsView result={diag} />}
        <div className="actions">
          <button type="button" className="secondary" disabled={busy !== null} onClick={() => void onTest()}>
            {busy === "test" ? t("form.testing") : t("form.test")}
          </button>
          <button type="submit" disabled={busy !== null || !tested || !meta.name}>
            {busy === "save" ? t("form.saving") : diag?.ok === false ? t("form.save_anyway") : t("form.save")}
          </button>
          {editing && (
            <button type="button" className="danger" disabled={busy !== null} onClick={() => void onDelete()}>
              {t("form.delete")}
            </button>
          )}
        </div>
        {!tested && <small className="muted">{t("form.test_first")}</small>}
      </form>
    </section>
  );
}
