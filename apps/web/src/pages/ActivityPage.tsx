import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { formatDateTime, getBackupStatusTone } from "../utils";
import type { ActivityPageProps } from "./shared";

export function ActivityPage({ data, language, t }: ActivityPageProps) {
  return (
    <div className="page-stack">
      <PageHeader title={t.nav.activity} description={t.activityIntro} />

      <section className="panel-card">
        <div className="panel-card-header">
          <h2>{t.recentBackupRuns}</h2>
        </div>
        {data.backupRuns.length === 0 ? (
          <EmptyState description={t.activityEmptyDescription} title={t.emptyBackupRuns} />
        ) : (
          <DataTable>
            <table>
              <thead>
                <tr>
                  <th>{t.backupStatus}</th>
                  <th>{t.backupStarted}</th>
                  <th>{t.backupFinished}</th>
                  <th>{t.backupTriggeredBy}</th>
                  <th>{t.backupSummary}</th>
                </tr>
              </thead>
              <tbody>
                {data.backupRuns.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <StatusBadge tone={getBackupStatusTone(run.status)}>
                        {t.status[run.status]}
                      </StatusBadge>
                    </td>
                    <td>{formatDateTime(run.started_at, language, t.notAvailable)}</td>
                    <td>{formatDateTime(run.finished_at, language, t.notAvailable)}</td>
                    <td>
                      {t.triggeredBy[run.triggered_by as "manual" | "system" | "schedule"] ??
                        t.triggeredBy.unknown}
                    </td>
                    <td>{run.summary ?? t.notAvailable}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </DataTable>
        )}
      </section>
    </div>
  );
}
