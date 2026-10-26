import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { api } from "../../api";
import { StatusBadge } from "../../components/StatusBadge";
import { codeMessage, errorMessage } from "../../errors";
import { formatDateTime, useCameras } from "../../hooks";

export function CamerasAdminPage() {
  const { t, i18n } = useTranslation();
  const { data, error, reload } = useCameras();
  const [busy, setBusy] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function retest(id: number) {
    setBusy(id);
    setActionError(null);
    try {
      await api(`/api/cameras/${id}/test`, { method: "POST" });
      reload();
    } catch (err) {
      setActionError(errorMessage(t, err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section>
      <h1>{t("cameras.title")}</h1>
      <div className="toolbar">
        <Link className="button" to="/settings/cameras/new">
          {t("cameras.add")}
        </Link>
        <Link to="/settings/accounts">{t("accounts.title")}</Link>
      </div>
      {(error !== null || actionError) && (
        <p className="error" role="alert">
          {actionError ?? errorMessage(t, error)}
        </p>
      )}
      {data?.length === 0 && <p className="muted">{t("dashboard.empty_title")}</p>}
      <ul className="rows">
        {data?.map((c) => (
          <li key={c.id} className="row">
            <div className="row-main">
              <Link to={`/settings/cameras/${c.id}`}>{c.name}</Link>
              <span className="muted">
                {[t(`providers.${c.provider}`, { defaultValue: c.provider }), c.location].filter(Boolean).join(" · ")}
              </span>
              {c.status_code && <span className="muted">{codeMessage(t, c.status_code)}</span>}
              {c.last_checked_at && (
                <span className="muted">
                  {t("cameras.last_checked", { when: formatDateTime(i18n.language, c.last_checked_at) })}
                </span>
              )}
            </div>
            <StatusBadge status={c.status} />
            <button className="secondary" disabled={busy !== null} onClick={() => void retest(c.id)}>
              {busy === c.id ? t("form.testing") : t("form.test")}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
