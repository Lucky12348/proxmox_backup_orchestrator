import { useEffect, useMemo, useState } from "react";

import {
  getAgentStatus,
  getBackupRuns,
  getExternalBackupRuns,
  getPBSInventory,
  getPBSStatus,
  getPlanningDisks,
  getPlanningOverview,
  getPreferredDisks,
  getProxmoxInventory,
  getProxmoxStatus,
  getUnplannedAssets,
  getVMs,
  getOverview,
  prepareDisk,
  syncPBSInventory,
  syncProxmoxInventory,
  runExternalBackup,
  updateDisk,
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
  VirtualMachine,
  DiskPlanningSummary,
  UnplannedAsset,
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
  pbsInventory: PBSInventoryItem[];
  pbsStatus: PBSStatus;
  proxmoxStatus: ProxmoxStatus;
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
    getExternalBackupRuns(),
    getPlanningDisks(),
    getPlanningOverview(),
    getUnplannedAssets(),
    getProxmoxStatus(),
    getProxmoxInventory(),
    getPBSStatus(),
    getPBSInventory(),
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
    pbsInventory,
    pbsStatus,
    proxmoxStatus,
  };
}

export function useAppData() {
  const [data, setData] = useState<AppDataState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bannerError, setBannerError] = useState<string | null>(null);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [proxmoxSyncing, setProxmoxSyncing] = useState(false);
  const [pbsSyncing, setPbsSyncing] = useState(false);

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

  async function mutateVmCritical(vmId: number, critical: boolean) {
    setSavingKey(`vm-${vmId}`);
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
      setSavingKey(null);
    }
  }

  async function mutateDisk(
    diskId: number,
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
    setSavingKey(`disk-${diskId}`);
    setBannerError(null);

    try {
      await updateDisk(diskId, payload);
      await refresh();
    } catch (mutationError) {
      setBannerError(mutationError instanceof Error ? mutationError.message : "Unknown error");
    } finally {
      setSavingKey(null);
    }
  }

  async function runProxmoxSync(successMessage: string) {
    setProxmoxSyncing(true);
    setBannerError(null);
    setSyncMessage(null);

    try {
      const summary = await syncProxmoxInventory();
      await refresh();
      setSyncMessage(
        `${successMessage}: ${summary.total_seen} (${summary.synced_vms_count} VM, ${summary.synced_cts_count} CT)`,
      );
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
      setSyncMessage(
        `${successMessage}: ${summary.total_snapshots_seen} (${summary.matched_vms} VM, ${summary.matched_cts} CT)`,
      );
    } catch (syncError) {
      setBannerError(syncError instanceof Error ? syncError.message : "Unknown error");
    } finally {
      setPbsSyncing(false);
    }
  }

  async function startExternalBackup(diskId: number, successMessage: string) {
    setSavingKey(`external-backup-${diskId}`);
    setBannerError(null);
    setSyncMessage(null);

    try {
      const run = await runExternalBackup(diskId);
      await refresh();
      setSyncMessage(`${successMessage}: ${run.disk_name}`);
      return run;
    } catch (runError) {
      setBannerError(runError instanceof Error ? runError.message : "Unknown error");
    } finally {
      setSavingKey(null);
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
    setSavingKey(`disk-prep-${diskId}`);
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
      setSavingKey(null);
    }

    return null;
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
    savingKey,
    proxmoxSyncing,
    pbsSyncing,
    pbsInventoryByVmId,
    load,
    refresh,
    clearBannerError: () => setBannerError(null),
    clearSyncMessage: () => setSyncMessage(null),
    mutateVmCritical,
    mutateDisk,
    runProxmoxSync,
    runPBSSync,
    startExternalBackup,
    startDiskPreparation,
  };
}
