import { useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../auth";
import { LiveVideo } from "../components/LiveVideo";
import { StatusBadge } from "../components/StatusBadge";
import { codeMessage, errorMessage } from "../errors";
import { formatDateTime, useCameras } from "../hooks";
import type { Camera } from "../types";
import { useInView } from "../visibility";

export type View = "all" | "favourites" | "locations" | "offline";

const TITLES: Record<View, string> = {
  all: "nav.all",
  favourites: "nav.favourites",
  locations: "nav.locations",
  offline: "nav.offline",
};

export const PROBLEM = new Set(["needs_setup", "unsupported", "quota"]);
const LAYOUTS = [1, 4, 9, 16] as const;
type Layout = (typeof LAYOUTS)[number];
const LAYOUT_KEY = "camdash.layout";

function storedLayout(): Layout {
  const v = Number(localStorage.getItem(LAYOUT_KEY));
  return (LAYOUTS as readonly number[]).includes(v) ? (v as Layout) : 4;
}

/** Battery cameras and cameras with setup problems never start streaming by themselves. */
export function autoPlays(cam: Camera): boolean {
  return !PROBLEM.has(cam.status) && !cam.capabilities.battery;
}

function CameraTile({ cam, admin, onOpen }: { cam: Camera; admin: boolean; onOpen: () => void }) {
  const { t, i18n } = useTranslation();
  const ref = useRef<HTMLElement>(null);
  const inView = useInView(ref);
  const [woken, setWoken] = useState(false);
  const [live, setLive] = useState(false);
  const probe = cam.probe.sub_probe ?? cam.probe.main_probe;
  const problem = PROBLEM.has(cam.status);
  const play = !problem && inView && (autoPlays(cam) || woken);

  return (
    <article
      ref={ref}
      className={`tile tile-${cam.status}${live ? " tile-live" : ""}`}
      tabIndex={0}
      data-camera-id={cam.id}
      aria-label={cam.name}
      onDoubleClick={onOpen}
    >
      <div className="tile-media">
        {play ? (
          <LiveVideo cameraId={cam.id} quality="sub" active onState={(s) => setLive(s === "playing")} />
        ) : problem ? (
          <div className="tile-placeholder">
            <p>{cam.status_code ? codeMessage(t, cam.status_code) : t(`status.${cam.status}`)}</p>
            {admin && (
              <Link className="tile-fix" to={`/settings/cameras/${cam.id}`}>
                {t("camera.fix")}
              </Link>
            )}
          </div>
        ) : cam.capabilities.battery ? (
          <div className="tile-placeholder">
            <button type="button" onClick={() => setWoken(true)}>
              {t("live.wake")}
            </button>
            <small>{t("live.wake_hint")}</small>
          </div>
        ) : (
          <div className="tile-placeholder" />
        )}
      </div>
      <header>
        <h3>
          <button type="button" className="link-button tile-open" onClick={onOpen}>
            {cam.name}
          </button>
        </h3>
        {live ? <span className="badge badge-live">{t("live.live")}</span> : <StatusBadge status={cam.status} />}
      </header>
      <p className="tile-meta">
        {[
          cam.location,
          t(`transport.${cam.transport}`),
          probe?.codec ? `${probe.codec}${probe.width ? ` ${probe.width}×${probe.height}` : ""}` : "",
          `${t("camera.last_seen")}: ${cam.last_seen_at ? formatDateTime(i18n.language, cam.last_seen_at) : t("camera.never")}`,
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
    </article>
  );
}

export function CamerasPage({ view }: { view: View }) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const { data, error } = useCameras();
  const [query, setQuery] = useState("");
  const [location, setLocation] = useState("");
  const [provider, setProvider] = useState("");
  const [status, setStatus] = useState("");

  const cams = useMemo(() => {
    const q = query.trim().toLocaleLowerCase();
    return (data ?? []).filter(
      (c) =>
        (view !== "favourites" || c.favourite) &&
        (view !== "offline" || c.status === "offline") &&
        (!q || `${c.name} ${c.location} ${c.group}`.toLocaleLowerCase().includes(q)) &&
        (!location || c.location === location) &&
        (!provider || c.provider === provider) &&
        (!status || c.status === status),
    );
  }, [data, view, query, location, provider, status]);

  const locations = [...new Set((data ?? []).map((c) => c.location).filter(Boolean))].sort();
  const providers = [...new Set((data ?? []).map((c) => c.provider))].sort();
  const statuses = [...new Set((data ?? []).map((c) => c.status))].sort();
  const admin = user?.role === "admin";
  const navigate = useNavigate();
  const [layout, setLayoutState] = useState<Layout>(storedLayout);
  const [page, setPage] = useState(0);
  const columns = Math.sqrt(layout);

  function setLayout(l: Layout) {
    localStorage.setItem(LAYOUT_KEY, String(l));
    setLayoutState(l);
    setPage(0);
  }

  const pages = Math.max(1, Math.ceil(cams.length / layout));
  const current = Math.min(page, pages - 1);
  const visible = view === "locations" ? cams : cams.slice(current * layout, (current + 1) * layout);

  const groups: [string, Camera[]][] =
    view === "locations"
      ? Object.entries(
          visible.reduce<Record<string, Camera[]>>((acc, c) => {
            (acc[c.location || ""] ??= []).push(c);
            return acc;
          }, {}),
        ).sort(([a], [b]) => a.localeCompare(b))
      : [["", visible]];

  const open = (c: Camera) => navigate(`/camera/${c.id}`, { state: { ids: cams.map((x) => x.id) } });

  function onGridKey(e: KeyboardEvent<HTMLDivElement>) {
    const tiles = Array.from(e.currentTarget.querySelectorAll<HTMLElement>("[data-camera-id]"));
    const i = tiles.indexOf(document.activeElement as HTMLElement);
    if (i < 0) return;
    const step = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: columns, ArrowUp: -columns }[e.key];
    if (step !== undefined) {
      e.preventDefault();
      tiles[Math.max(0, Math.min(tiles.length - 1, i + step))]?.focus();
    } else if (e.key === "Enter" || e.key.toLowerCase() === "f") {
      e.preventDefault();
      const cam = visible.find((c) => String(c.id) === tiles[i]?.dataset.cameraId);
      if (cam) open(cam);
    }
  }

  return (
    <section>
      <div className="page-head">
        <h1>{t(TITLES[view])}</h1>
        {cams.length > 0 && view !== "locations" && (
          <div className="layout-switch" role="group" aria-label={t("grid.layout")}>
            {LAYOUTS.map((l) => (
              <button
                key={l}
                type="button"
                className={l === layout ? "" : "secondary"}
                aria-pressed={l === layout}
                onClick={() => setLayout(l)}
              >
                {l}
              </button>
            ))}
          </div>
        )}
      </div>
      {data && data.length > 0 && (
        <div className="filters">
          <input
            type="search"
            aria-label={t("filters.search")}
            placeholder={t("filters.search")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select aria-label={t("filters.location")} value={location} onChange={(e) => setLocation(e.target.value)}>
            <option value="">{t("filters.all_locations")}</option>
            {locations.map((l) => (
              <option key={l}>{l}</option>
            ))}
          </select>
          <select aria-label={t("filters.provider")} value={provider} onChange={(e) => setProvider(e.target.value)}>
            <option value="">{t("filters.all_providers")}</option>
            {providers.map((p) => (
              <option key={p} value={p}>
                {t(`providers.${p}`, { defaultValue: p })}
              </option>
            ))}
          </select>
          <select aria-label={t("filters.status")} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("filters.all_statuses")}</option>
            {statuses.map((s) => (
              <option key={s} value={s}>
                {t(`status.${s}`)}
              </option>
            ))}
          </select>
        </div>
      )}
      {error !== null && <p className="error">{errorMessage(t, error)}</p>}
      {data && cams.length === 0 && (
        <div className="empty">
          <h2>{data.length === 0 ? t("dashboard.empty_title") : t("dashboard.no_match")}</h2>
          {data.length === 0 && <p>{t("dashboard.empty_body")}</p>}
          {data.length === 0 && admin && <Link to="/settings/cameras/new">{t("cameras.add")}</Link>}
        </div>
      )}
      {groups.map(([loc, list]) => (
        <div key={loc}>
          {view === "locations" && <h2>{loc || t("camera.no_location")}</h2>}
          <div
            className="grid"
            style={view === "locations" ? undefined : { ["--cols" as string]: columns }}
            onKeyDown={onGridKey}
          >
            {list.map((c) => (
              <CameraTile key={c.id} cam={c} admin={admin} onOpen={() => open(c)} />
            ))}
          </div>
        </div>
      ))}
      {view !== "locations" && pages > 1 && (
        <nav className="pager" aria-label={t("grid.pages")}>
          <button type="button" className="secondary" disabled={current === 0} onClick={() => setPage(current - 1)}>
            {t("grid.prev")}
          </button>
          <span>{t("grid.page", { page: current + 1, pages })}</span>
          <button
            type="button"
            className="secondary"
            disabled={current >= pages - 1}
            onClick={() => setPage(current + 1)}
          >
            {t("grid.next")}
          </button>
        </nav>
      )}
    </section>
  );
}
