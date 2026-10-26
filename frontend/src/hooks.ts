import { useCallback, useEffect, useState } from "react";

import { api } from "./api";
import type { Account, Camera, ProvidersResponse } from "./types";

export function useFetch<T>(path: string | null): {
  data: T | null;
  error: unknown;
  reload: () => void;
} {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (path === null) return;
    let alive = true;
    api<T>(path)
      .then((d) => {
        if (alive) {
          setData(d);
          setError(null);
        }
      })
      .catch((e: unknown) => {
        if (alive) setError(e);
      });
    return () => {
      alive = false;
    };
  }, [path, tick]);
  const reload = useCallback(() => setTick((x) => x + 1), []);
  return { data, error, reload };
}

export const useProviders = () => useFetch<ProvidersResponse>("/api/providers");
export const useCameras = () => useFetch<Camera[]>("/api/cameras");
export const useAccounts = (enabled = true) => useFetch<Account[]>(enabled ? "/api/accounts" : null);

export function formatDateTime(lang: string, iso: string | null): string {
  if (!iso) return "";
  return new Intl.DateTimeFormat(lang, { dateStyle: "short", timeStyle: "short" }).format(new Date(iso));
}
