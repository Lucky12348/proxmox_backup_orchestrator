import { getStoredToken } from "./AuthContext";
import type {
  AgentStatus,
  AutoSyncResult,
  BackupRun,
  DiskHandoffStatus,
  DiskPreparationRun,
  DiskPlanningSummary,
  ExternalBackupPreview,
  ExternalBackupRun,
  ExternalDisk,
  MaintenanceAction,
  MaintenanceComponentStatus,
  MaintenanceStatus,
  NotificationStatus,
  NotificationTestResult,
  ScheduledBackupEvent,
  ScheduledBackupEventPayload,
  ScheduledBackupCalendarOccurrence,
  ScheduledBackupRun,
  Overview,
  PBSInventoryItem,
  PBSStatus,
  PBSSyncSummary,
  ProxmoxStatus,
  ProxmoxSyncSummary,
  PlanningOverview,
  SystemTime,
  UnplannedAsset,
  VirtualMachine,
} from "./types";

const API_BASE_PATH = "/api/v1";

// Custom event to signal 401 to the app (triggers logout)
export const AUTH_EXPIRED_EVENT = "pbo:auth-expired";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getStoredToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> ?? {}),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE_PATH}${path}`, {
    ...init,
    headers,
  });

  // Session expired — dispatch event so App can redirect to login
  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
    throw new Error("Session expired. Please log in again.");
  }

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

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export function getOverview() {
  return request<Overview>("/overview");
}

export function getVMs() {
  return request<VirtualMachine[]>("/vms");
}

export function updateVM(
  id: number,
  payload: Partial<Pick<VirtualMachine, "critical" | "enabled" | "size_gb">>,
) {
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

export function getScheduledBackupEvents() {
  return request<ScheduledBackupEvent[]>("/planning/events");
}

export function getScheduledBackupCalendar(start: string, end: string) {
  const params = new URLSearchParams({ start, end });
  return request<ScheduledBackupCalendarOccurrence[]>(`/planning/calendar?${params.toString()}`);
}

export function createScheduledBackupEvent(payload: ScheduledBackupEventPayload) {
  return request<ScheduledBackupEvent>("/planning/events", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateScheduledBackupEvent(eventId: number, payload: Partial<ScheduledBackupEventPayload>) {
  return request<ScheduledBackupEvent>(`/planning/events/${eventId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteScheduledBackupEvent(eventId: number) {
  return request<void>(`/planning/events/${eventId}`, { method: "DELETE" });
}

export function getScheduledBackupRuns() {
  return request<ScheduledBackupRun[]>("/planning/runs");
}

export function runScheduledBackupNow(eventId: number) {
  return request<ScheduledBackupRun>(`/planning/events/${eventId}/run-now`, { method: "POST" });
}

export function confirmScheduledBackupRun(runId: number) {
  return request<ScheduledBackupRun>(`/planning/runs/${runId}/confirm`, { method: "POST" });
}

export function cancelScheduledBackupRun(runId: number) {
  return request<ScheduledBackupRun>(`/planning/runs/${runId}/cancel`, { method: "POST" });
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
    body: JSON.stringify({ disk_id: diskId, confirmation: true }),
  });
}

export function getExternalBackupRuns() {
  return request<ExternalBackupRun[]>("/external-backups/runs");
}

export function getExternalBackupRun(runId: number) {
  return request<ExternalBackupRun>(`/external-backups/runs/${runId}`);
}

export function cleanupExternalBackupRuns(keepLast = 10) {
  return request<{ deleted: number; keep_last: number }>(
    `/external-backups/runs/cleanup?keep_last=${keepLast}`,
    { method: "DELETE" },
  );
}

export function deleteExternalBackupRun(runId: number) {
  return request<void>(`/external-backups/runs/${runId}`, { method: "DELETE" });
}

export function cleanupBackupRuns(keepLast = 10) {
  return request<{ deleted: number; keep_last: number }>(
    `/backup-runs/cleanup?keep_last=${keepLast}`,
    { method: "DELETE" },
  );
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

export function ejectExternalDisk(diskId: number) {
  return request<ExternalDisk>(`/disks/${diskId}/eject`, { method: "POST" });
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

export function getSystemTime() {
  return request<SystemTime>("/system/time");
}

export function triggerAutoSync() {
  return request<AutoSyncResult>("/system/auto-sync", { method: "POST" });
}

export function getMaintenanceStatus() {
  return request<MaintenanceStatus>("/maintenance/updates/status");
}

export function checkMaintenanceComponent(component: "app" | "proxmox-agent" | "pbs-agent") {
  return request<MaintenanceComponentStatus>(`/maintenance/updates/${component}/check`, {
    method: "POST",
  });
}

export function updateMaintenanceComponent(component: "app" | "proxmox-agent" | "pbs-agent") {
  return request<MaintenanceAction>(`/maintenance/updates/${component}/update`, {
    method: "POST",
  });
}

export function updateAllMaintenanceComponents() {
  return request<MaintenanceAction[]>("/maintenance/updates/update-all", {
    method: "POST",
  });
}

export function getNotificationStatus() {
  return request<NotificationStatus>("/notifications/status");
}

export function sendTestNotification() {
  return request<NotificationTestResult>("/notifications/test", {
    method: "POST",
  });
}
