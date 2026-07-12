import { useEffect, useMemo, useState } from "react";

import {
  getAgentStatus,
  getBackupRuns,
  cleanupBackupRuns,
  cleanupExternalBackupRuns,
  ejectExternalDisk,
  getExternalBackupRuns,
  getPBSInventory,
  getPBSStatus,
  getProxmoxBackupJobs,
  getPlanningDisks,
  getPlanningOverview,
  getScheduledBackupEvents,
  getScheduledBackupRuns,
  getPreferredDisks,
  getProxmoxInventory,
  getProxmoxStatus,
  getSystemVersion,
  getUnplannedAssets,
  getVMs,
  getOverview,
  prepareDisk,
  syncPBSInventory,
  syncProxmoxInventory,
  triggerAutoSync,
  runExternalBackup,
  updateDisk,
  updateAssetIgnore,
  updateProxmoxBackupJobSelection,
  updateVM,
} from "../api";
import type {
  AgentStatus,
  BackupRun,
  ExternalBackupRun,
  ExternalDisk,
  Overview,
  PBSInventoryItem,
  PBSStatus,
  PlanningOverview,
  ProxmoxStatus,
  ProxmoxBackupJob,
  VirtualMachine,
  DiskPlanningSummary,
  UnplannedAsset,
  ScheduledBackupEvent,
  ScheduledBackupRun,
  SystemVersion,
} from "../types";

export interface AppDataState {
  agentStatus: AgentStatus;
  overview: Overview;
  vms: VirtualMachine[];
  disks: ExternalDisk[];
  backupRuns: BackupRun[];
  externalBackupRuns: ExternalBackupRun[];
  planningDisks: DiskPlanningSummary[];
  planningOverview: PlanningOverview;
  unplannedAssets: UnplannedAsset[];
  scheduledBackupEvents: ScheduledBackupEvent[];
  scheduledBackupRuns: ScheduledBackupRun[];
  pbsInventory: PBSInventoryItem[];
  pbsStatus: PBSStatus;
  proxmoxStatus: ProxmoxStatus;
  proxmoxBackupJobs: ProxmoxBackupJob[];
  systemVersion: SystemVersion | null;
}

async function fetchAppData(): Promise<AppDataState> {
  const [
    agentStatus,
    overview,
    vms,
    preferredDisks,
    backupRuns,
    externalBackupRuns,
    planningDisks,
    planningOverview,
    unplannedAssets,
    scheduledBackupEvents,
    scheduledBackupRuns,
    proxmoxStatus,
    proxmoxBackupJobs,
    proxmoxInventory,
    pbsStatus,
    pbsInventory,
    systemVersion,
  ] = await Promise.all([
    getAgentStatus(),
    getOverview(),
    getVMs(),
    getPreferredDisks(),
    getBackupRuns(),
    getExternalBackupRuns(),
    getPlanningDisks(),
    getPlanningOverview(),
    getUnplannedAssets(),
    getScheduledBackupEvents(),
    getScheduledBackupRuns(),
    getProxmoxStatus(),
    getProxmoxBackupJobs().catch(() => []),
    getProxmoxInventory(),
    getPBSStatus(),
    getPBSInventory(),
    getSystemVersion().catch(() => null),
  ]);

  return {
    agentStatus,
    overview,
    vms: proxmoxInventory.length > 0 ? proxmoxInventory : vms,
    disks: preferredDisks,
    backupRuns,
    externalBackupRuns,
    planningDisks,
    planningOverview,
    unplannedAssets,
    scheduledBackupEvents,
    scheduledBackupRuns,
    pbsInventory,
    pbsStatus,
    proxmoxStatus,
    proxmoxBackupJobs,
    systemVersion,
  };
}

