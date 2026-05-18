import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { getAgentStatusTone, getBackupStatusTone } from "../utils";
import type { DashboardPageProps } from "./shared";

declare const gsap: any;

// Animated counter hook
function useCountUp(targetValue: number | string, decimals = 0) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const num = typeof targetValue === "string"
      ? parseFloat(targetValue.replace(/[^0-9.]/g, ""))
      : targetValue;

    if (isNaN(num) || typeof gsap === "undefined") return;
    if (!ref.current) return;

    const suffix = typeof targetValue === "string"
      ? targetValue.replace(/[0-9.]/g, "")
      : "";

    const obj = { val: 0 };
    gsap.to(obj, {
      val: num,
      duration: 1.2,
      ease: "power2.out",
      onUpdate() {
        if (ref.current) {
          ref.current.textContent =
            decimals > 0
              ? obj.val.toFixed(decimals) + suffix
              : Math.round(obj.val) + suffix;
        }
      },
    });
  }, [targetValue, decimals]);

  return ref;
}

interface AnimatedStatCardProps {
  label: string;
  value: string | number;
  hint?: string;
  valueClass?: string;
}

function AnimatedStatCard({ label, value, hint, valueClass }: AnimatedStatCardProps) {
  const counterRef = useCountUp(value);
  const cardRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (typeof gsap === "undefined" || !cardRef.current) return;
    gsap.from(cardRef.current, {
      opacity: 0,
      y: 16,
      scale: 0.97,
      duration: 0.45,
      ease: "power2.out",
    });
  }, []);

  return (
    <article className="stat-card" ref={cardRef}>
      <p className="stat-label">{label}</p>
      <p className={`stat-value ${valueClass ?? ""}`}>
        <span ref={counterRef}>0</span>
      </p>
      {hint && <p className="stat-hint">{hint}</p>}
    </article>
  );
}

interface LatestBackupCardProps {
  label: string;
  value: string;
  hint?: string;
  tone?: "neutral" | "success" | "danger" | "warning" | "info";
}

function LatestBackupCard({ label, value, hint, tone }: LatestBackupCardProps) {
  const cardRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (typeof gsap === "undefined" || !cardRef.current) return;
    gsap.from(cardRef.current, {
      opacity: 0,
      y: 16,
      scale: 0.97,
      duration: 0.45,
      ease: "power2.out",
      delay: 0.15,
    });
  }, []);

  const colorMap: Record<string, string> = {
    success: "var(--success)",
    danger:  "var(--danger)",
    warning: "var(--warning)",
    info:    "var(--info)",
    neutral: "var(--text-secondary)",
  };

  return (
    <article className="stat-card" ref={cardRef}>
      <p className="stat-label">{label}</p>
      <p className="stat-value" style={{ color: colorMap[tone ?? "neutral"], fontSize: "1.4rem" }}>
        {value}
      </p>
      {hint && <p className="stat-hint">{hint}</p>}
    </article>
  );
}

