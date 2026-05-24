import { useEffect, useMemo, useState } from "react";

import {
  checkMaintenanceComponent,
  getMaintenanceStatus,
  getNotificationPreferences,
  getNotificationStatus,
  getSystemTime,
  resetNotificationPreferences,
  sendTestNotification,
  updateNotificationPreferences,
  updateMaintenanceComponent,
} from "../api";
import { ErrorBanner } from "../components/ErrorBanner";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import type { SettingsPageProps } from "./shared";
import type { MaintenanceAction, MaintenanceCommandResult, MaintenanceComponentStatus, NotificationPreferences, NotificationStatus } from "../types";
import { formatDateTimeLocal } from "../utils";

type MaintenanceComponent = "app" | "proxmox-agent" | "pbs-agent";
type ComponentUiState = "idle" | "checking" | "update_running" | "post_update_checking" | "update_success" | "update_error" | "restarting";

interface ComponentMeta {
  uiState: ComponentUiState;
  lastCheckedAt: string | null;
  lastUpdatedAt: string | null;
  message: string | null;
  logs: MaintenanceCommandResult[];
}

const COMPONENTS: { id: MaintenanceComponent; backend: string; label: string }[] = [
  { id: "app", backend: "app-vm", label: "App VM" },
  { id: "proxmox-agent", backend: "proxmox-agent", label: "Proxmox agent" },
  { id: "pbs-agent", backend: "pbs-agent", label: "PBS agent" },
];
const UPDATE_ALL_ORDER: MaintenanceComponent[] = ["proxmox-agent", "pbs-agent", "app"];

const initialMeta: Record<MaintenanceComponent, ComponentMeta> = {
  app: { uiState: "idle", lastCheckedAt: null, lastUpdatedAt: null, message: null, logs: [] },
  "proxmox-agent": { uiState: "idle", lastCheckedAt: null, lastUpdatedAt: null, message: null, logs: [] },
  "pbs-agent": { uiState: "idle", lastCheckedAt: null, lastUpdatedAt: null, message: null, logs: [] },
};

const NOTIFICATION_EVENTS = [
  ["notify_on_backup_success", "notificationEventBackupSuccess"],
  ["notify_on_backup_failure", "notificationEventBackupFailure"],
  ["notify_on_disk_eject_ready", "notificationEventDiskEjectReady"],
  ["notify_on_update_result", "notificationEventUpdateResult"],
  ["notify_on_agent_degraded", "notificationEventAgentDegraded"],
  ["notify_on_low_coverage", "notificationEventLowCoverage"],
  ["notify_on_disk_new_detected", "notificationEventDiskNewDetected"],
  ["notify_on_disk_known_detected", "notificationEventDiskKnownDetected"],
  ["notify_on_planned_disk_detected", "notificationEventPlannedDiskDetected"],
  ["notify_on_planned_backup_reminder", "notificationEventPlannedBackupReminder"],
  ["notify_on_planned_backup_started", "notificationEventPlannedBackupStarted"],
  ["notify_on_planned_confirmation_required", "notificationEventPlannedConfirmationRequired"],
  ["notify_on_planned_backup_missed", "notificationEventPlannedBackupMissed"],
] as const;

function shortCommit(value: string | null) {
  return value ? value.slice(0, 12) : "N/A";
}

function nowIso() {
  return new Date().toISOString();
}

function backendName(component: MaintenanceComponent) {
  return COMPONENTS.find((item) => item.id === component)?.backend ?? component;
}

function componentIdFromBackend(component: string): MaintenanceComponent | null {
  return COMPONENTS.find((item) => item.backend === component)?.id ?? null;
}

function statusTone(status: string) {
  if (status === "up_to_date") return "success" as const;
  if (status === "update_available") return "warning" as const;
  return "danger" as const;
}

function uiTone(state: ComponentUiState) {
  if (state === "update_success") return "success" as const;
  if (state === "update_error") return "danger" as const;
  if (state === "checking" || state === "update_running" || state === "post_update_checking" || state === "restarting") return "info" as const;
  return "neutral" as const;
}

