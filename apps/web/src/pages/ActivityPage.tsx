import { useEffect, useRef, useState } from "react";

import { getExternalBackupRun } from "../api";
import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { formatDateTime, getBackupStatusTone } from "../utils";
import type { ExternalBackupRun } from "../types";
import type { ActivityPageProps } from "./shared";

function isActiveRun(run: ExternalBackupRun) {
  return run.status === "pending" || run.status === "running";
}

function excerptLog(value: string | null, maxLength = 32000) {
  if (!value) {
    return null;
  }

  return value.length <= maxLength ? value : `...[truncated]\n${value.slice(-maxLength)}`;
}

export function ActivityPage({
  cleanupSaving,
  data,
  externalBackupRuns,
  language,
  onCleanupOldRunsRequest,
  t,
}: ActivityPageProps) {
  return (
    <div className="page-stack">
      <PageHeader title={t.nav.activity} description={t.activityIntro} />

      <section className="panel-card">
        <div className="panel-card-header">
          <h2>{t.externalBackupRuns}</h2>
          <button
            className="ghost-button"
            disabled={cleanupSaving}
            onClick={onCleanupOldRunsRequest}
            type="button"
          >
            {cleanupSaving ? t.activityCleanupRunning : t.activityCleanupButton}
          </button>
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
                  <th>{t.externalBackupProgress}</th>
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
                    <td>{formatExternalBackupMode(run, t)}</td>
                    <td>
                      <strong>{formatExternalBackupStep(run.current_step, t)}</strong>
                      <br />
                      {formatExternalBackupMessage(run.progress_message ?? run.message, t) ?? t.notAvailable}
                      <br />
                      <span className="muted-text">
                        {t.externalBackupLastLogAt}: {formatDateTime(run.last_log_at, language, t.notAvailable)}
                      </span>
                    </td>
                    <td>{run.target_path}</td>
                    <td>{formatDateTime(run.started_at, language, t.notAvailable)}</td>
                    <td>{formatDateTime(run.finished_at, language, t.notAvailable)}</td>
                    <td>{run.message ?? t.notAvailable}</td>
                    <td>
                      <ExternalBackupRunDetails run={run} language={language} t={t} />
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

function formatExternalBackupMode(run: ExternalBackupRun, t: ActivityPageProps["t"]) {
  if (
    run.mode === "dedicated" &&
    [run.message, run.progress_message, run.stdout_log].some((value) =>
      value?.includes("Existing dedicated PBS datastore reused"),
    )
  ) {
    return t.externalBackupDedicatedReuseMode;
  }
  return t.externalBackupModeLabel[run.mode];
}

function formatExternalBackupStep(step: string | null, t: ActivityPageProps["t"]) {
  if (step === "prepare_dedicated_datastore") {
    return t.externalBackupPrepareDedicatedDatastore;
  }
  return step ?? t.notAvailable;
}

function formatExternalBackupMessage(message: string | null, t: ActivityPageProps["t"]) {
  if (message === "Existing dedicated PBS datastore reused. No formatting performed.") {
    return t.externalBackupDedicatedReuseMessage;
  }
  return message;
}

function ExternalBackupRunDetails({
  run,
  language,
  t,
}: {
  run: ExternalBackupRun;
  language: ActivityPageProps["language"];
  t: ActivityPageProps["t"];
}) {
  const [open, setOpen] = useState(false);
  const [liveRun, setLiveRun] = useState(run);
  const stdoutRef = useRef<HTMLPreElement | null>(null);
  const stderrRef = useRef<HTMLPreElement | null>(null);
  const shouldStickStdout = useRef(true);
  const shouldStickStderr = useRef(true);

  useEffect(() => {
    setLiveRun(run);
  }, [run]);

  useEffect(() => {
    if (!open || !isActiveRun(liveRun)) {
      return;
    }

    const intervalId = window.setInterval(() => {
      void getExternalBackupRun(liveRun.id).then(setLiveRun).catch(() => undefined);
    }, 2000);

    return () => window.clearInterval(intervalId);
  }, [liveRun.id, liveRun.status, open]);

  useEffect(() => {
    scrollLogToBottom(stdoutRef.current, shouldStickStdout.current);
    scrollLogToBottom(stderrRef.current, shouldStickStderr.current);
  }, [liveRun.stdout_log, liveRun.stderr_log]);

  return (
    <details className="log-details" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>{t.viewDetails}</summary>
      <div className="log-details-body">
        <p>
          <strong>{t.backupStatus}:</strong>{" "}
          <StatusBadge tone={getBackupStatusTone(liveRun.status)}>
            {t.status[liveRun.status]}
          </StatusBadge>
        </p>
        <p>
          <strong>{t.externalBackupResult}:</strong> {liveRun.message ?? t.notAvailable}
        </p>
        <p>
          <strong>{t.externalBackupProgress}:</strong> {formatExternalBackupStep(liveRun.current_step, t)} -{" "}
          {formatExternalBackupMessage(liveRun.progress_message, t) ?? t.notAvailable}
        </p>
        <p>
          <strong>{t.externalBackupLastLogAt}:</strong>{" "}
          {formatDateTime(liveRun.last_log_at, language, t.notAvailable)}
        </p>
        <p>
          <strong>{t.externalBackupTargetPath}:</strong> {liveRun.target_path}
        </p>
        <p>
          <strong>{t.pbsDatastore}:</strong> {liveRun.datastore_name}
        </p>
        <p>
          <strong>{t.externalBackupReturnCode}:</strong> {liveRun.return_code ?? t.notAvailable}
        </p>
        <p>
          <strong>{t.externalBackupCommand}:</strong> {liveRun.command_summary ?? t.notAvailable}
        </p>
        <p>
          <strong>cwd:</strong> {liveRun.execution_cwd ?? t.notAvailable}
        </p>
        <p>
          <strong>{t.externalBackupStdout}:</strong>
        </p>
        <pre
          className="log-pre"
          onScroll={(event) => {
            shouldStickStdout.current = isScrolledNearBottom(event.currentTarget);
          }}
          ref={stdoutRef}
        >
          {excerptLog(liveRun.stdout_log) ?? t.externalBackupNoLogs}
        </pre>
        <p>
          <strong>{t.externalBackupStderr}:</strong>
        </p>
        <pre
          className="log-pre"
          onScroll={(event) => {
            shouldStickStderr.current = isScrolledNearBottom(event.currentTarget);
          }}
          ref={stderrRef}
        >
          {excerptLog(liveRun.stderr_log) ?? t.externalBackupNoLogs}
        </pre>
      </div>
    </details>
  );
}

function isScrolledNearBottom(element: HTMLElement) {
  return element.scrollHeight - element.scrollTop - element.clientHeight < 32;
}

function scrollLogToBottom(element: HTMLElement | null, shouldScroll: boolean) {
  if (!element || !shouldScroll) {
    return;
  }
  element.scrollTop = element.scrollHeight;
}
