import { useEffect, useRef, useState, type PointerEvent } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { LiveVideo } from "../components/LiveVideo";
import { StatusBadge } from "../components/StatusBadge";
import { codeMessage } from "../errors";
import { useCameras } from "../hooks";
import { useLatest } from "../visibility";
import { PROBLEM } from "./CamerasPage";

interface Zoom {
  scale: number;
  x: number;
  y: number;
}
const NO_ZOOM: Zoom = { scale: 1, x: 0, y: 0 };
const SWIPE_PX = 60;

export function CameraView() {
  const { t } = useTranslation();
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { data } = useCameras();
  const stageRef = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState<Zoom>(NO_ZOOM);
  const [wokenFor, setWokenFor] = useState<string | null>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const gesture = useRef<{ dist: number; scale: number; startX: number; startY: number; zoom: Zoom } | null>(null);

  const order: number[] =
    (location.state as { ids?: number[] } | null)?.ids ?? (data ?? []).map((c) => c.id);
  const cam = data?.find((c) => String(c.id) === id);
  const index = cam ? order.indexOf(cam.id) : -1;

  function go(delta: number) {
    if (index < 0 || order.length < 2) return;
    const next = order[(index + delta + order.length) % order.length];
    setZoom(NO_ZOOM);
    navigate(`/camera/${next}`, { replace: true, state: location.state });
  }

  function toggleFullscreen() {
    const el = stageRef.current;
    if (!el) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void el.requestFullscreen?.().catch(() => undefined);
  }

  const keyHandler = useLatest((e: KeyboardEvent) => {
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;
    if (e.key === "ArrowRight") go(1);
    else if (e.key === "ArrowLeft") go(-1);
    else if (e.key.toLowerCase() === "f") toggleFullscreen();
    // The browser consumes the first Esc to leave document full screen.
    else if (e.key === "Escape" && !document.fullscreenElement) navigate(-1);
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => keyHandler.current(e);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [keyHandler]);

  function onPointerDown(e: PointerEvent<HTMLDivElement>) {
    e.currentTarget.setPointerCapture(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const pts = [...pointers.current.values()];
    gesture.current = {
      dist: pts.length === 2 ? Math.hypot(pts[0]!.x - pts[1]!.x, pts[0]!.y - pts[1]!.y) : 0,
      scale: zoom.scale,
      startX: e.clientX,
      startY: e.clientY,
      zoom,
    };
  }

  function onPointerMove(e: PointerEvent<HTMLDivElement>) {
    if (!pointers.current.has(e.pointerId) || !gesture.current) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const pts = [...pointers.current.values()];
    const g = gesture.current;
    if (pts.length === 2 && g.dist > 0) {
      const dist = Math.hypot(pts[0]!.x - pts[1]!.x, pts[0]!.y - pts[1]!.y);
      setZoom((z) => ({ ...z, scale: Math.min(4, Math.max(1, (g.scale * dist) / g.dist)) }));
    } else if (pts.length === 1 && zoom.scale > 1) {
      setZoom({ ...g.zoom, x: g.zoom.x + e.clientX - g.startX, y: g.zoom.y + e.clientY - g.startY });
    }
  }

  function onPointerUp(e: PointerEvent<HTMLDivElement>) {
    const g = gesture.current;
    const single = pointers.current.size === 1;
    pointers.current.delete(e.pointerId);
    if (single && g && zoom.scale === 1) {
      const dx = e.clientX - g.startX;
      if (Math.abs(dx) > SWIPE_PX && Math.abs(dx) > Math.abs(e.clientY - g.startY)) go(dx < 0 ? 1 : -1);
    }
    if (zoom.scale <= 1.05) setZoom(NO_ZOOM);
    gesture.current = pointers.current.size ? { ...g!, zoom } : null;
  }

  if (!data) return <p className="muted">{t("app.loading")}</p>;
  if (!cam) return <p className="error">{t("errors.camera.not_found")}</p>;

  const problem = PROBLEM.has(cam.status);
  const needsWake = cam.capabilities.battery && wokenFor !== id;

  return (
    <section className="viewer">
      <header className="viewer-head">
        <button type="button" className="secondary" onClick={() => navigate(-1)} aria-label={t("viewer.back")}>
          ←
        </button>
        <h1>{cam.name}</h1>
        <StatusBadge status={cam.status} />
        <span className="muted">{t(`transport.${cam.transport}`)}</span>
        <span className="spacer" />
        <button type="button" className="secondary" onClick={() => go(-1)} aria-label={t("viewer.prev")}>
          ‹
        </button>
        <button type="button" className="secondary" onClick={() => go(1)} aria-label={t("viewer.next")}>
          ›
        </button>
        <button type="button" className="secondary" onClick={toggleFullscreen}>
          {t("viewer.fullscreen")}
        </button>
      </header>
      <div
        ref={stageRef}
        className="viewer-stage"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={() => setZoom(NO_ZOOM)}
      >
        {problem ? (
          <p className="viewer-msg">{cam.status_code ? codeMessage(t, cam.status_code) : t(`status.${cam.status}`)}</p>
        ) : needsWake ? (
          <div className="viewer-msg">
            <button type="button" onClick={() => setWokenFor(id ?? null)}>
              {t("live.wake")}
            </button>
            <small>{t("live.wake_hint")}</small>
          </div>
        ) : (
          <div
            className="viewer-zoom"
            style={{ transform: `translate(${zoom.x}px, ${zoom.y}px) scale(${zoom.scale})` }}
          >
            <LiveVideo key={cam.id} cameraId={cam.id} quality="main" active />
          </div>
        )}
      </div>
      <p className="muted viewer-hint">{t("viewer.hint")}</p>
    </section>
  );
}
