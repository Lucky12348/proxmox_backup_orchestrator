import { useEffect, useMemo, useState } from "react";

import {
  getAgentStatus,
  getBackupRuns,
  getPlanningDisks,
  getPlanningOverview,
  getPBSInventory,
  getPBSStatus,
  getPreferredDisks,
  getProxmoxInventory,
  getProxmoxStatus,
  getVMs,
  getOverview,
  getUnplannedAssets,
  syncPBSInventory,
  syncProxmoxInventory,
  updateDisk,
  updateVM,
} from "./api";
import { translations, type Language } from "./i18n";
import type {
  AgentStatus,
  BackupRun,
  BackupRunStatus,
  DiskPlanningSummary,
  ExternalDisk,
  Overview,
  PBSInventoryItem,
  PBSStatus,
  PlanningOverview,
  ProxmoxStatus,
  UnplannedAsset,
  VirtualMachine,
} from "./types";

interface DashboardState {
  agentStatus: AgentStatus;
  overview: Overview;
  vms: VirtualMachine[];
  disks: ExternalDisk[];
  backupRuns: BackupRun[];
  planningDisks: DiskPlanningSummary[];
  planningOverview: PlanningOverview;
  unplannedAssets: UnplannedAsset[];
  pbsInventory: PBSInventoryItem[];
  pbsStatus: PBSStatus;
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
  if (source === "proxmox") {
    return "source-badge source-proxmox";
  }

  if (source === "agent") {
    return "source-badge source-agent";
  }

  return "source-badge source-seed";
}

