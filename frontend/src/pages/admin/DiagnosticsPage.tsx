import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { StatusBadge } from "../../components/StatusBadge";
import { codeMessage, errorMessage } from "../../errors";
import { formatDateTime, useFetch } from "../../hooks";
import type { CameraStatus } from "../../types";

interface DiagResponse {
  backend: string;
  db: string;
  go2rtc: string;
  streams: {
    max: number;
    idle_seconds: number;
    active: { camera_id: number; quality: string; viewers: number; transport: string }[];
  };
  cameras: {
    id: number;
    name: string;
    provider: string;
    status: CameraStatus;
    status_code: string | null;
    verified: boolean;
    last_checked_at: string | null;
  }[];
  system: { cpu_percent: number | null; mem_total: number | null; mem_used: number | null; load: number[] | null } | null;
  logs: { time: string; level: string; logger: string; message: string }[];
}

const MB = 1024 * 1024;

export function DiagnosticsPage() {
  const { t, i18n } = useTranslation();
  const { data, error, reload } = useFetch<DiagResponse>("/api/diagnostics");

  useEffect(() => {
    const timer = window.setInterval(reload, 10000);
    return () => window.clearInterval(timer);
  }, [reload]);

  const fmt = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 });
  const health = (v: string) => <span className={v === "ok" ? "ok" : "error"}>{t(`diagnostics.health_${v}`)}</span>;

  return (
    <section>
      <h1>{t("diagnostics.title")}</h1>
      {error !== null && <p className="error">{errorMessage(t, error)}</p>}
      {data && (
        <>
          <div className="card diag-grid">
            <span>{t("diagnostics.backend")}</span>
            {health(data.backend)}
            <span>{t("diagnostics.db")}</span>
            {health(data.db)}
            <span>{t("diagnostics.go2rtc")}</span>
            {health(data.go2rtc)}
            <span>{t("diagnostics.streams")}</span>
            <span>
              {t("diagnostics.streams_value", { active: data.streams.active.length, max: data.streams.max })}
            </span>
            <span>{t("diagnostics.cpu")}</span>
            <span>
              {data.system?.cpu_percent != null ? `${fmt.format(data.system.cpu_percent)} %` : t("diagnostics.na")}
            </span>
            <span>{t("diagnostics.ram")}</span>
            <span>
              {data.system?.mem_used != null && data.system.mem_total
                ? `${fmt.format(data.system.mem_used / MB)} / ${fmt.format(data.system.mem_total / MB)} MB`
                : t("diagnostics.na")}
            </span>
          </div>

          <h2>{t("diagnostics.cameras")}</h2>
          <ul className="rows">
            {data.cameras.map((c) => (
              <li key={c.id} className="row">
                <div className="row-main">
                  <strong>{c.name}</strong>
                  <span className="muted">
                    {t(`providers.${c.provider}`, { defaultValue: c.provider })}
                    {c.verified ? ` · ${t("diagnostics.verified")}` : ` · ${t("diagnostics.unverified")}`}
                    {c.last_checked_at ? ` · ${formatDateTime(i18n.language, c.last_checked_at)}` : ""}
                  </span>
                  {c.status_code && <span className="error">{codeMessage(t, c.status_code)}</span>}
                </div>
                <StatusBadge status={c.status} />
              </li>
            ))}
          </ul>

          <h2>{t("diagnostics.logs")}</h2>
          <pre className="logs">
            {data.logs
              .slice()
              .reverse()
              .map((l) => `${formatDateTime(i18n.language, l.time)} ${l.level} ${l.logger}: ${l.message}`)
              .join("\n")}
          </pre>
        </>
      )}
    </section>
  );
}
