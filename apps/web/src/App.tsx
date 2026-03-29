import { useEffect, useMemo, useState } from "react";

import {
  getBackupRuns,
  getDisks,
  getOverview,
  getProxmoxInventory,
  getProxmoxStatus,
  getVMs,
  syncProxmoxInventory,
  updateDisk,
  updateVM,
} from "./api";
import { translations, type Language } from "./i18n";
import type {
  BackupRun,
  BackupRunStatus,
  ExternalDisk,
  Overview,
  ProxmoxStatus,
  VirtualMachine,
} from "./types";

interface DashboardState {
  overview: Overview;
  vms: VirtualMachine[];
  disks: ExternalDisk[];
  backupRuns: BackupRun[];
  proxmoxStatus: ProxmoxStatus;
}

const LOCALE_BY_LANGUAGE: Record<Language, string> = {
  en: "en-US",
  fr: "fr-FR",
};

function formatDateTime(value: string | null, language: Language, fallback: string) {
  if (!value) {
    return fallback;
  }

  return new Intl.DateTimeFormat(LOCALE_BY_LANGUAGE[language], {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function statusClassName(status: BackupRunStatus | null) {
  if (!status) {
    return "status-badge status-unknown";
  }

  return `status-badge status-${status}`;
}

function sourceClassName(source: string) {
  return source === "proxmox" ? "source-badge source-proxmox" : "source-badge source-seed";
}

export default function App() {
  const [language, setLanguage] = useState<Language>("en");
  const [dashboard, setDashboard] = useState<DashboardState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bannerError, setBannerError] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);

  const t = translations[language];

  async function loadDashboard() {
    setLoading(true);
    setError(null);

    try {
      const [overview, vms, disks, backupRuns, proxmoxStatus, proxmoxInventory] =
        await Promise.all([
          getOverview(),
          getVMs(),
          getDisks(),
          getBackupRuns(),
          getProxmoxStatus(),
          getProxmoxInventory(),
        ]);

      setDashboard({
        overview,
        vms: proxmoxInventory.length > 0 ? proxmoxInventory : vms,
        disks,
        backupRuns,
        proxmoxStatus,
      });
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadDashboard();
  }, []);

  async function refreshVmInventory() {
    const [overview, vms, proxmoxInventory, proxmoxStatus] = await Promise.all([
      getOverview(),
      getVMs(),
      getProxmoxInventory(),
      getProxmoxStatus(),
    ]);

    setDashboard((current) =>
      current
        ? {
            ...current,
            overview,
            vms: proxmoxInventory.length > 0 ? proxmoxInventory : vms,
            proxmoxStatus,
          }
        : current,
    );
  }

  async function handleVmCriticalChange(vm: VirtualMachine, critical: boolean) {
    const key = `vm-${vm.id}`;
    setSavingKey(key);
    setBannerError(null);

    try {
      const updated = await updateVM(vm.id, { critical });
      setDashboard((current) =>
        current
          ? {
              ...current,
              vms: current.vms.map((item) => (item.id === updated.id ? updated : item)),
            }
          : current,
      );
    } catch (mutationError) {
      setBannerError(mutationError instanceof Error ? mutationError.message : "Unknown error");
    } finally {
      setSavingKey(null);
    }
  }

  async function handleDiskDedicatedChange(disk: ExternalDisk, dedicated_backup_disk: boolean) {
    const key = `disk-${disk.id}`;
    setSavingKey(key);
    setBannerError(null);

    try {
      const updated = await updateDisk(disk.id, { dedicated_backup_disk });
      setDashboard((current) =>
        current
          ? {
              ...current,
              disks: current.disks.map((item) => (item.id === updated.id ? updated : item)),
            }
          : current,
      );
    } catch (mutationError) {
      setBannerError(mutationError instanceof Error ? mutationError.message : "Unknown error");
    } finally {
      setSavingKey(null);
    }
  }

  async function handleSyncInventory() {
    setSyncing(true);
    setBannerError(null);
    setSyncMessage(null);

    try {
      const summary = await syncProxmoxInventory();
      await refreshVmInventory();
      setSyncMessage(
        `${t.proxmoxSyncSummary}: ${summary.total_seen} (${summary.synced_vms_count} VM, ${summary.synced_cts_count} CT)`,
      );
    } catch (syncError) {
      setBannerError(syncError instanceof Error ? syncError.message : "Unknown error");
    } finally {
      setSyncing(false);
    }
  }

  const latestStatusLabel = useMemo(() => {
    const status = dashboard?.overview.latest_backup_status;
    if (!status) {
      return t.status.unknown;
    }

    return t.status[status];
  }, [dashboard?.overview.latest_backup_status, t.status]);

  if (loading) {
    return (
      <main className="app-shell">
        <section className="state-card">
          <p className="state-text">{t.loading}</p>
        </section>
      </main>
    );
  }

  if (error || !dashboard) {
    return (
      <main className="app-shell">
        <section className="state-card">
          <p className="state-text">{t.error}</p>
          {error ? <p className="state-error">{error}</p> : null}
          <button className="retry-button" onClick={() => void loadDashboard()} type="button">
            {t.retry}
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <section className="hero">
        <div>
          <p className="eyebrow">{t.dashboard}</p>
          <h1>{t.title}</h1>
          <p className="subtitle">{t.subtitle}</p>
        </div>

        <label className="language-select">
          <span>{t.language}</span>
          <select
            value={language}
            aria-label={t.language}
            onChange={(event) => setLanguage(event.target.value as Language)}
          >
            <option value="fr">FR</option>
            <option value="en">EN</option>
          </select>
        </label>
      </section>

      {bannerError ? (
        <section className="banner banner-error">
          <p>{bannerError}</p>
        </section>
      ) : null}

      {syncMessage ? (
        <section className="banner banner-info">
          <p>{syncMessage}</p>
        </section>
      ) : null}

      <section className="card-grid">
        <article className="card kpi-card">
          <p className="card-label">{t.coveragePercent}</p>
          <p className="card-value">{dashboard.overview.coverage_percent}%</p>
          <p className="card-detail">
            {dashboard.overview.protected_vms} / {dashboard.overview.total_vms} {t.coverageDetail}
          </p>
        </article>

        <article className="card kpi-card">
          <p className="card-label">{t.totalVms}</p>
          <p className="card-value">{dashboard.overview.total_vms}</p>
          <p className="card-detail">{t.totalVmsDetail}</p>
        </article>

        <article className="card kpi-card">
          <p className="card-label">{t.connectedDisks}</p>
          <p className="card-value">{dashboard.overview.connected_disks}</p>
          <p className="card-detail">{t.connectedDisksDetail}</p>
        </article>

        <article className="card kpi-card">
          <p className="card-label">{t.latestBackup}</p>
          <p className={`card-value ${statusClassName(dashboard.overview.latest_backup_status)}`}>
            {latestStatusLabel}
          </p>
          <p className="card-detail">{t.latestBackupDetail}</p>
        </article>
      </section>

      <section className="panel">
        <div className="section-heading">
          <h2>{t.proxmoxConnection}</h2>
          <button
            className="action-button"
            disabled={syncing}
            onClick={() => void handleSyncInventory()}
            type="button"
          >
            {syncing ? t.proxmoxSyncing : t.proxmoxSync}
          </button>
        </div>

        <div className="proxmox-grid">
          <div>
            <p className="card-label">{t.proxmoxStatus}</p>
            <p className={statusClassName(dashboard.proxmoxStatus.connected ? "success" : "failed")}>
              {dashboard.proxmoxStatus.connected ? t.connected : t.disconnected}
            </p>
          </div>
          <div>
            <p className="card-label">{t.proxmoxNode}</p>
            <p>{dashboard.proxmoxStatus.node_name}</p>
          </div>
          <div>
            <p className="card-label">{t.proxmoxSsl}</p>
            <p>{dashboard.proxmoxStatus.verify_ssl ? t.yes : t.no}</p>
          </div>
          <div>
            <p className="card-label">{t.proxmoxMessage}</p>
            <p>{dashboard.proxmoxStatus.message}</p>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="section-heading">
          <h2>{t.virtualMachines}</h2>
          {savingKey?.startsWith("vm-") ? <span className="saving-indicator">{t.saving}</span> : null}
        </div>

        {dashboard.vms.length === 0 ? (
          <p className="empty-state">{t.emptyVms}</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t.vmName}</th>
                  <th>{t.vmType}</th>
                  <th>{t.vmSource}</th>
                  <th>{t.vmNode}</th>
                  <th>{t.vmRuntimeStatus}</th>
                  <th>{t.vmCritical}</th>
                  <th>{t.vmSize}</th>
                  <th>{t.vmEnabled}</th>
                  <th>{t.vmLastBackup}</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.vms.map((vm) => (
                  <tr key={vm.id}>
                    <td>{vm.name}</td>
                    <td>{vm.vm_type.toUpperCase()}</td>
                    <td>
                      <span className={sourceClassName(vm.source)}>{t.source[vm.source]}</span>
                    </td>
                    <td>{vm.node_name ?? t.notAvailable}</td>
                    <td>{vm.runtime_status ?? t.notAvailable}</td>
                    <td>
                      <label className="checkbox-cell">
                        <input
                          checked={vm.critical}
                          disabled={savingKey === `vm-${vm.id}`}
                          type="checkbox"
                          onChange={(event) => void handleVmCriticalChange(vm, event.target.checked)}
                        />
                        <span>{vm.critical ? t.yes : t.no}</span>
                      </label>
                    </td>
                    <td>{vm.size_gb}</td>
                    <td>{vm.enabled ? t.yes : t.no}</td>
                    <td>{formatDateTime(vm.last_backup_at, language, t.notAvailable)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="section-heading">
          <h2>{t.externalDisks}</h2>
          {savingKey?.startsWith("disk-") ? <span className="saving-indicator">{t.saving}</span> : null}
        </div>

        {dashboard.disks.length === 0 ? (
          <p className="empty-state">{t.emptyDisks}</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t.diskName}</th>
                  <th>{t.diskSerial}</th>
                  <th>{t.diskCapacity}</th>
                  <th>{t.diskConnected}</th>
                  <th>{t.diskDedicated}</th>
                  <th>{t.diskAllowExistingData}</th>
                  <th>{t.diskPreferredRootPath}</th>
                  <th>{t.diskNotes}</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.disks.map((disk) => (
                  <tr key={disk.id}>
                    <td>{disk.display_name}</td>
                    <td>{disk.serial_number}</td>
                    <td>{disk.capacity_gb}</td>
                    <td>{disk.connected ? t.yes : t.no}</td>
                    <td>
                      <label className="checkbox-cell">
                        <input
                          checked={disk.dedicated_backup_disk}
                          disabled={savingKey === `disk-${disk.id}`}
                          type="checkbox"
                          onChange={(event) =>
                            void handleDiskDedicatedChange(disk, event.target.checked)
                          }
                        />
                        <span>{disk.dedicated_backup_disk ? t.yes : t.no}</span>
                      </label>
                    </td>
                    <td>{disk.allow_existing_data ? t.yes : t.no}</td>
                    <td>{disk.preferred_root_path ?? t.notAvailable}</td>
                    <td>{disk.notes ?? t.notAvailable}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>{t.recentBackupRuns}</h2>
        {dashboard.backupRuns.length === 0 ? (
          <p className="empty-state">{t.emptyBackupRuns}</p>
        ) : (
          <div className="table-wrap">
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
                {dashboard.backupRuns.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <span className={statusClassName(run.status)}>{t.status[run.status]}</span>
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
          </div>
        )}
      </section>
    </main>
  );
}
