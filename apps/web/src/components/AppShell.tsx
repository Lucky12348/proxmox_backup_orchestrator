import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import type { Language, TranslationDictionary } from "../i18n";

interface AppShellProps {
  children: ReactNode;
  language: Language;
  onLanguageChange: (language: Language) => void;
  t: TranslationDictionary;
}

const NAV_ITEMS = [
  { to: "/", key: "dashboard" },
  { to: "/assets", key: "assets" },
  { to: "/disks", key: "disks" },
  { to: "/planning", key: "planning" },
  { to: "/integrations", key: "integrations" },
  { to: "/activity", key: "activity" },
  { to: "/settings", key: "settings" },
] as const;

export function AppShell({ children, language, onLanguageChange, t }: AppShellProps) {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <p className="sidebar-kicker">PBO</p>
          <h1>{t.title}</h1>
          <p>{t.appTagline}</p>
        </div>

        <nav className="sidebar-nav" aria-label={t.navigation}>
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              className={({ isActive }) =>
                isActive ? "nav-link nav-link-active" : "nav-link"
              }
              end={item.to === "/"}
              to={item.to}
            >
              {t.nav[item.key]}
            </NavLink>
          ))}
        </nav>
      </aside>

      <div className="shell-main">
        <header className="topbar">
          <div>
            <p className="topbar-label">{t.navigation}</p>
            <p className="topbar-title">{t.adminConsole}</p>
          </div>

          <label className="language-select">
            <span>{t.language}</span>
            <select
              aria-label={t.language}
              onChange={(event) => onLanguageChange(event.target.value as Language)}
              value={language}
            >
              <option value="fr">FR</option>
              <option value="en">EN</option>
            </select>
          </label>
        </header>

        <main className="page-container">{children}</main>
      </div>
    </div>
  );
}
