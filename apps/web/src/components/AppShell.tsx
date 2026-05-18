import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useAuth } from "../AuthContext";
import type { Language, TranslationDictionary } from "../i18n";

interface AppShellProps {
  children: ReactNode;
  language: Language;
  onLanguageChange: (language: Language) => void;
  t: TranslationDictionary;
}

const NAV_ITEMS = [
  {
    to: "/",
    key: "dashboard" as const,
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="1" y="1" width="6" height="6" rx="1.5"/>
        <rect x="9" y="1" width="6" height="6" rx="1.5"/>
        <rect x="1" y="9" width="6" height="6" rx="1.5"/>
        <rect x="9" y="9" width="6" height="6" rx="1.5"/>
      </svg>
    ),
  },
  {
    to: "/assets",
    key: "assets" as const,
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="1" y="3" width="14" height="10" rx="2"/>
        <path d="M5 3V2M11 3V2"/>
        <path d="M1 7h14"/>
      </svg>
    ),
  },
  {
    to: "/disks",
    key: "disks" as const,
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <ellipse cx="8" cy="5" rx="7" ry="3"/>
        <path d="M1 5v3c0 1.657 3.134 3 7 3s7-1.343 7-3V5"/>
        <path d="M1 8v3c0 1.657 3.134 3 7 3s7-1.343 7-3V8"/>
        <circle cx="11" cy="5" r="0.75" fill="currentColor" stroke="none"/>
      </svg>
    ),
  },
  {
    to: "/planning",
    key: "planning" as const,
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M2 12L6 7l3 3 5-7"/>
        <circle cx="6" cy="7" r="1.2" fill="currentColor" stroke="none"/>
        <circle cx="9" cy="10" r="1.2" fill="currentColor" stroke="none"/>
      </svg>
    ),
  },
  {
    to: "/integrations",
    key: "integrations" as const,
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="3" cy="8" r="2"/>
        <circle cx="13" cy="4" r="2"/>
        <circle cx="13" cy="12" r="2"/>
        <path d="M5 7.5L11 4.5M5 8.5L11 11.5"/>
      </svg>
    ),
  },
  {
    to: "/activity",
    key: "activity" as const,
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="1,9 4,6 7,11 10,4 13,7 15,5"/>
      </svg>
    ),
  },
  {
    to: "/settings",
    key: "settings" as const,
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="8" cy="8" r="2.5"/>
        <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.41 1.41M11.54 11.54l1.41 1.41M3.05 12.95l1.41-1.41M11.54 4.46l1.41-1.41"/>
      </svg>
    ),
  },
] as const;

export function AppShell({ children, language, onLanguageChange, t }: AppShellProps) {
  const { logout } = useAuth();

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
              <span className="nav-icon">{item.icon}</span>
              {t.nav[item.key]}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px" }}>
            <div style={{
              width: 28, height: 28, borderRadius: "50%",
              background: "var(--ac-d)", border: "1px solid rgba(88,166,255,.3)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 11, fontWeight: 600, color: "var(--ac)", flexShrink: 0
            }}>A</div>
            <div>
              <div style={{ fontSize: 12, fontWeight: 500, color: "var(--t1)" }}>admin</div>
              <div style={{ fontSize: 11, color: "var(--t3)" }}>Local</div>
            </div>
            <button
              aria-label={language === "fr" ? "Déconnexion" : "Log out"}
              className="icon-button"
              onClick={logout}
              title={language === "fr" ? "Déconnexion" : "Log out"}
              type="button"
              style={{ width: 28, height: 28 }}
            >
              <svg
                aria-hidden="true"
                fill="none"
                height="15"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="1.7"
                viewBox="0 0 16 16"
                width="15"
              >
                <path d="M6 14H3.5A1.5 1.5 0 0 1 2 12.5v-9A1.5 1.5 0 0 1 3.5 2H6" />
                <path d="M10 5l3 3-3 3" />
                <path d="M13 8H6" />
              </svg>
            </button>
            <label className="language-select" style={{ marginLeft: "auto" }}>
              <select
                aria-label={t.language}
                onChange={(event) => onLanguageChange(event.target.value as Language)}
                value={language}
                style={{ minHeight: 28, fontSize: 11, padding: "3px 8px" }}
              >
                <option value="fr">FR</option>
                <option value="en">EN</option>
              </select>
            </label>
          </div>
        </div>
      </aside>

      <div className="shell-main">
        <header className="topbar">
          <div className="topbar-left">
            <span className="topbar-breadcrumb">PBO</span>
            <span className="topbar-sep">›</span>
            <span className="topbar-title">{t.adminConsole}</span>
          </div>
          <div className="topbar-right">
            <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <span style={{
                width: 6, height: 6, borderRadius: "50%",
                background: "var(--gr)", display: "inline-block"
              }} />
              <span className="muted-text">LIVE</span>
            </div>
          </div>
        </header>

        <main className="page-container">
          {children}
        </main>
      </div>
    </div>
  );
}