function statusLabel(status: string, t: SettingsPageProps["t"]) {
  if (status === "up_to_date") return t.maintenanceStatus.up_to_date;
  if (status === "update_available") return t.maintenanceStatus.update_available;
  if (status === "error") return t.maintenanceStatus.error;
  return status;
}

function stateLabel(state: ComponentUiState, t: SettingsPageProps["t"]) {
  return t.maintenanceUiState[state];
}

function isNetworkRestartError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error);
  return /fetch|network|failed|load|timeout|aborted|reset|connexion|connection|internal server error|request failed with status 5\d\d|\b5\d\d\b/i.test(message);
}

function logsHaveErrors(logs: MaintenanceCommandResult[]) {
  return logs.some((log) => log.return_code !== 0);
}

function isUpToDate(status: MaintenanceComponentStatus | undefined) {
  return Boolean(status && status.status === "up_to_date" && (!status.local_commit || !status.remote_commit || status.local_commit === status.remote_commit));
}

function renderLogs(logs: MaintenanceCommandResult[], t: SettingsPageProps["t"]) {
  if (logs.length === 0) {
    return <p className="integration-message">{t.externalBackupNoLogs}</p>;
  }

  return (
    <details className="maintenance-log-details" open={logs.length <= 2 && !logsHaveErrors(logs)}>
      <summary>{t.maintenanceLogs}</summary>
      <div className="maintenance-log-list">
        {logs.map((log, index) => (
          <pre className={log.return_code === 0 ? "maintenance-log" : "maintenance-log maintenance-log-error"} key={`${log.command}-${index}`}>
            {[
              `$ ${log.command}`,
              `exit=${log.return_code}`,
              log.stdout ? `stdout:\n${log.stdout}` : null,
              log.stderr ? `stderr:\n${log.stderr}` : null,
            ].filter(Boolean).join("\n")}
          </pre>
        ))}
      </div>
    </details>
  );
}

