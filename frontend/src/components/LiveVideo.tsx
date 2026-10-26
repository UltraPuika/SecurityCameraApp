import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { codeMessage } from "../errors";
import { MsePlayer, type PlayerState } from "../player/mse";
import { usePageVisible, useLatest } from "../visibility";

interface Props {
  cameraId: number;
  quality: "main" | "sub";
  active: boolean;
  className?: string;
  onState?: (state: PlayerState) => void;
}

export function LiveVideo({ cameraId, quality, active, className, onState }: Props) {
  const { t } = useTranslation();
  const videoRef = useRef<HTMLVideoElement>(null);
  const pageVisible = usePageVisible();
  const [state, setState] = useState<PlayerState>("stopped");
  const [error, setError] = useState<{ code: string; detail: Record<string, unknown> } | null>(null);
  const onStateRef = useLatest(onState);

  const running = active && pageVisible;

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !running) return;
    const player = new MsePlayer(video, cameraId, quality, (s, code, detail) => {
      setState(s);
      if (s === "error" && code) setError({ code, detail: detail ?? {} });
      else if (s === "playing") setError(null);
      onStateRef.current?.(s);
    });
    player.start();
    return () => player.stop();
  }, [cameraId, quality, running, onStateRef]);

  return (
    <div className={`live ${className ?? ""}`}>
      <video ref={videoRef} muted playsInline autoPlay disablePictureInPicture aria-label={t("live.video")} />
      {running && state !== "playing" && (
        <div className="live-overlay" role="status">
          <span>{t(`live.${state}`)}</span>
          {error && <small>{codeMessage(t, error.code, error.detail)}</small>}
        </div>
      )}
    </div>
  );
}
