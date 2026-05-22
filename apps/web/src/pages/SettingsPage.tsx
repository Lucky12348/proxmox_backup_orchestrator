import { useEffect, useMemo, useState } from "react";

import {
  checkMaintenanceComponent,
  getMaintenanceStatus,
  getSystemTime,
  updateMaintenanceComponent,
} from "../api";
import { ErrorBanner } from "../components/ErrorBanner";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import type { SettingsPageProps } from "./shared";
import type { MaintenanceAction, MaintenanceCommandResult, MaintenanceComponentStatus } from "../types";
import { formatDateTimeLocal } from "../utils";

type MaintenanceComponent = "app" | "proxmox-agent" | "pbs-agent";
type ComponentUiState = "idle" | "checking" | "update_running" | "update_success" | "update_error" | "restarting";

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

const initialMeta: Record<MaintenanceComponent, ComponentMeta> = {
  app: { uiState: "idle", lastCheckedAt: null, lastUpdatedAt: null, message: null, logs: [] },
  "proxmox-agent": { uiState: "idle", lastCheckedAt: null, lastUpdatedAt: null, message: null, logs: [] },
  "pbs-agent": { uiState: "idle", lastCheckedAt: null, lastUpdatedAt: null, message: null, logs: [] },
};

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
  if (state === "checking" || state === "update_running" || state === "restarting") return "info" as const;
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
  return /fetch|network|failed|load|timeout|aborted|reset|connexion|connection/i.test(message);
}

function logsHaveErrors(logs: MaintenanceCommandResult[]) {
  return logs.some((log) => log.return_code !== 0);
}

function isUpToDate(status: MaintenanceComponentStatus | undefined) {
  return status?.status === "up_to_date";
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
  const [loading, setLoading] = useState(false);
  const [banner, setBanner] = useState<{ message: string; tone: "info" | "error" } | null>(null);

  const anyBusy = useMemo(
    () => Object.values(meta).some((item) => item.uiState === "checking" || item.uiState === "update_running" || item.uiState === "restarting"),
    [meta],
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
    void loadStatus();
  }, []);

  useEffect(() => {
    if (!anyBusy) return;
    const intervalId = window.setInterval(() => {
      void loadStatus({ silent: true });
    }, 3000);
    return () => window.clearInterval(intervalId);
  }, [anyBusy]);

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

  async function updateComponent(component: MaintenanceComponent) {
    const warning = component === "app" ? t.maintenanceAppRestartWarning : t.maintenanceConfirmUpdate;
    if (!window.confirm(warning)) return;

    setBanner(null);
    setComponentMeta(component, { uiState: "update_running", message: t.maintenanceUpdating, logs: meta[component].logs });
    try {
      const result = await updateMaintenanceComponent(component);
      applyActionResult(result);
      await loadStatus({ silent: true });
      const noOp = result.action_status === "up_to_date";
      const success = noOp || (result.action_status !== "error" && !logsHaveErrors(result.logs));
      setComponentMeta(component, {
        uiState: success ? "update_success" : "update_error",
        lastUpdatedAt: result.finished_at ?? nowIso(),
        message: noOp ? t.maintenanceAlreadyUpToDate : success ? t.maintenanceUpdateSuccess : t.maintenanceUpdateError,
        logs: result.logs,
      });
      setBanner({ message: noOp ? t.maintenanceAlreadyUpToDate : success ? t.maintenanceUpdateSuccess : t.maintenanceUpdateError, tone: success ? "info" : "error" });
    } catch (updateError) {
      if (component === "app" && isNetworkRestartError(updateError)) {
        await waitForAppRestart(component);
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
    const counts = { skipped: 0, updated: 0, failed: 0 };
    const candidates = COMPONENTS.filter((component) => {
      const status = findStatus(component.id);
      if (isUpToDate(status)) {
        counts.skipped += 1;
        setComponentMeta(component.id, { message: t.maintenanceAlreadyUpToDate });
        return false;
      }
      return true;
    });

    if (candidates.length === 0) {
      setBanner({ message: t.maintenanceUpdateAllSummary.replace("{updated}", "0").replace("{skipped}", String(counts.skipped)).replace("{failed}", "0"), tone: "info" });
      return;
    }

    for (const component of candidates) {
      setComponentMeta(component.id, { uiState: "update_running", message: t.maintenanceUpdating });
    }

    try {
      for (const component of candidates) {
        try {
          const result = await updateMaintenanceComponent(component.id);
          applyActionResult(result);
          const noOp = result.action_status === "up_to_date";
          const success = noOp || (result.action_status !== "error" && !logsHaveErrors(result.logs));
          if (noOp) counts.skipped += 1;
          else if (success) counts.updated += 1;
          else counts.failed += 1;
          setComponentMeta(component.id, {
            uiState: success ? "update_success" : "update_error",
            lastUpdatedAt: result.finished_at ?? nowIso(),
            message: noOp ? t.maintenanceAlreadyUpToDate : success ? t.maintenanceUpdateSuccess : t.maintenanceUpdateError,
            logs: result.logs,
          });
        } catch (updateError) {
          if (component.id === "app" && isNetworkRestartError(updateError)) {
            await waitForAppRestart("app");
            counts.updated += 1;
            continue;
          }
          counts.failed += 1;
          setComponentMeta(component.id, {
            uiState: "update_error",
            message: updateError instanceof Error ? updateError.message : t.maintenanceUpdateError,
          });
        }
      }
      await loadStatus({ silent: true });
      const message = t.maintenanceUpdateAllSummary
        .replace("{updated}", String(counts.updated))
        .replace("{skipped}", String(counts.skipped))
        .replace("{failed}", String(counts.failed));
      setBanner({ message, tone: counts.failed > 0 ? "error" : "info" });
    } catch (updateError) {
      if (isNetworkRestartError(updateError)) {
        await waitForAppRestart("app");
        return;
      }
      setBanner({ message: updateError instanceof Error ? updateError.message : t.maintenanceUpdateError, tone: "error" });
      for (const component of COMPONENTS) {
        setComponentMeta(component.id, { uiState: "update_error", message: t.maintenanceUpdateError });
      }
    }
  }

  async function waitForAppRestart(component: MaintenanceComponent) {
    setComponentMeta(component, { uiState: "restarting", message: t.maintenanceRestarting });
    setBanner({ message: t.maintenanceRestarting, tone: "info" });

    const deadline = Date.now() + 120000;
    while (Date.now() < deadline) {
      await new Promise((resolve) => window.setTimeout(resolve, 2000));
      try {
        await getSystemTime();
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
              message: item.id === component ? t.maintenanceAppUpdated : previous.message,
            };
          }
          return next;
        });
        setBanner({ message: t.maintenanceAppUpdated, tone: "info" });
        return;
      } catch {
        // Keep polling while the API/Web containers restart.
      }
    }

    setComponentMeta(component, { uiState: "update_error", message: t.maintenanceReconnectFailed });
    setBanner({ message: t.maintenanceReconnectFailed, tone: "error" });
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
            const busy = componentMeta.uiState === "checking" || componentMeta.uiState === "update_running" || componentMeta.uiState === "restarting";
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
                    {componentMeta.uiState === "update_running" ? <><span className="inline-spinner" /> {t.maintenanceUpdating}</> : upToDate ? t.maintenanceUpToDateShort : t.maintenanceUpdate}
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
