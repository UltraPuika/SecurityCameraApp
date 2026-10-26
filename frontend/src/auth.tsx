import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, ApiError, setCsrfToken } from "./api";
import i18n, { type Language } from "./i18n";

export interface Me {
  username: string;
  role: "admin" | "viewer";
  language: Language | null;
  csrf_token: string;
}

interface AuthState {
  user: Me | null;
  loading: boolean;
  login(username: string, password: string): Promise<void>;
  logout(): Promise<void>;
  setLanguage(lang: Language): Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

function apply(me: Me | null): void {
  setCsrfToken(me?.csrf_token ?? null);
  if (me?.language) void i18n.changeLanguage(me.language);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api<Me>("/api/auth/me")
      .then((me) => {
        apply(me);
        setUser(me);
      })
      .catch((err: unknown) => {
        if (!(err instanceof ApiError) || err.status !== 401) console.warn("session check failed");
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const me = await api<Me>("/api/auth/login", { method: "POST", body: { username, password } });
    apply(me);
    setUser(me);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } finally {
      apply(null);
      setUser(null);
    }
  }, []);

  const setLanguage = useCallback(async (lang: Language) => {
    await i18n.changeLanguage(lang);
    const me = await api<Me>("/api/me/preferences", { method: "PUT", body: { language: lang } });
    apply(me);
    setUser(me);
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, logout, setLanguage }),
    [user, loading, login, logout, setLanguage],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