export function useAppData() {
  const [data, setData] = useState<AppDataState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bannerError, setBannerError] = useState<string | null>(null);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  // A Set (not a single string) so that two independent mutations in flight at
  // once (e.g. ejecting disk A while toggling "trusted" on disk B) each keep
  // their own button disabled instead of the second one clearing the first's
  // key early and allowing a double-submit on a destructive action.
  const [savingKeys, setSavingKeys] = useState<Set<string>>(new Set());
  const [proxmoxSyncing, setProxmoxSyncing] = useState(false);
  const [pbsSyncing, setPbsSyncing] = useState(false);

  function startSaving(key: string) {
    setSavingKeys((current) => {
      const next = new Set(current);
      next.add(key);
      return next;
    });
  }

  function stopSaving(key: string) {
    setSavingKeys((current) => {
      if (!current.has(key)) {
        return current;
      }
      const next = new Set(current);
      next.delete(key);
      return next;
    });
  }

  function isSaving(key: string) {
    return savingKeys.has(key);
  }

  async function load() {
    setLoading(true);
    setError(null);

    try {
      const nextData = await fetchAppData();
      setData(nextData);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  async function refresh() {
    try {
      const nextData = await fetchAppData();
      setData(nextData);
    } catch (refreshError) {
      setBannerError(refreshError instanceof Error ? refreshError.message : "Unknown error");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!data) {
      return;
    }

    let cancelled = false;
    void triggerAutoSync()
      .then((result) => {
        if (!cancelled && (result.proxmox_triggered || result.pbs_triggered)) {
          window.setTimeout(() => {
            if (!cancelled) void refresh();
          }, 2500);
        }
      })
      .catch((syncError) => {
        if (!cancelled) {
          setBannerError(syncError instanceof Error ? syncError.message : "Unknown error");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [data !== null]);

  const hasActiveExternalBackup =
    data?.externalBackupRuns.some((run) => run.status === "pending" || run.status === "running") ?? false;

  useEffect(() => {
    if (!hasActiveExternalBackup) {
      return;
    }

    const intervalId = window.setInterval(() => {
      void getExternalBackupRuns()
        .then((externalBackupRuns) => {
          setData((current) => (current ? { ...current, externalBackupRuns } : current));
        })
        .catch((pollError) => {
          setBannerError(pollError instanceof Error ? pollError.message : "Unknown error");
        });
    }, 2000);

    return () => window.clearInterval(intervalId);
  }, [hasActiveExternalBackup]);

  async function mutateVmCritical(vmId: number, critical: boolean) {
    const key = `vm-${vmId}`;
    startSaving(key);
    setBannerError(null);

    try {
      const updated = await updateVM(vmId, { critical });
      setData((current) =>
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
      stopSaving(key);
    }
  }

  async function mutateDisk(
    diskId: number,
    payload: Partial<
      Pick<
        ExternalDisk,
        | "dedicated_backup_disk"
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
    const key = `disk-${diskId}`;
    startSaving(key);
    setBannerError(null);

    try {
      await updateDisk(diskId, payload);
      await refresh();
    } catch (mutationError) {
      setBannerError(mutationError instanceof Error ? mutationError.message : "Unknown error");
    } finally {
      stopSaving(key);
    }
  }

  async function runProxmoxSync(successMessage: string) {
    setProxmoxSyncing(true);
    setBannerError(null);
    setSyncMessage(null);

    try {
      const summary = await syncProxmoxInventory();
      await refresh();
      setSyncMessage(summary.already_running
        ? "Proxmox sync is already running."
        : `${successMessage}: ${summary.total_seen} (${summary.synced_vms_count} VM, ${summary.synced_cts_count} CT)`);
    } catch (syncError) {
      setBannerError(syncError instanceof Error ? syncError.message : "Unknown error");
    } finally {
      setProxmoxSyncing(false);
    }
  }

  async function runPBSSync(successMessage: string) {
    setPbsSyncing(true);
    setBannerError(null);
    setSyncMessage(null);

    try {
      const summary = await syncPBSInventory();
      await refresh();
      setSyncMessage(summary.already_running
        ? "PBS sync is already running."
        : `${successMessage}: ${summary.total_snapshots_seen} (${summary.matched_vms} VM, ${summary.matched_cts} CT)`);
    } catch (syncError) {
      setBannerError(syncError instanceof Error ? syncError.message : "Unknown error");
    } finally {
      setPbsSyncing(false);
    }
  }

  async function startExternalBackup(diskId: number, successMessage: string) {
    const key = `external-backup-${diskId}`;
    startSaving(key);
    setBannerError(null);
    setSyncMessage(null);

    try {
      setSyncMessage("External backup run started. Live progress is available on the Activity page.");
      const run = await runExternalBackup(diskId);
      setData((current) =>
        current
          ? {
              ...current,
              externalBackupRuns: [run, ...current.externalBackupRuns.filter((item) => item.id !== run.id)],
            }
          : current,
      );
      setSyncMessage(`${successMessage}: ${run.disk_name}`);
      return run;
    } catch (runError) {
      setBannerError(runError instanceof Error ? runError.message : "Unknown error");
    } finally {
      stopSaving(key);
    }

    return null;
  }

  async function startDiskPreparation(
    diskId: number,
    payload: {
      mode: "preserve_existing_data" | "dedicated_backup";
      mount_base_path?: string | null;
      confirm_destructive: boolean;
    },
    successMessage: string,
  ) {
    const key = `disk-prep-${diskId}`;
    startSaving(key);
    setBannerError(null);
    setSyncMessage(null);

    try {
      const run = await prepareDisk(diskId, payload);
      await refresh();
      setSyncMessage(`${successMessage}: ${run.mount_path ?? `disk ${diskId}`}`);
      return run;
    } catch (runError) {
      setBannerError(runError instanceof Error ? runError.message : "Unknown error");
    } finally {
      stopSaving(key);
    }

    return null;
  }

  async function mutateAssetIgnore(vm: VirtualMachine, ignored: boolean, reason?: string | null) {
    const vmid = vm.external_id ?? String(vm.id);
    const key = `vm-ignore-${vm.id}`;
    startSaving(key);
    setBannerError(null);

    try {
      await updateAssetIgnore(vm.source, vm.node_name ?? "-", vmid, { ignored, reason });
      await refresh();
    } catch (mutationError) {
      setBannerError(mutationError instanceof Error ? mutationError.message : "Unknown error");
    } finally {
      stopSaving(key);
    }
  }

  async function mutateBackupJobSelection(jobId: string, selectedVmids: number[]) {
    const key = `backup-job-${jobId}`;
    startSaving(key);
    setBannerError(null);
    setSyncMessage(null);

    try {
      await updateProxmoxBackupJobSelection(jobId, selectedVmids);
      await refresh();
      setSyncMessage("Sélection du job Proxmox mise à jour.");
    } catch (mutationError) {
      setBannerError(mutationError instanceof Error ? mutationError.message : "Unknown error");
    } finally {
      stopSaving(key);
    }
  }

  async function ejectDisk(diskId: number, successMessage: string) {
    const key = `disk-eject-${diskId}`;
    startSaving(key);
    setBannerError(null);
    setSyncMessage(null);

    try {
      await ejectExternalDisk(diskId);
      await refresh();
      setSyncMessage(successMessage);
      return true;
    } catch (ejectError) {
      setBannerError(ejectError instanceof Error ? ejectError.message : "Unknown error");
    } finally {
      stopSaving(key);
    }

    return false;
  }

  async function cleanupActivityRuns(keepLast: number, successMessage: string) {
    const key = "activity-cleanup";
    startSaving(key);
    setBannerError(null);
    setSyncMessage(null);

    try {
      const [externalResult, backupResult] = await Promise.all([
        cleanupExternalBackupRuns(keepLast),
        cleanupBackupRuns(keepLast),
      ]);
      await refresh();
      setSyncMessage(
        `${successMessage}: ${externalResult.deleted + backupResult.deleted}`,
      );
    } catch (cleanupError) {
      setBannerError(cleanupError instanceof Error ? cleanupError.message : "Unknown error");
    } finally {
      stopSaving(key);
    }
  }

  const pbsInventoryByVmId = useMemo(
    () => new Map(data?.pbsInventory.map((item) => [item.vm_id, item]) ?? []),
    [data?.pbsInventory],
  );

  return {
    data,
    loading,
    error,
    bannerError,
    syncMessage,
    isSaving,
    proxmoxSyncing,
    pbsSyncing,
    pbsInventoryByVmId,
    load,
    refresh,
    clearBannerError: () => setBannerError(null),
    clearSyncMessage: () => setSyncMessage(null),
    mutateVmCritical,
    mutateAssetIgnore,
    mutateBackupJobSelection,
    mutateDisk,
    runProxmoxSync,
    runPBSSync,
    startExternalBackup,
    startDiskPreparation,
    ejectDisk,
    cleanupActivityRuns,
  };
}
