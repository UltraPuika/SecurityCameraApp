import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../auth";
import { errorMessage } from "../errors";

export function LoginPage() {
  const { t } = useTranslation();
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
    } catch (err) {
      setError(errorMessage(t, err));
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <form className="card login-card" onSubmit={onSubmit} noValidate>
        <h1>{t("app.name")}</h1>
        <h2>{t("login.title")}</h2>
        <label>
          {t("login.username")}
          <input
            autoComplete="username"
            autoCapitalize="none"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </label>
        <label>
          {t("login.password")}
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={busy || !username || !password}>
          {busy ? t("login.submitting") : t("login.submit")}
        </button>
      </form>
    </main>
  );
}
