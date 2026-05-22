import { useEffect, useState } from "react";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import {
  getMaintenanceStatus,
  checkMaintenanceComponent,
  updateAllMaintenanceComponents,
  updateMaintenanceComponent,
} from "../api";
import type { SettingsPageProps } from "./shared";
import type { MaintenanceAction, MaintenanceCommandResult, MaintenanceComponentStatus } from "../types";

type MaintenanceComponent = "app" | "proxmox-agent" | "pbs-agent";

const COMPONENTS: { id: MaintenanceComponent; label: string }[] = [
  { id: "app", label: "App VM" },
  { id: "proxmox-agent", label: "Proxmox agent" },
  { id: "pbs-agent", label: "PBS agent" },
];

function shortCommit(value: string | null) {
  return value ? value.slice(0, 12) : "N/A";
}

function statusTone(status: string) {
  if (status === "up_to_date") return "success" as const;
  if (status === "update_available") return "warning" as const;
  return "danger" as const;
}

function statusLabel(status: string, t: SettingsPageProps["t"]) {
  if (status === "up_to_date") return t.maintenanceStatus.up_to_date;
  if (status === "update_available") return t.maintenanceStatus.update_available;
  if (status === "error") return t.maintenanceStatus.error;
  return status;
}

function renderLogs(logs: MaintenanceCommandResult[]) {
  if (logs.length === 0) return null;
  return (
    <pre className="maintenance-log">
      {logs.map((log) => [
        `$ ${log.command}`,
        `exit=${log.return_code}`,
        log.stdout ? `stdout:\n${log.stdout}` : null,
        log.stderr ? `stderr:\n${log.stderr}` : null,
      ].filter(Boolean).join("\n")).join("\n\n")}
    </pre>
  );
}

export function SettingsPage({ t }: SettingsPageProps) {
  const [components, setComponents] = useState<MaintenanceComponentStatus[]>([]);
  const [logs, setLogs] = useState<MaintenanceCommandResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [workingKey, setWorkingKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function loadStatus() {
    setLoading(true);
    setError(null);
    try {
      const result = await getMaintenanceStatus();
      setComponents(result.components);
      setLogs(result.components.flatMap((component) => component.logs));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadStatus();
  }, []);

  async function checkComponent(component: MaintenanceComponent) {
    setWorkingKey(`check-${component}`);
    setError(null);
    try {
      const result = await checkMaintenanceComponent(component);
      setComponents((current) => [
        ...current.filter((item) => item.component !== result.component),
        result,
      ]);
      setLogs(result.logs);
    } catch (checkError) {
      setError(checkError instanceof Error ? checkError.message : "Unknown error");
    } finally {
      setWorkingKey(null);
    }
  }

  async function updateComponent(component: MaintenanceComponent) {
    const warning = component === "app" ? t.maintenanceAppRestartWarning : t.maintenanceConfirmUpdate;
    if (!window.confirm(warning)) return;

    setWorkingKey(`update-${component}`);
    setError(null);
    try {
      const result = await updateMaintenanceComponent(component);
      applyActionResult(result);
    } catch (updateError) {
      setError(updateError instanceof Error ? updateError.message : "Unknown error");
    } finally {
      setWorkingKey(null);
    }
  }

  async function updateAllComponents() {
    if (!window.confirm(t.maintenanceAppRestartWarning)) return;

    setWorkingKey("update-all");
    setError(null);
    try {
      const results = await updateAllMaintenanceComponents();
      for (const result of results) applyActionResult(result);
      setLogs(results.flatMap((result) => result.logs));
    } catch (updateError) {
      setError(updateError instanceof Error ? updateError.message : "Unknown error");
    } finally {
      setWorkingKey(null);
    }
  }

  function applyActionResult(result: MaintenanceAction) {
    setComponents((current) => [
      ...current.filter((item) => item.component !== result.status.component),
      result.status,
    ]);
    setLogs(result.logs);
  }

  function findStatus(component: MaintenanceComponent) {
    const backendName = component === "app" ? "app-vm" : component;
    return components.find((item) => item.component === backendName);
  }

  return (
    <div className="page-stack">
      <PageHeader title={t.nav.settings} description={t.settingsIntro} />

      <section className="panel-card">
        <div className="panel-card-header">
          <h2>{t.maintenanceTitle}</h2>
          <div className="button-row">
            <button className="action-button" disabled={loading || workingKey !== null} onClick={() => void loadStatus()} type="button">
              {loading ? t.loading : t.maintenanceCheckUpdates}
            </button>
            <button className="action-button" disabled={workingKey !== null} onClick={() => void updateAllComponents()} type="button">
              {workingKey === "update-all" ? t.maintenanceUpdating : t.maintenanceUpdateAll}
            </button>
          </div>
        </div>
        <p className="integration-message">{t.maintenanceDescription}</p>
        {error ? <p className="integration-message danger-text">{error}</p> : null}

        <div className="maintenance-grid">
          {COMPONENTS.map((component) => {
            const status = findStatus(component.id);
            return (
              <article className="maintenance-card" key={component.id}>
                <div className="panel-card-header">
                  <h3>{component.label}</h3>
                  <StatusBadge tone={statusTone(status?.status ?? "error")}>
                    {status ? statusLabel(status.status, t) : t.status.unknown}
                  </StatusBadge>
                </div>
                <div className="integration-details">
                  <div className="summary-row"><span>{t.maintenanceBranch}</span><strong>{status?.branch ?? t.notAvailable}</strong></div>
                  <div className="summary-row"><span>{t.maintenanceLocalCommit}</span><strong>{shortCommit(status?.local_commit ?? null)}</strong></div>
                  <div className="summary-row"><span>{t.maintenanceRemoteCommit}</span><strong>{shortCommit(status?.remote_commit ?? null)}</strong></div>
                </div>
                {status?.error ? <p className="integration-message danger-text">{status.error}</p> : null}
                <div className="button-row">
                  <button className="ghost-button" disabled={workingKey !== null} onClick={() => void checkComponent(component.id)} type="button">
                    {workingKey === `check-${component.id}` ? t.loading : t.maintenanceCheckUpdates}
                  </button>
                  <button className="action-button" disabled={workingKey !== null} onClick={() => void updateComponent(component.id)} type="button">
                    {workingKey === `update-${component.id}` ? t.maintenanceUpdating : t.maintenanceUpdate}
                  </button>
                </div>
              </article>
            );
          })}
        </div>

        <h3 className="section-subtitle">{t.maintenanceLogs}</h3>
        {renderLogs(logs) ?? <p className="integration-message">{t.externalBackupNoLogs}</p>}
      </section>
    </div>
  );
}
