import type { TFunction } from "i18next";

import { ApiError } from "./api";

/** Translates a backend code (e.g. "net.tcp_refused"); falls back per prefix, then generic. */
export function codeMessage(t: TFunction, code: string, detail: Record<string, unknown> = {}): string {
  const prefix = code.split(".")[0];
  const vars = { ...detail, code };
  return t(`errors.${code}`, {
    ...vars,
    defaultValue: t(`errors.${prefix}.generic`, { ...vars, defaultValue: t("errors.unknown_code", vars) }),
  });
}

export function errorMessage(t: TFunction, err: unknown): string {
  if (err instanceof ApiError) {
    return codeMessage(t, err.code, { seconds: err.retryAfter ?? 0, ...err.detail });
  }
  return t("errors.unknown");
}
