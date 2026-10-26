import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { api } from "../../api";
import { DiagnosticsView } from "../../components/DiagnosticsView";
import { defaults, DynamicFields, splitValues, type Values } from "../../components/DynamicFields";
import { errorMessage } from "../../errors";
import { useAccounts, useProviders } from "../../hooks";
import type { Account, Diagnostics, ImouDevice } from "../../types";

function DeviceList({ account }: { account: Account }) {
  const { t } = useTranslation();
  const [devices, setDevices] = useState<ImouDevice[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      setDevices(await api<ImouDevice[]>(`/api/accounts/${account.id}/devices`));
    } catch (err) {
      setError(errorMessage(t, err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <button className="secondary" disabled={busy} onClick={() => void load()}>
        {busy ? t("app.loading") : t("accounts.show_devices")}
      </button>
      {error && <p className="error">{error}</p>}
      {devices?.length === 0 && <p className="muted">{t("accounts.no_devices")}</p>}
      {devices && devices.length > 0 && (
        <ul className="rows">
          {devices.map((d) => {
            const q = new URLSearchParams({
              provider: account.provider,
              account: String(account.id),
              device_id: d.device_id,
              channel_id: d.channel_id,
              name: d.name,
            });
            return (
              <li key={`${d.device_id}/${d.channel_id}`} className="row">
                <div className="row-main">
                  <span>{d.name || d.device_id}</span>
                  <span className="muted">{t("accounts.channel", { device: d.device_id, channel: d.channel_id })}</span>
                </div>
                {d.added ? (
                  <span className="muted">{t("accounts.already_added")}</span>
                ) : (
                  <Link className="button" to={`/settings/cameras/new?${q.toString()}`}>
                    {t("accounts.add_camera")}
                  </Link>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

export function AccountsPage() {
  const { t } = useTranslation();
  const { data: providers } = useProviders();
  const { data: accounts, error: loadError, reload } = useAccounts();
  const spec = providers?.accounts[0];
  const [name, setName] = useState("");
  const [values, setValues] = useState<Values | null>(null);
  const [diag, setDiag] = useState<Diagnostics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const vals = values ?? (spec ? defaults(spec.fields) : {});

  function body() {
    const { config, secrets } = splitValues(spec?.fields ?? [], vals);
    return { name, provider: spec?.id ?? "", config, secrets };
  }

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(errorMessage(t, err));
    } finally {
      setBusy(false);
    }
  }

  const onTest = () =>
    run(async () => setDiag(await api<Diagnostics>("/api/accounts/test", { method: "POST", body: body() })));

  const onSave = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      await api("/api/accounts", { method: "POST", body: body() });
      setName("");
      setValues(null);
      setDiag(null);
      reload();
    });
  };

  function onDelete(a: Account) {
    if (!window.confirm(t("accounts.confirm_delete", { name: a.name }))) return;
    void run(async () => {
      await api(`/api/accounts/${a.id}`, { method: "DELETE" });
      reload();
    });
  }

  return (
    <section>
      <h1>{t("accounts.title")}</h1>
      <p className="muted">{t("accounts.intro")}</p>
      {loadError !== null && <p className="error">{errorMessage(t, loadError)}</p>}
      <ul className="rows">
        {accounts?.map((a) => (
          <li key={a.id} className="row row-block">
            <div className="row-main">
              <strong>{a.name}</strong>
              <span className="muted">
                {t(`providers.${a.provider}`, { defaultValue: a.provider })} ·{" "}
                {t(`options.data_center.${String(a.config.data_center)}`, { defaultValue: String(a.config.data_center) })}
              </span>
            </div>
            <DeviceList account={a} />
            <button className="danger" disabled={busy} onClick={() => onDelete(a)}>
              {t("form.delete")}
            </button>
          </li>
        ))}
      </ul>
      {spec && (
        <form className="card form" onSubmit={onSave} noValidate>
          <h2>{t("accounts.add")}</h2>
          <label>
            {t("camera.name")} *
            <input value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
          </label>
          <DynamicFields
            fields={spec.fields}
            values={vals}
            onChange={(v) => {
              setValues(v);
              setDiag(null);
            }}
          />
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {diag && <DiagnosticsView result={diag} />}
          <div className="actions">
            <button type="button" className="secondary" disabled={busy} onClick={() => void onTest()}>
              {t("form.test")}
            </button>
            <button type="submit" disabled={busy || !name || !diag?.ok}>
              {t("form.save")}
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