export default function App() {
  const [language, setLanguage] = useState<Language>("en");
  const [dashboard, setDashboard] = useState<DashboardState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bannerError, setBannerError] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [pbsSyncing, setPbsSyncing] = useState(false);
  const [proxmoxSyncing, setProxmoxSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);

  const t = translations[language];

  async function loadDashboard() {
    setLoading(true);
    setError(null);

    try {
      const [
        agentStatus,
        overview,
        vms,
        preferredDisks,
        backupRuns,
        planningDisks,
        planningOverview,
        unplannedAssets,
        proxmoxStatus,
        proxmoxInventory,
        pbsStatus,
        pbsInventory,
      ] = await Promise.all([
        getAgentStatus(),
        getOverview(),
        getVMs(),
        getPreferredDisks(),
        getBackupRuns(),
        getPlanningDisks(),
        getPlanningOverview(),
        getUnplannedAssets(),
        getProxmoxStatus(),
        getProxmoxInventory(),
        getPBSStatus(),
        getPBSInventory(),
      ]);

      setDashboard({
        agentStatus,
        overview,
        vms: proxmoxInventory.length > 0 ? proxmoxInventory : vms,
        disks: preferredDisks,
        backupRuns,
        planningDisks,
        planningOverview,
        unplannedAssets,
        pbsInventory,
        pbsStatus,
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

  async function refreshDashboardData() {
    const [
      agentStatus,
      overview,
      vms,
      preferredDisks,
      planningDisks,
      planningOverview,
      unplannedAssets,
      proxmoxInventory,
      proxmoxStatus,
      pbsStatus,
      pbsInventory,
    ] =
      await Promise.all([
        getAgentStatus(),
        getOverview(),
        getVMs(),
        getPreferredDisks(),
        getPlanningDisks(),
        getPlanningOverview(),
        getUnplannedAssets(),
        getProxmoxInventory(),
        getProxmoxStatus(),
        getPBSStatus(),
        getPBSInventory(),
      ]);

    setDashboard((current) =>
      current
        ? {
            ...current,
            agentStatus,
            overview,
            vms: proxmoxInventory.length > 0 ? proxmoxInventory : vms,
            disks: preferredDisks,
            planningDisks,
            planningOverview,
            unplannedAssets,
            pbsInventory,
            pbsStatus,
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

  async function handleDiskFieldUpdate(
    disk: ExternalDisk,
    payload: Partial<
      Pick<
        ExternalDisk,
        | "dedicated_backup_disk"
        | "allow_existing_data"
        | "display_name"
        | "preferred_root_path"
        | "notes"
        | "trusted"
        | "usable_capacity_gb"
        | "reserved_capacity_gb"
        | "planning_notes"
      >
    >,
  ) {
    const key = `disk-${disk.id}`;
    setSavingKey(key);
    setBannerError(null);

    try {
      await updateDisk(disk.id, payload);
      await refreshDashboardData();
    } catch (mutationError) {
      setBannerError(mutationError instanceof Error ? mutationError.message : "Unknown error");
    } finally {
      setSavingKey(null);
    }
  }

  async function handleProxmoxSync() {
    setProxmoxSyncing(true);
    setBannerError(null);
    setSyncMessage(null);

    try {
      const summary = await syncProxmoxInventory();
      await refreshDashboardData();
      setSyncMessage(
        `${t.proxmoxSyncSummary}: ${summary.total_seen} (${summary.synced_vms_count} VM, ${summary.synced_cts_count} CT)`,
      );
    } catch (syncError) {
      setBannerError(syncError instanceof Error ? syncError.message : "Unknown error");
    } finally {
      setProxmoxSyncing(false);
    }
  }

  async function handlePBSSync() {
    setPbsSyncing(true);
    setBannerError(null);
    setSyncMessage(null);

    try {
      const summary = await syncPBSInventory();
      await refreshDashboardData();
      setSyncMessage(
        `${t.pbsSyncSummary}: ${summary.total_snapshots_seen} (${summary.matched_vms} VM, ${summary.matched_cts} CT)`,
      );
    } catch (syncError) {
      setBannerError(syncError instanceof Error ? syncError.message : "Unknown error");
    } finally {
      setPbsSyncing(false);
    }
  }

  const pbsInventoryByVmId = useMemo(
    () => new Map(dashboard?.pbsInventory.map((item) => [item.vm_id, item]) ?? []),
    [dashboard?.pbsInventory],
  );

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
          <h2>{t.agentStatus}</h2>
          <span
            className={statusClassName(
              dashboard.agentStatus.connected ? "success" : "failed",
            )}
          >
            {dashboard.agentStatus.connected ? t.connected : t.degraded}
          </span>
        </div>

        <div className="proxmox-grid">
          <div>
            <p className="card-label">{t.agentHostname}</p>
            <p>{dashboard.agentStatus.hostname ?? t.notAvailable}</p>
          </div>
          <div>
            <p className="card-label">{t.agentHeartbeat}</p>
            <p>
              {formatDateTime(
                dashboard.agentStatus.last_heartbeat_at,
                language,
                t.notAvailable,
              )}
            </p>
          </div>
          <div>
            <p className="card-label">{t.agentReport}</p>
            <p>
              {formatDateTime(
                dashboard.agentStatus.last_report_at,
                language,
                t.notAvailable,
              )}
            </p>
          </div>
          <div>
            <p className="card-label">{t.agentHealth}</p>
            <p>{dashboard.agentStatus.connected ? t.connected : t.degraded}</p>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="section-heading">
          <h2>{t.proxmoxConnection}</h2>
          <button
            className="action-button"
            disabled={proxmoxSyncing}
            onClick={() => void handleProxmoxSync()}
            type="button"
          >
            {proxmoxSyncing ? t.proxmoxSyncing : t.proxmoxSync}
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
          <h2>{t.pbsConnection}</h2>
          <button
            className="action-button"
            disabled={pbsSyncing}
            onClick={() => void handlePBSSync()}
            type="button"
          >
            {pbsSyncing ? t.pbsSyncing : t.pbsSync}
          </button>
        </div>

        <div className="proxmox-grid">
          <div>
            <p className="card-label">{t.pbsStatus}</p>
            <p className={statusClassName(dashboard.pbsStatus.connected ? "success" : "failed")}>
              {dashboard.pbsStatus.connected ? t.connected : t.disconnected}
            </p>
          </div>
          <div>
            <p className="card-label">{t.pbsDatastore}</p>
            <p>{dashboard.pbsStatus.datastore}</p>
          </div>
          <div>
            <p className="card-label">{t.pbsSsl}</p>
            <p>{dashboard.pbsStatus.verify_ssl ? t.yes : t.no}</p>
          </div>
          <div>
            <p className="card-label">{t.pbsMessage}</p>
            <p>{dashboard.pbsStatus.message}</p>
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
                  <th>{t.vmProtected}</th>
                  <th>{t.vmCritical}</th>
                  <th>{t.vmSize}</th>
                  <th>{t.vmEnabled}</th>
                  <th>{t.vmLastBackup}</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.vms.map((vm) => {
                  const backupState = pbsInventoryByVmId.get(vm.id);

                  return (
                    <tr key={vm.id}>
                      <td>{vm.name}</td>
                      <td>{vm.vm_type.toUpperCase()}</td>
                      <td>
                        <span className={sourceClassName(vm.source)}>{t.source[vm.source]}</span>
                      </td>
                      <td>{vm.node_name ?? t.notAvailable}</td>
                      <td>{vm.runtime_status ?? t.notAvailable}</td>
                      <td>{backupState?.protected ? t.yes : t.no}</td>
                      <td>
                        <label className="checkbox-cell">
                          <input
                            checked={vm.critical}
                            disabled={savingKey === `vm-${vm.id}`}
                            type="checkbox"
                            onChange={(event) =>
                              void handleVmCriticalChange(vm, event.target.checked)
                            }
                          />
                          <span>{vm.critical ? t.yes : t.no}</span>
                        </label>
                      </td>
                      <td>{vm.size_gb}</td>
                      <td>{vm.enabled ? t.yes : t.no}</td>
                      <td>
                        {formatDateTime(
                          backupState?.last_backup_at ?? vm.last_backup_at,
                          language,
                          t.notAvailable,
                        )}
                      </td>
                    </tr>
                  );
                })}
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
                  <th>{t.diskSerial}</th>
                  <th>{t.diskName}</th>
                  <th>{t.diskModel}</th>
                  <th>{t.diskCapacity}</th>
                  <th>{t.diskFilesystem}</th>
                  <th>{t.diskMountPath}</th>
                  <th>{t.diskConnected}</th>
                  <th>{t.diskCandidateType}</th>
                  <th>{t.diskDetectionReason}</th>
                  <th>{t.diskDedicated}</th>
                  <th>{t.diskAllowExistingData}</th>
                  <th>{t.diskTrusted}</th>
                  <th>{t.diskUsableCapacity}</th>
                  <th>{t.diskReservedCapacity}</th>
                  <th>{t.diskPlanningNotes}</th>
                  <th>{t.diskLastSeen}</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.disks.map((disk) => (
                  <tr key={disk.id}>
                    <td>{disk.serial_number}</td>
                    <td>{disk.display_name}</td>
                    <td>{disk.model_name ?? t.notAvailable}</td>
                    <td>{disk.capacity_gb}</td>
                    <td>{disk.filesystem_type ?? t.notAvailable}</td>
                    <td>{disk.mount_path ?? t.notAvailable}</td>
                    <td>{disk.connected ? t.yes : t.no}</td>
                    <td>{disk.candidate_type ?? t.notAvailable}</td>
                    <td>{disk.detection_reason ?? t.notAvailable}</td>
                    <td>
                      <label className="checkbox-cell">
                        <input
                          checked={disk.dedicated_backup_disk}
                          disabled={savingKey === `disk-${disk.id}`}
                          type="checkbox"
                          onChange={(event) =>
                            void handleDiskFieldUpdate(disk, {
                              dedicated_backup_disk: event.target.checked,
                            })
                          }
                        />
                        <span>{disk.dedicated_backup_disk ? t.yes : t.no}</span>
                      </label>
                    </td>
                    <td>
                      <label className="checkbox-cell">
                        <input
                          checked={disk.allow_existing_data}
                          disabled={savingKey === `disk-${disk.id}`}
                          type="checkbox"
                          onChange={(event) =>
                            void handleDiskFieldUpdate(disk, {
                              allow_existing_data: event.target.checked,
                            })
                          }
                        />
                        <span>{disk.allow_existing_data ? t.yes : t.no}</span>
                      </label>
                    </td>
                    <td>
                      <label className="checkbox-cell">
                        <input
                          checked={disk.trusted}
                          disabled={savingKey === `disk-${disk.id}`}
                          type="checkbox"
                          onChange={(event) =>
                            void handleDiskFieldUpdate(disk, {
                              trusted: event.target.checked,
                            })
                          }
                        />
                        <span>{disk.trusted ? t.yes : t.no}</span>
                      </label>
                    </td>
                    <td>
                      <input
                        className="number-input"
                        defaultValue={disk.usable_capacity_gb ?? ""}
                        disabled={savingKey === `disk-${disk.id}`}
                        type="number"
                        min={0}
                        onBlur={(event) =>
                          void handleDiskFieldUpdate(disk, {
                            usable_capacity_gb:
                              event.target.value === "" ? null : Number(event.target.value),
                          })
                        }
                      />
                    </td>
                    <td>
                      <input
                        className="number-input"
                        defaultValue={disk.reserved_capacity_gb}
                        disabled={savingKey === `disk-${disk.id}`}
                        type="number"
                        min={0}
                        onBlur={(event) =>
                          void handleDiskFieldUpdate(disk, {
                            reserved_capacity_gb: Number(event.target.value || 0),
                          })
                        }
                      />
                    </td>
                    <td>{disk.planning_notes ?? t.notAvailable}</td>
                    <td>{formatDateTime(disk.last_seen_at, language, t.notAvailable)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>{t.planning}</h2>
        <section className="card-grid compact-grid">
          <article className="card">
            <p className="card-label">{t.planningCoverage}</p>
            <p className="card-value">{dashboard.planningOverview.planning_coverage_percent}%</p>
          </article>
          <article className="card">
            <p className="card-label">{t.planningTrustedDisks}</p>
            <p className="card-value">{dashboard.planningOverview.trusted_disk_count}</p>
          </article>
          <article className="card">
            <p className="card-label">{t.planningPlannedAssets}</p>
            <p className="card-value">
              {dashboard.planningOverview.planned_vm_count} / {dashboard.planningOverview.plannable_vm_count}
            </p>
          </article>
        </section>

        <div className="table-wrap">
          {dashboard.planningDisks.length === 0 ? (
            <p className="empty-state">{t.emptyPlanningDisks}</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>{t.diskName}</th>
                  <th>{t.planningAvailableCapacity}</th>
                  <th>{t.planningTotalPlanned}</th>
                  <th>{t.planningPlannedVmCount}</th>
                  <th>{t.planningUnplannedVmCount}</th>
                  <th>{t.planningFitsAll}</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.planningDisks.map((disk) => (
                  <tr key={disk.disk_id}>
                    <td>{disk.display_name}</td>
                    <td>{disk.available_capacity_gb}</td>
                    <td>{disk.total_planned_gb}</td>
                    <td>{disk.planned_vm_count}</td>
                    <td>{disk.unplanned_vm_count}</td>
                    <td>{disk.fits_all ? t.yes : t.no}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <h3>{t.planningUnplannedAssets}</h3>
        {dashboard.unplannedAssets.length === 0 ? (
          <p className="empty-state">{t.emptyUnplannedAssets}</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t.vmName}</th>
                  <th>{t.vmType}</th>
                  <th>{t.vmSize}</th>
                  <th>{t.vmCritical}</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.unplannedAssets.map((vm) => (
                  <tr key={vm.vm_id}>
                    <td>{vm.name}</td>
                    <td>{vm.vm_type.toUpperCase()}</td>
                    <td>{vm.size_gb}</td>
                    <td>{vm.critical ? t.yes : t.no}</td>
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
