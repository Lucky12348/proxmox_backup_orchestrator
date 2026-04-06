import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { formatDateTime, getBackupStatusTone } from "../utils";
import type { ActivityPageProps } from "./shared";

function excerptLog(value: string | null, maxLength = 2000) {
  if (!value) {
    return null;
  }

  return value.length <= maxLength ? value : `${value.slice(0, maxLength)}\n...[truncated]`;
}

export function ActivityPage({ data, externalBackupRuns, language, t }: ActivityPageProps) {
  return (
    <div className="page-stack">
      <PageHeader title={t.nav.activity} description={t.activityIntro} />

      <section className="panel-card">
        <div className="panel-card-header">
          <h2>{t.externalBackupRuns}</h2>
        </div>
        {externalBackupRuns.length === 0 ? (
          <EmptyState description={t.externalBackupRunsDescription} title={t.emptyExternalBackupRuns} />
        ) : (
          <DataTable>
            <table>
              <thead>
                <tr>
                  <th>{t.diskName}</th>
                  <th>{t.backupStatus}</th>
                  <th>{t.externalBackupMode}</th>
                  <th>{t.externalBackupTargetPath}</th>
                  <th>{t.backupStarted}</th>
                  <th>{t.backupFinished}</th>
                  <th>{t.backupSummary}</th>
                  <th>{t.viewDetails}</th>
                </tr>
              </thead>
              <tbody>
                {externalBackupRuns.map((run) => (
                  <tr key={run.id}>
                    <td>{run.disk_name}</td>
                    <td>
                      <StatusBadge tone={getBackupStatusTone(run.status)}>
                        {t.status[run.status]}
                      </StatusBadge>
                    </td>
                    <td>{t.externalBackupModeLabel[run.mode]}</td>
                    <td>{run.target_path}</td>
                    <td>{formatDateTime(run.started_at, language, t.notAvailable)}</td>
                    <td>{formatDateTime(run.finished_at, language, t.notAvailable)}</td>
                    <td>{run.message ?? t.notAvailable}</td>
                    <td>
                      <details className="log-details">
                        <summary>{t.viewDetails}</summary>
                        <div className="log-details-body">
                          <p>
                            <strong>{t.backupStatus}:</strong>{" "}
                            <StatusBadge tone={getBackupStatusTone(run.status)}>
                              {t.status[run.status]}
                            </StatusBadge>
                          </p>
                          <p>
                            <strong>{t.externalBackupResult}:</strong> {run.message ?? t.notAvailable}
                          </p>
                          <p>
                            <strong>{t.externalBackupTargetPath}:</strong> {run.target_path}
                          </p>
                          <p>
                            <strong>{t.pbsDatastore}:</strong> {run.datastore_name}
                          </p>
                          <p>
                            <strong>{t.externalBackupReturnCode}:</strong>{" "}
                            {run.return_code ?? t.notAvailable}
                          </p>
                          <p>
                            <strong>{t.externalBackupCommand}:</strong>{" "}
                            {run.command_summary ?? t.notAvailable}
                          </p>
                          <p>
                            <strong>{t.externalBackupStdout}:</strong>
                          </p>
                          <pre>{excerptLog(run.stdout_log) ?? t.externalBackupNoLogs}</pre>
                          <p>
                            <strong>{t.externalBackupStderr}:</strong>
                          </p>
                          <pre>{excerptLog(run.stderr_log) ?? t.externalBackupNoLogs}</pre>
                        </div>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </DataTable>
        )}
      </section>

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
