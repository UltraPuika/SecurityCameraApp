import { useTranslation } from "react-i18next";

import type { CameraStatus } from "../types";

export function StatusBadge({ status }: { status: CameraStatus }) {
  const { t } = useTranslation();
  return <span className={`badge badge-${status}`}>{t(`status.${status}`)}</span>;
}
