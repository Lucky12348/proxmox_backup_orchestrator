import type {
  AgentStatus,
  BackupRun,
  DiskHandoffStatus,
  DiskPreparationRun,
  DiskPlanningSummary,
  ExternalBackupPreview,
  ExternalBackupRun,
  ExternalDisk,
  Overview,
  PBSInventoryItem,
  PBSStatus,
  PBSSyncSummary,
  ProxmoxStatus,
  ProxmoxSyncSummary,
  PlanningOverview,
  UnplannedAsset,
  VirtualMachine,
} from "./types";

const API_BASE_PATH = "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_PATH}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const body = await response.text();
    let parsedDetail: string | undefined;

    try {
      const parsed = JSON.parse(body) as { detail?: string };
      parsedDetail = parsed.detail;
    } catch {
      parsedDetail = undefined;
    }

    throw new Error(parsedDetail || body || `Request failed with status ${response.status}`);
  }

  return (await response.json()) as T;
}

export function getOverview() {
  return request<Overview>("/overview");
}

export function getVMs() {
  return request<VirtualMachine[]>("/vms");
}

export function updateVM(id: number, payload: Partial<Pick<VirtualMachine, "critical" | "enabled" | "size_gb">>) {
  return request<VirtualMachine>(`/vms/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function getDisks() {
  return request<ExternalDisk[]>("/disks");
}

export function getPreferredDisks() {
  return request<ExternalDisk[]>("/disks/preferred");
}

export function updateDisk(
  id: number,
  payload: Partial<
    Pick<
      ExternalDisk,
      | "dedicated_backup_disk"
      | "allow_existing_data"
      | "preferred_root_path"
      | "notes"
      | "display_name"
      | "trusted"
      | "usable_capacity_gb"
      | "reserved_capacity_gb"
      | "planning_notes"
    >
  >,
) {
  return request<ExternalDisk>(`/disks/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function getBackupRuns() {
  return request<BackupRun[]>("/backup-runs");
}

export function getProxmoxStatus() {
  return request<ProxmoxStatus>("/integrations/proxmox/status");
}

export function syncProxmoxInventory() {
  return request<ProxmoxSyncSummary>("/integrations/proxmox/sync", {
    method: "POST",
  });
}

export function getProxmoxInventory() {
  return request<VirtualMachine[]>("/integrations/proxmox/inventory");
}

export function getPBSStatus() {
  return request<PBSStatus>("/integrations/pbs/status");
}

export function syncPBSInventory() {
  return request<PBSSyncSummary>("/integrations/pbs/sync", {
    method: "POST",
  });
}

export function getPBSInventory() {
  return request<PBSInventoryItem[]>("/integrations/pbs/inventory");
}

export function getAgentStatus() {
  return request<AgentStatus>("/agent/status");
}

export function getPlanningDisks() {
  return request<DiskPlanningSummary[]>("/planning/disks");
}

export function getPlanningOverview() {
  return request<PlanningOverview>("/planning/overview");
}

export function getUnplannedAssets() {
  return request<UnplannedAsset[]>("/planning/unplanned-assets");
}

export function getExternalBackupPreview(diskId: number) {
  return request<ExternalBackupPreview>(`/external-backups/preview/${diskId}`);
}

export function runExternalBackup(diskId: number) {
  return request<ExternalBackupRun>("/external-backups/run", {
    method: "POST",
    body: JSON.stringify({
      disk_id: diskId,
      confirmation: true,
    }),
  });
}

export function getExternalBackupRuns() {
  return request<ExternalBackupRun[]>("/external-backups/runs");
}

export function prepareDisk(
  diskId: number,
  payload: {
    mode: "preserve_existing_data" | "dedicated_backup";
    mount_base_path?: string | null;
    confirm_destructive: boolean;
  },
) {
  return request<DiskPreparationRun>(`/disks/${diskId}/prepare`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function handoffDiskToPBS(diskId: number) {
  return request<DiskHandoffStatus>(`/disks/${diskId}/handoff-to-pbs`, {
    method: "POST",
    body: JSON.stringify({ confirmation: true }),
  });
}

export function detachDiskFromPBS(diskId: number) {
  return request<DiskHandoffStatus>(`/disks/${diskId}/handoff-to-pbs`, {
    method: "DELETE",
  });
}

export function getDiskPBSVisibility(diskId: number) {
  return request<DiskHandoffStatus>(`/disks/${diskId}/pbs-visibility`);
}

export function getDiskPreparationRuns(diskId: number) {
  return request<DiskPreparationRun[]>(`/disks/${diskId}/preparation-runs`);
}

export function getDiskPreparationRun(runId: number) {
  return request<DiskPreparationRun>(`/disks/preparation-runs/${runId}`);
}
