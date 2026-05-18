import { useState, useRef, useEffect, type FormEvent } from "react";
import { useAuth } from "../AuthContext";
import type { TranslationDictionary } from "../i18n";

declare const gsap: any;

interface LoginPageProps {
  t: TranslationDictionary;
}

export function LoginPage({ t }: LoginPageProps) {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (typeof gsap === "undefined" || !cardRef.current) return;
    gsap.from(cardRef.current, {
      opacity: 0,
      y: 32,
      scale: 0.96,
      duration: 0.55,
      ease: "power3.out",
    });
    gsap.from(".login-field", {
      opacity: 0,
      y: 10,
      duration: 0.4,
      stagger: 0.1,
      ease: "power2.out",
      delay: 0.25,
    });
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-shell">
      <div className="login-bg" />
      <div className="login-bg-grid" />

      <div className="login-card" ref={cardRef}>
        <div className="login-header">
          <div className="login-logo">PBO</div>
          <h1 className="login-title">{t.title}</h1>
          <p className="login-subtitle">BACKUP ORCHESTRATION CONSOLE</p>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          {error && <div className="login-error">{error}</div>}

          <div className="login-field">
            <label htmlFor="pbo-username">USERNAME</label>
            <input
              id="pbo-username"
              type="text"
              autoComplete="username"
              autoFocus
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="admin"
              required
              disabled={loading}
            />
          </div>

          <div className="login-field">
            <label htmlFor="pbo-password">PASSWORD</label>
            <input
              id="pbo-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="********"
              required
              disabled={loading}
            />
          </div>

          <button className="login-submit" type="submit" disabled={loading || !username || !password}>
            {loading ? "AUTHENTICATING..." : "CONNECT ->"}
          </button>
        </form>
      </div>
    </div>
  );
}
