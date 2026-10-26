import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useAuth } from "../auth";
import { errorMessage } from "../errors";
import { LANGUAGES, type Language } from "../i18n";

export function SettingsPage() {
  const { t, i18n } = useTranslation();
  const { user, setLanguage } = useAuth();
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);

  async function onChange(lang: Language) {
    setStatus(null);
    try {
      await setLanguage(lang);
      setStatus({ ok: true, text: t("settings.language_saved", { lng: lang }) });
    } catch (err) {
      setStatus({ ok: false, text: errorMessage(t, err) });
    }
  }

  return (
    <section>
      <h1>{t("settings.title")}</h1>
      {user?.role === "admin" && (
        <nav className="card links">
          <Link to="/settings/cameras">{t("cameras.title")}</Link>
          <Link to="/settings/accounts">{t("accounts.title")}</Link>
          <Link to="/settings/diagnostics">{t("diagnostics.title")}</Link>
        </nav>
      )}
      <div className="card">
        {user && (
          <p>{t("settings.signed_in_as", { username: user.username, role: t(`role.${user.role}`) })}</p>
        )}
        <label>
          {t("settings.language")}
          <select value={i18n.resolvedLanguage} onChange={(e) => void onChange(e.target.value as Language)}>
            {LANGUAGES.map((l) => (
              <option key={l} value={l}>
                {t(`language.${l}`)}
              </option>
            ))}
          </select>
        </label>
        {status && (
          <p className={status.ok ? "ok" : "error"} role="status">
            {status.text}
          </p>
        )}
      </div>
    </section>
  );
}