export function DashboardPage({ data, t, latestBackupLabel }: DashboardPageProps) {
  const sectionRefs = useRef<HTMLElement[]>([]);
  const statsRef = useRef<HTMLElement>(null);

  // Stagger sections on mount
  useEffect(() => {
    if (typeof gsap === "undefined") return;
    const ctx = gsap.context(() => {
      gsap.from(".dashboard-section", {
        opacity: 0,
        y: 20,
        duration: 0.5,
        stagger: 0.12,
        ease: "power2.out",
        delay: 0.1,
      });
    });
    return () => ctx.revert();
  }, []);

  const backupTone = getBackupStatusTone(data.overview.latest_backup_status);

  return (
    <div className="page-stack">
      <PageHeader title={t.nav.dashboard} description={t.dashboardIntro} />

      {/* KPI STATS */}
      <section className="stats-grid dashboard-section" ref={statsRef}>
        <AnimatedStatCard
          label={t.coveragePercent}
          value={`${data.overview.coverage_percent}%`}
          hint={`${data.overview.protected_vms} / ${data.overview.total_vms} ${t.coverageDetail}`}
          valueClass="stat-value-accent"
        />
        <AnimatedStatCard
          label={t.totalVms}
          value={data.overview.total_vms}
        />
        <AnimatedStatCard
          label={t.diskTrusted}
          value={data.planningOverview.trusted_disk_count}
          hint={t.planningTrustedDisks}
          valueClass="stat-value-success"
        />
        <LatestBackupCard
          label={t.latestBackup}
          value={latestBackupLabel}
          hint={t.latestBackupDetail}
          tone={backupTone}
        />
      </section>

      {/* INTEGRATIONS + PLANNING */}
      <section className="summary-grid dashboard-section">
        {/* Integrations */}
        <article className="panel-card">
          <div className="panel-card-header">
            <h2>{t.integrationsSummary}</h2>
            <Link className="inline-link" to="/integrations">{t.viewDetails}</Link>
          </div>
          <div className="summary-list">
            <div className="summary-row">
              <span>{t.proxmoxConnection}</span>
              <StatusBadge tone={data.proxmoxStatus.connected ? "success" : "danger"}>
                {data.proxmoxStatus.connected ? t.connected : t.disconnected}
              </StatusBadge>
            </div>
            <div className="summary-row">
              <span>{t.pbsConnection}</span>
              <StatusBadge tone={data.pbsStatus.connected ? "success" : "danger"}>
                {data.pbsStatus.connected ? t.connected : t.disconnected}
              </StatusBadge>
            </div>
            <div className="summary-row">
              <span>{t.agentStatus}</span>
              <StatusBadge tone={getAgentStatusTone(data.agentStatus.status)}>
                {t[data.agentStatus.status]}
              </StatusBadge>
            </div>
          </div>
        </article>

        {/* Planning */}
        <article className="panel-card">
          <div className="panel-card-header">
            <h2>{t.planningSummary}</h2>
            <Link className="inline-link" to="/planning">{t.viewDetails}</Link>
          </div>
          <div className="summary-list">
            <div className="summary-row">
              <span>{t.planningCoverage}</span>
              <strong style={{ fontFamily: "var(--text-mono)", color: "var(--accent)", fontSize: "0.9rem" }}>
                {data.planningOverview.planning_coverage_percent}%
              </strong>
            </div>
            <div className="summary-row">
              <span>{t.planningTrustedDisks}</span>
              <strong style={{ fontFamily: "var(--text-mono)", fontSize: "0.9rem" }}>
                {data.planningOverview.trusted_disk_count}
              </strong>
            </div>
            <div className="summary-row">
              <span>{t.planningPlannedAssets}</span>
              <strong style={{ fontFamily: "var(--text-mono)", fontSize: "0.9rem" }}>
                {data.planningOverview.planned_vm_count} / {data.planningOverview.plannable_vm_count}
              </strong>
            </div>
          </div>
        </article>
      </section>

      {/* UNPLANNED + ACTIVITY */}
      <section className="summary-grid dashboard-section">
        <article className="panel-card">
          <div className="panel-card-header">
            <h2>{t.unplannedAssetsSummary}</h2>
            <Link className="inline-link" to="/planning">{t.viewDetails}</Link>
          </div>
          {data.unplannedAssets.length === 0 ? (
            <EmptyState description={t.dashboardUnplannedDescription} title={t.emptyUnplannedAssets} />
          ) : (
            <ul className="compact-list">
              {data.unplannedAssets.slice(0, 5).map((asset) => (
                <li key={asset.vm_id}>
                  <span>{asset.name}</span>
                  <strong>{asset.size_gb} GB</strong>
                </li>
              ))}
            </ul>
          )}
        </article>

        <article className="panel-card">
          <div className="panel-card-header">
            <h2>{t.activitySummary}</h2>
            <Link className="inline-link" to="/activity">{t.viewDetails}</Link>
          </div>
          {data.backupRuns.length === 0 ? (
            <EmptyState description={t.activityIntro} title={t.emptyBackupRuns} />
          ) : (
            <ul className="compact-list">
              {data.backupRuns.slice(0, 4).map((run) => (
                <li key={run.id}>
                  <span>{t.status[run.status]}</span>
                  <StatusBadge tone={getBackupStatusTone(run.status)}>
                    {run.triggered_by}
                  </StatusBadge>
                </li>
              ))}
            </ul>
          )}
        </article>
      </section>
    </div>
  );
}
