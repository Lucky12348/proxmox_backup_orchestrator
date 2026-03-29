import { Link } from "react-router-dom";

import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatCard } from "../components/StatCard";
import { StatusBadge } from "../components/StatusBadge";
import { getAgentStatusTone, getBackupStatusTone } from "../utils";
import type { DashboardPageProps } from "./shared";

export function DashboardPage({ data, t, latestBackupLabel }: DashboardPageProps) {
  return (
    <div className="page-stack">
      <PageHeader title={t.nav.dashboard} description={t.dashboardIntro} />

      <section className="stats-grid">
        <StatCard
          hint={`${data.overview.protected_vms} / ${data.overview.total_vms} ${t.coverageDetail}`}
          label={t.coveragePercent}
          value={`${data.overview.coverage_percent}%`}
        />
        <StatCard label={t.totalVms} value={data.overview.total_vms} />
        <StatCard
          hint={t.planningTrustedDisks}
          label={t.diskTrusted}
          value={data.planningOverview.trusted_disk_count}
        />
        <StatCard
          hint={t.latestBackupDetail}
          label={t.latestBackup}
          value={latestBackupLabel}
          tone={getBackupStatusTone(data.overview.latest_backup_status)}
        />
      </section>

      <section className="summary-grid">
        <article className="panel-card">
          <div className="panel-card-header">
            <h2>{t.integrationsSummary}</h2>
            <Link className="inline-link" to="/integrations">
              {t.viewDetails}
            </Link>
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

        <article className="panel-card">
          <div className="panel-card-header">
            <h2>{t.planningSummary}</h2>
            <Link className="inline-link" to="/planning">
              {t.viewDetails}
            </Link>
          </div>
          <div className="summary-list">
            <div className="summary-row">
              <span>{t.planningCoverage}</span>
              <strong>{data.planningOverview.planning_coverage_percent}%</strong>
            </div>
            <div className="summary-row">
              <span>{t.planningTrustedDisks}</span>
              <strong>{data.planningOverview.trusted_disk_count}</strong>
            </div>
            <div className="summary-row">
              <span>{t.planningPlannedAssets}</span>
              <strong>
                {data.planningOverview.planned_vm_count} / {data.planningOverview.plannable_vm_count}
              </strong>
            </div>
          </div>
        </article>
      </section>

      <section className="summary-grid">
        <article className="panel-card">
          <div className="panel-card-header">
            <h2>{t.unplannedAssetsSummary}</h2>
            <Link className="inline-link" to="/planning">
              {t.viewDetails}
            </Link>
          </div>
          {data.unplannedAssets.length === 0 ? (
            <EmptyState
              description={t.dashboardUnplannedDescription}
              title={t.emptyUnplannedAssets}
            />
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
            <Link className="inline-link" to="/activity">
              {t.viewDetails}
            </Link>
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
