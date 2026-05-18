import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import type { Language, TranslationDictionary } from "../i18n";

// GSAP is loaded via CDN in index.html
declare const gsap: any;

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
  const sidebarRef = useRef<HTMLElement>(null);
  const navLinksRef = useRef<HTMLElement>(null);
  const mainRef = useRef<HTMLDivElement>(null);
  const location = useLocation();

  // Sidebar entrance animation
  useEffect(() => {
    if (typeof gsap === "undefined") return;
    const ctx = gsap.context(() => {
      gsap.from(".sidebar-brand", {
        opacity: 0,
        x: -20,
        duration: 0.5,
        ease: "power2.out",
      });
      gsap.from(".nav-link", {
        opacity: 0,
        x: -14,
        duration: 0.4,
        stagger: 0.06,
        ease: "power2.out",
        delay: 0.15,
      });
      gsap.from(".sidebar-footer", {
        opacity: 0,
        y: 10,
        duration: 0.4,
        ease: "power2.out",
        delay: 0.5,
      });
    }, sidebarRef);
    return () => ctx.revert();
  }, []);

  // Page transition on route change
  useEffect(() => {
    if (typeof gsap === "undefined" || !mainRef.current) return;
    gsap.fromTo(
      mainRef.current,
      { opacity: 0, y: 8 },
      { opacity: 1, y: 0, duration: 0.3, ease: "power2.out" }
    );
  }, [location.pathname]);

  return (
    <div className="shell">
      <aside className="sidebar" ref={sidebarRef}>
        <div className="sidebar-brand">
          <p className="sidebar-kicker">PBO</p>
          <h1>{t.title}</h1>
          <p>{t.appTagline}</p>
        </div>

        <nav className="sidebar-nav" ref={navLinksRef as any} aria-label={t.navigation}>
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
            {/* status dot */}
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{
                width: 7, height: 7, borderRadius: "50%",
                background: "var(--success)",
                boxShadow: "0 0 6px var(--success)",
                display: "inline-block"
              }} />
              <span className="muted-text" style={{ fontSize: "0.7rem" }}>LIVE</span>
            </span>
          </div>
        </header>

        <main className="page-container" ref={mainRef}>
          {children}
        </main>
      </div>
    </div>
  );
}