export function SettingsPage({ t }: SettingsPageProps) {
  const [components, setComponents] = useState<MaintenanceComponentStatus[]>([]);
  const [meta, setMeta] = useState<Record<MaintenanceComponent, ComponentMeta>>(initialMeta);
  const [notificationStatus, setNotificationStatus] = useState<NotificationStatus | null>(null);
  const [notificationPreferences, setNotificationPreferences] = useState<NotificationPreferences | null>(null);
  const [notificationDraft, setNotificationDraft] = useState<NotificationPreferences | null>(null);
  const [notificationLoading, setNotificationLoading] = useState(false);
  const [notificationTestRunning, setNotificationTestRunning] = useState(false);
  const [notificationSaving, setNotificationSaving] = useState(false);
  const [notificationResult, setNotificationResult] = useState<{ message: string; tone: "info" | "error" } | null>(null);
  const [loading, setLoading] = useState(false);
  const [banner, setBanner] = useState<{ message: string; tone: "info" | "error" } | null>(null);

  const anyBusy = useMemo(
    () => Object.values(meta).some((item) => item.uiState === "checking" || item.uiState === "update_running" || item.uiState === "post_update_checking" || item.uiState === "restarting"),
    [meta],
  );
  const notificationDirty = useMemo(
    () => JSON.stringify(notificationDraft) !== JSON.stringify(notificationPreferences),
    [notificationDraft, notificationPreferences],
  );

  async function loadStatus(options: { silent?: boolean } = {}) {
    if (!options.silent) setLoading(true);
    try {
      const result = await getMaintenanceStatus();
      setComponents(result.components);
      const checkedAt = nowIso();
      setMeta((current) => {
        const next = { ...current };
        for (const status of result.components) {
          const id = componentIdFromBackend(status.component);
          if (!id) continue;
          next[id] = {
            ...next[id],
            lastCheckedAt: checkedAt,
            logs: next[id].logs.length > 0 ? next[id].logs : status.logs,
            uiState: next[id].uiState === "checking" ? "idle" : next[id].uiState,
          };
        }
        return next;
      });
    } catch (loadError) {
      if (!options.silent) {
        setBanner({ message: loadError instanceof Error ? loadError.message : "Unknown error", tone: "error" });
      }
    } finally {
      if (!options.silent) setLoading(false);
    }
  }

  useEffect(() => {
    void loadStatus().then(() => void checkAllComponents());
    void loadNotificationStatus();
  }, []);

  async function checkComponent(component: MaintenanceComponent) {
    setComponentMeta(component, { uiState: "checking", message: null });
    try {
      const result = await checkMaintenanceComponent(component);
      upsertComponent(result);
      setComponentMeta(component, {
        uiState: "idle",
        lastCheckedAt: nowIso(),
        logs: result.logs,
        message: null,
      });
    } catch (checkError) {
      setComponentMeta(component, {
        uiState: "update_error",
        message: checkError instanceof Error ? checkError.message : "Unknown error",
      });
    }
  }

  async function checkAllComponents() {
    await Promise.all(COMPONENTS.map((component) => checkComponent(component.id)));
  }

  async function updateComponent(component: MaintenanceComponent) {
    const warning = component === "app" ? t.maintenanceAppRestartWarning : t.maintenanceConfirmUpdate;
    if (!window.confirm(warning)) return;

    setBanner(null);
    try {
      const outcome = await runComponentUpdate(component);
      if (component === "app" && outcome.updated) {
        scheduleAppReload();
      }
    } catch (updateError) {
      if (isNetworkRestartError(updateError)) {
        const recovered = await recoverAfterInterruptedUpdate(component);
        if (recovered) {
          if (component === "app") {
            scheduleAppReload();
          }
        }
        return;
      }
      setComponentMeta(component, {
        uiState: "update_error",
        message: updateError instanceof Error ? updateError.message : "Unknown error",
      });
      setBanner({ message: t.maintenanceUpdateError, tone: "error" });
    }
  }

  async function updateAllComponents() {
    if (anyBusy) return;
    if (!window.confirm(t.maintenanceAppRestartWarning)) return;

    setBanner(null);
    const counts = { already: 0, updated: 0, failed: 0 };
    for (const component of UPDATE_ALL_ORDER) {
      setComponentMeta(component, { uiState: "idle", message: null });
    }

    try {
      for (const component of UPDATE_ALL_ORDER) {
        if (component === "app" && counts.failed > 0) {
          setComponentMeta("app", { uiState: "idle", message: t.maintenanceSkippedDueToAgentFailure });
          break;
        }
        try {
          const outcome = await runComponentUpdate(component);
          if (outcome.already) counts.already += 1;
          else if (outcome.updated) counts.updated += 1;

          if (component === "app" && outcome.updated) {
            scheduleAppReload();
            return;
          }
        } catch (updateError) {
          if (isNetworkRestartError(updateError)) {
            const recovered = await recoverAfterInterruptedUpdate(component);
            if (recovered) {
              counts.updated += 1;
            } else {
              counts.failed += 1;
            }
            if (component === "app" && recovered) {
              scheduleAppReload();
              return;
            }
            continue;
          }
          counts.failed += 1;
          setComponentMeta(component, {
            uiState: "update_error",
            message: updateError instanceof Error ? updateError.message : t.maintenanceUpdateError,
          });
        }
      }
      const message = formatUpdateAllSummary(counts);
      setBanner({ message, tone: counts.failed > 0 ? "error" : "info" });
    } catch (updateError) {
      if (isNetworkRestartError(updateError)) {
        const recovered = await waitForAppRestart("app");
        if (recovered) {
          await loadStatus({ silent: true });
        }
        return;
      }
      setBanner({ message: updateError instanceof Error ? updateError.message : t.maintenanceUpdateError, tone: "error" });
      for (const component of COMPONENTS) {
        setComponentMeta(component.id, { uiState: "update_error", message: t.maintenanceUpdateError });
      }
    }
  }

  async function runComponentUpdate(component: MaintenanceComponent): Promise<{ already: boolean; updated: boolean }> {
    setComponentMeta(component, {
      uiState: "update_running",
      message: t.maintenanceUpdating,
      logs: [clientLog(t.maintenanceUpdateStarted)],
    });

    const result = await updateMaintenanceComponent(component);
    applyActionResult(result);
    const updateReturnedError = result.action_status === "error" || logsHaveErrors(result.logs);
    const already = result.action_status === "up_to_date";

    setComponentMeta(component, {
      uiState: "post_update_checking",
      message: t.maintenancePostUpdateChecking,
      logs: [clientLog(t.maintenanceUpdateStarted), ...result.logs, clientLog(t.maintenanceUpdateCommandResult), clientLog(t.maintenancePostUpdateChecking)],
    });

    try {
      const checked = await waitForComponentUpToDate(component);
      const completedAt = nowIso();
      const message = already
        ? t.maintenanceAlreadyUpToDate
        : updateReturnedError
          ? t.maintenancePostCheckRecovered
          : t.maintenanceUpdateSuccess;
      setComponentMeta(component, {
        uiState: "update_success",
        lastCheckedAt: completedAt,
        lastUpdatedAt: result.finished_at ?? completedAt,
        message,
        logs: mergeLogs([clientLog(t.maintenanceUpdateStarted), ...result.logs, clientLog(t.maintenanceUpdateCommandResult)], checked.logs),
      });
      return { already, updated: !already };
    } catch (error) {
      setComponentMeta(component, {
        uiState: "update_error",
        message: error instanceof Error ? error.message : t.maintenanceUpdateError,
        logs: result.logs,
      });
      throw error;
    }
  }

  async function waitForComponentUpToDate(
    component: MaintenanceComponent,
    options: { timeoutMs?: number } = {},
  ): Promise<MaintenanceComponentStatus> {
    const deadline = Date.now() + (options.timeoutMs ?? 120000);
    let lastError: unknown = null;
    setComponentMeta(component, { uiState: "post_update_checking", message: t.maintenancePostUpdateChecking });

    while (Date.now() < deadline) {
      try {
        const status = await checkMaintenanceComponent(component);
        upsertComponent(status);
        setComponentMeta(component, {
          uiState: "post_update_checking",
          lastCheckedAt: nowIso(),
          logs: status.logs,
          message: t.maintenancePostUpdateChecking,
        });
        if (isUpToDate(status)) {
          return status;
        }
      } catch (error) {
        lastError = error;
        if (isNetworkRestartError(error)) {
          appendComponentLog(component, t.maintenanceTemporaryErrorTolerated);
          setComponentMeta(component, { uiState: "restarting", message: t.maintenanceAgentRestarting });
        } else {
          appendComponentLog(component, error instanceof Error ? error.message : String(error));
          setComponentMeta(component, { uiState: "post_update_checking", message: t.maintenancePostUpdateChecking });
        }
      }

      await new Promise((resolve) => window.setTimeout(resolve, 2000));
    }

    const suffix = lastError instanceof Error ? ` ${lastError.message}` : "";
    throw new Error(`${t.maintenancePostUpdateTimeout}${suffix}`);
  }

  function scheduleAppReload() {
    setComponentMeta("app", { uiState: "update_success", message: t.maintenanceAppReloading });
    setBanner({ message: t.maintenanceAppReloading, tone: "info" });
    window.setTimeout(() => window.location.reload(), 2500);
  }

  function formatUpdateAllSummary(counts: { updated: number; already: number; failed: number }) {
    return t.maintenanceUpdateAllSummary
      .replace("{updated}", String(counts.updated))
      .replace("{already}", String(counts.already))
      .replace("{skipped}", String(counts.already))
      .replace("{failed}", String(counts.failed));
  }

  function mergeLogs(first: MaintenanceCommandResult[], second: MaintenanceCommandResult[]) {
    if (first.length === 0) return second;
    if (second.length === 0) return first;
    return [...first, clientLog(t.maintenancePostUpdateChecking), ...second, clientLog(t.maintenancePostCheckSuccess)];
  }

  function clientLog(message: string): MaintenanceCommandResult {
    return {
      command: "ui",
      return_code: 0,
      stdout: message,
      stderr: null,
    };
  }

  function appendComponentLog(component: MaintenanceComponent, message: string) {
    setMeta((current) => {
      const previous = current[component];
      const lastLog = previous.logs[previous.logs.length - 1];
      if (lastLog?.command === "ui" && lastLog.stdout === message) return current;
      return {
        ...current,
        [component]: {
          ...previous,
          logs: [...previous.logs, clientLog(message)].slice(-20),
        },
      };
    });
  }

  async function recoverAfterInterruptedUpdate(component: MaintenanceComponent): Promise<boolean> {
    if (component === "app") {
      return waitForAppRestart(component);
    }

    setComponentMeta(component, {
      uiState: "restarting",
      message: t.maintenanceAgentRestarting,
      logs: [clientLog(t.maintenanceUpdateStarted), clientLog(t.maintenanceTemporaryErrorTolerated), clientLog(t.maintenancePostUpdateChecking)],
    });
    try {
      const checked = await waitForComponentUpToDate(component);
      const completedAt = nowIso();
      setComponentMeta(component, {
        uiState: "update_success",
        lastCheckedAt: completedAt,
        lastUpdatedAt: completedAt,
        message: t.maintenancePostCheckRecovered,
        logs: mergeLogs([clientLog(t.maintenanceTemporaryErrorTolerated)], checked.logs),
      });
      return true;
    } catch (error) {
      setComponentMeta(component, {
        uiState: "update_error",
        message: error instanceof Error ? error.message : t.maintenanceUpdateError,
      });
      return false;
    }
  }

  async function loadNotificationStatus() {
    setNotificationLoading(true);
    try {
      const [status, preferences] = await Promise.all([getNotificationStatus(), getNotificationPreferences()]);
      setNotificationStatus(status);
      setNotificationPreferences(preferences);
      setNotificationDraft(preferences);
      setNotificationResult(null);
    } catch (error) {
      setNotificationResult({
        message: error instanceof Error ? error.message : "Unknown error",
        tone: "error",
      });
    } finally {
      setNotificationLoading(false);
    }
  }

  async function saveNotificationPreferences() {
    if (!notificationDraft) return;
    setNotificationSaving(true);
    setNotificationResult(null);
    try {
      const saved = await updateNotificationPreferences(notificationDraft);
      setNotificationPreferences(saved);
      setNotificationDraft(saved);
      setNotificationStatus(await getNotificationStatus());
      setNotificationResult({ message: t.notificationPreferencesSaved, tone: "info" });
    } catch (error) {
      setNotificationResult({ message: error instanceof Error ? error.message : "Unknown error", tone: "error" });
    } finally {
      setNotificationSaving(false);
    }
  }

  async function resetNotificationPreferenceDefaults() {
    if (!window.confirm(t.notificationResetConfirm)) return;
    setNotificationSaving(true);
    setNotificationResult(null);
    try {
      const defaults = await resetNotificationPreferences();
      setNotificationPreferences(defaults);
      setNotificationDraft(defaults);
      setNotificationStatus(await getNotificationStatus());
      setNotificationResult({ message: t.notificationPreferencesReset, tone: "info" });
    } catch (error) {
      setNotificationResult({ message: error instanceof Error ? error.message : "Unknown error", tone: "error" });
    } finally {
      setNotificationSaving(false);
    }
  }

  function patchNotificationDraft(patch: Partial<NotificationPreferences>) {
    setNotificationDraft((current) => current ? { ...current, ...patch } : current);
  }

  async function testNotification() {
    setNotificationTestRunning(true);
    setNotificationResult(null);
    try {
      const result = await sendTestNotification();
      setNotificationResult({
        message: result.message,
        tone: result.sent ? "info" : "error",
      });
    } catch (error) {
      setNotificationResult({
        message: error instanceof Error ? error.message : "Unknown error",
        tone: "error",
      });
    } finally {
      setNotificationTestRunning(false);
    }
  }

  async function waitForAppRestart(component: MaintenanceComponent): Promise<boolean> {
    setComponentMeta(component, { uiState: "restarting", message: t.maintenanceRestarting });
    setBanner({ message: t.maintenanceRestarting, tone: "info" });

    const deadline = Date.now() + 120000;
    while (Date.now() < deadline) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
      try {
        await getSystemTime();
        const checked = await waitForComponentUpToDate(component, { timeoutMs: 60000 });
        await loadStatus({ silent: true });
        const completedAt = nowIso();
        setMeta((current) => {
          const next = { ...current };
          for (const item of COMPONENTS) {
            const previous = next[item.id];
            const wasBusy = previous.uiState === "update_running" || previous.uiState === "restarting";
            next[item.id] = {
              ...previous,
              uiState: item.id === component ? "update_success" : wasBusy ? "idle" : previous.uiState,
              lastCheckedAt: completedAt,
              lastUpdatedAt: item.id === component ? completedAt : previous.lastUpdatedAt,
              logs: item.id === component ? checked.logs : previous.logs,
              message: item.id === component ? t.maintenanceAppUpdated : previous.message,
            };
          }
          return next;
        });
        setBanner({ message: t.maintenanceAppUpdated, tone: "info" });
        return true;
      } catch {
        // Keep polling while the API/Web containers restart.
      }
    }

    setComponentMeta(component, { uiState: "update_error", message: t.maintenanceReconnectFailed });
    setBanner({ message: t.maintenanceReconnectFailed, tone: "error" });
    return false;
  }

  function applyActionResult(result: MaintenanceAction) {
    upsertComponent(result.status);
    const id = componentIdFromBackend(result.status.component);
    if (id) {
      setComponentMeta(id, { logs: result.logs, lastUpdatedAt: result.finished_at ?? nowIso() });
    }
  }

  function upsertComponent(status: MaintenanceComponentStatus) {
    setComponents((current) => [
      ...current.filter((item) => item.component !== status.component),
      status,
    ]);
  }

  function setComponentMeta(component: MaintenanceComponent, patch: Partial<ComponentMeta>) {
    setMeta((current) => ({
      ...current,
      [component]: { ...current[component], ...patch },
    }));
  }

  function findStatus(component: MaintenanceComponent) {
    return components.find((item) => item.component === backendName(component));
  }

  return (
    <div className="page-stack">
      <PageHeader title={t.nav.settings} description={t.settingsIntro} />

      <section className="panel-card">
        <div className="panel-card-header">
          <h2>{t.notificationsTitle}</h2>
          <div className="button-row">
            <button className="ghost-button" disabled={notificationLoading} onClick={() => void loadNotificationStatus()} type="button">
              {notificationLoading ? <><span className="inline-spinner" /> {t.maintenanceChecking}</> : t.refresh}
            </button>
            <button
              className="action-button"
              disabled={notificationTestRunning || !notificationStatus?.enabled || !notificationStatus.configured}
              onClick={() => void testNotification()}
              type="button"
            >
              {notificationTestRunning ? <><span className="inline-spinner" /> {t.notificationTestSending}</> : t.notificationTestAction}
            </button>
          </div>
        </div>
        <p className="integration-message">{t.notificationsDescription}</p>
        {notificationResult ? (
          <ErrorBanner dismissLabel={t.dismiss} message={notificationResult.message} onDismiss={() => setNotificationResult(null)} tone={notificationResult.tone} />
        ) : null}
        <div className="integration-details">
          <div className="summary-row">
            <span>{t.notificationStatus}</span>
            <strong>{notificationStatus?.enabled ? t.enabled : t.disabled}</strong>
          </div>
          {notificationStatus && !notificationStatus.environment_enabled ? (
            <div className="summary-row">
              <span>{t.notificationEnvironmentDisabled}</span>
              <strong>{t.yes}</strong>
            </div>
          ) : null}
          <div className="summary-row">
            <span>{t.notificationConfigured}</span>
            <strong>{notificationStatus?.configured ? t.yes : t.no}</strong>
          </div>
          <div className="summary-row">
            <span>{t.notificationProvider}</span>
            <strong>{notificationStatus?.provider ?? t.notAvailable}</strong>
          </div>
          <div className="summary-row">
            <span>{t.notificationBaseUrl}</span>
            <strong>{notificationStatus?.base_url ?? t.notAvailable}</strong>
          </div>
          <div className="summary-row">
            <span>{t.notificationTopic}</span>
            <strong>{notificationStatus?.topic ?? t.notAvailable}</strong>
          </div>
          <div className="summary-row">
            <span>{t.notificationUsername}</span>
            <strong>{notificationStatus?.username ?? t.notAvailable}</strong>
          </div>
          <div className="summary-row">
            <span>{t.notificationLowCoverageThreshold}</span>
            <strong>{notificationDraft ? `${notificationDraft.low_coverage_threshold_percent}%` : t.notAvailable}</strong>
          </div>
        </div>
        <h3 className="settings-subtitle">{t.notificationPreferencesTitle}</h3>
        <div className="settings-toggle-grid">
          <label className="settings-toggle-row">
            <span>{t.notificationGlobalEnabled}</span>
            <span className="toggle">
              <input
                checked={notificationStatus?.environment_enabled ? notificationDraft?.notifications_enabled_override !== false : false}
                disabled={!notificationStatus?.environment_enabled || notificationSaving}
                onChange={(event) => patchNotificationDraft({ notifications_enabled_override: event.target.checked })}
                type="checkbox"
              />
              <span className="toggle-slider" />
            </span>
          </label>
          {NOTIFICATION_EVENTS.map(([field, labelKey]) => (
            <label className="settings-toggle-row" key={field}>
              <span>{t[labelKey]}</span>
              <span className="toggle">
                <input
                  checked={Boolean(notificationDraft?.[field])}
                  disabled={notificationSaving}
                  onChange={(event) => patchNotificationDraft({ [field]: event.target.checked } as Partial<NotificationPreferences>)}
                  type="checkbox"
                />
                <span className="toggle-slider" />
              </span>
            </label>
          ))}
        </div>
        <div className="settings-input-grid">
          <label>
            <span>{t.notificationLowCoverageThreshold}</span>
            <input
              min={0}
              max={100}
              type="number"
              value={notificationDraft?.low_coverage_threshold_percent ?? 100}
              onChange={(event) => patchNotificationDraft({ low_coverage_threshold_percent: Number(event.target.value) })}
            />
          </label>
          <label>
            <span>{t.notificationDiskDetectionCooldown}</span>
            <input
              min={0}
              type="number"
              value={notificationDraft?.disk_detection_notify_cooldown_seconds ?? 1800}
              onChange={(event) => patchNotificationDraft({ disk_detection_notify_cooldown_seconds: Number(event.target.value) })}
            />
          </label>
        </div>
        {notificationDirty ? <p className="integration-message">{t.notificationUnsavedChanges}</p> : null}
        <div className="button-row">
          <button className="action-button" disabled={!notificationDirty || notificationSaving || !notificationDraft} onClick={() => void saveNotificationPreferences()} type="button">
            {notificationSaving ? <><span className="inline-spinner" /> {t.maintenanceUpdating}</> : t.save}
          </button>
          <button className="ghost-button" disabled={notificationSaving} onClick={() => void resetNotificationPreferenceDefaults()} type="button">
            {t.notificationResetDefaults}
          </button>
        </div>
      </section>

      <section className="panel-card">
        <div className="panel-card-header">
          <h2>{t.maintenanceTitle}</h2>
          <div className="button-row">
            <button className="ghost-button" disabled={loading} onClick={() => void loadStatus()} type="button">
              {loading ? <><span className="inline-spinner" /> {t.maintenanceChecking}</> : t.refresh}
            </button>
            <button className="action-button" disabled={anyBusy} onClick={() => void updateAllComponents()} type="button">
              {anyBusy ? t.maintenanceBusy : t.maintenanceUpdateAll}
            </button>
          </div>
        </div>
        <p className="integration-message">{t.maintenanceDescription}</p>
        {banner ? (
          <ErrorBanner dismissLabel={t.dismiss} message={banner.message} onDismiss={() => setBanner(null)} tone={banner.tone} />
        ) : null}

        <div className="maintenance-grid">
          {COMPONENTS.map((component) => {
            const status = findStatus(component.id);
            const componentMeta = meta[component.id];
            const busy = componentMeta.uiState === "checking" || componentMeta.uiState === "update_running" || componentMeta.uiState === "post_update_checking" || componentMeta.uiState === "restarting";
            const upToDate = isUpToDate(status);
            return (
              <article className="maintenance-card" key={component.id}>
                <div className="panel-card-header">
                  <h3>{component.label}</h3>
                  <div className="button-row">
                    {busy ? <span className="inline-spinner" /> : null}
                    <StatusBadge tone={statusTone(status?.status ?? "error")}>
                      {status ? statusLabel(status.status, t) : t.status.unknown}
                    </StatusBadge>
                    {componentMeta.uiState !== "idle" ? (
                      <StatusBadge tone={uiTone(componentMeta.uiState)}>
                        {stateLabel(componentMeta.uiState, t)}
                      </StatusBadge>
                    ) : null}
                  </div>
                </div>
                <div className="integration-details">
                  <div className="summary-row"><span>{t.maintenanceBranch}</span><strong>{status?.branch ?? t.notAvailable}</strong></div>
                  <div className="summary-row"><span>{t.maintenanceLocalCommit}</span><strong>{shortCommit(status?.local_commit ?? null)}</strong></div>
                  <div className="summary-row"><span>{t.maintenanceRemoteCommit}</span><strong>{shortCommit(status?.remote_commit ?? null)}</strong></div>
                  <div className="summary-row"><span>{t.maintenanceLastChecked}</span><strong>{formatDateTimeLocal(componentMeta.lastCheckedAt, "fr", t.notAvailable)}</strong></div>
                  <div className="summary-row"><span>{t.maintenanceLastUpdated}</span><strong>{formatDateTimeLocal(componentMeta.lastUpdatedAt, "fr", t.notAvailable)}</strong></div>
                </div>
                {componentMeta.message ? (
                  <p className={componentMeta.uiState === "update_error" ? "integration-message danger-text" : "integration-message"}>
                    {componentMeta.message}
                  </p>
                ) : null}
                {status?.error ? <p className="integration-message danger-text">{status.error}</p> : null}
                <div className="button-row">
                  <button className="ghost-button" disabled={busy} onClick={() => void checkComponent(component.id)} type="button">
                    {componentMeta.uiState === "checking" ? <><span className="inline-spinner" /> {t.maintenanceChecking}</> : t.maintenanceCheckUpdates}
                  </button>
                  <button
                    className="action-button"
                    disabled={busy || upToDate}
                    onClick={() => void updateComponent(component.id)}
                    title={upToDate ? t.maintenanceNoUpdateAvailable : undefined}
                    type="button"
                  >
                    {componentMeta.uiState === "update_running" || componentMeta.uiState === "post_update_checking" || componentMeta.uiState === "restarting" ? <><span className="inline-spinner" /> {t.maintenanceUpdating}</> : upToDate ? t.maintenanceUpToDateShort : t.maintenanceUpdate}
                  </button>
                </div>
                {renderLogs(componentMeta.logs.length > 0 ? componentMeta.logs : status?.logs ?? [], t)}
              </article>
            );
          })}
        </div>
      </section>
    </div>
  );
}
