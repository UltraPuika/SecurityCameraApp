import { useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth";

const NAV = [
  { to: "/", key: "nav.all", end: true },
  { to: "/favourites", key: "nav.favourites" },
  { to: "/locations", key: "nav.locations" },
  { to: "/offline", key: "nav.offline" },
  { to: "/settings", key: "nav.settings" },
] as const;

export function Layout() {
  const { t } = useTranslation();
  const { logout } = useAuth();
  const [open, setOpen] = useState(false);

  return (
    <div className="shell">
      <header className="topbar">
        <button
          className="icon-button"
          aria-label={t("nav.menu")}
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          ☰
        </button>
        <span className="brand">{t("app.name")}</span>
      </header>
      <nav className={`sidebar${open ? " open" : ""}`}>
        <span className="brand">{t("app.name")}</span>
        <ul>
          {NAV.map((item) => (
            <li key={item.to}>
              <NavLink to={item.to} end={"end" in item} onClick={() => setOpen(false)}>
                {t(item.key)}
              </NavLink>
            </li>
          ))}
        </ul>
        <button className="link-button" onClick={() => void logout()}>
          {t("nav.logout")}
        </button>
      </nav>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
