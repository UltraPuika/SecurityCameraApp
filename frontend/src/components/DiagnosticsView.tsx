import { useTranslation } from "react-i18next";

import { codeMessage } from "../errors";
import type { Diagnostics } from "../types";

const ICON = { pass: "✓", fail: "✗", skip: "–" } as const;

function facts(t: ReturnType<typeof useTranslation>["t"], d: Record<string, unknown>): string[] {
  const out: string[] = [];
  if (d.ip) out.push(t("diag.fact_ip", { ip: d.ip }));
  if (d.port) out.push(t("diag.fact_port", { port: d.port }));
  if (d.method) out.push(t(`diag.method_${String(d.method)}`));
  if (d.codec) out.push(String(d.codec));
  if (d.width && d.height) out.push(`${String(d.width)}×${String(d.height)}`);
  if (d.fps) out.push(t("diag.fact_fps", { fps: d.fps }));
  if (d.state) out.push(t(`status.${String(d.state)}`));
  if (typeof d.channels === "number") out.push(t("diag.fact_channels", { count: d.channels }));
  if (typeof d.profiles === "number") out.push(t("diag.fact_profiles", { count: d.profiles }));
  if (d.cloud) out.push(t("transport.cloud"));
  return out;
}

export function DiagnosticsView({ result }: { result: Diagnostics }) {
  const { t } = useTranslation();
  return (
    <div className={`diag ${result.ok ? "diag-ok" : "diag-fail"}`} role="status">
      <strong>{result.ok ? t("diag.ok") : t("diag.failed")}</strong>
      <ol>
        {result.steps.map((s, i) => {
          const warnings = Array.isArray(s.detail.warnings) ? (s.detail.warnings as string[]) : [];
          return (
            <li key={i} className={`step step-${s.status}`}>
              <span className="step-icon" aria-hidden="true">
                {ICON[s.status]}
              </span>
              <span className="step-name">{t(`diag.step_${s.name}`, { defaultValue: s.name })}</span>
              <span className="visually-hidden">{t(`diag.status_${s.status}`)}</span>
              <span className="step-facts">{facts(t, s.detail).join(" · ")}</span>
              {s.code && <span className="step-msg">{codeMessage(t, s.code, s.detail)}</span>}
              {warnings.map((w) => (
                <span key={w} className="step-warn">
                  {codeMessage(t, w)}
                </span>
              ))}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
