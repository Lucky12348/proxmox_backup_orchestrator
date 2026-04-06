export type VmType = "vm" | "ct";
export type BackupRunStatus = "pending" | "running" | "success" | "failed";
export type VmSource = "seed" | "proxmox";
export type ExternalBackupMode = "dedicated" | "coexistence";
export type DiskPreparationMode = "preserve_existing_data" | "dedicated_backup";

export interface VirtualMachine {
  id: number;
  name: string;
  vm_type: VmType;
  critical: boolean;
  size_gb: number;
  enabled: boolean;
  source: VmSource;
  external_id: string | null;
  node_name: string | null;
  runtime_status: string | null;
  last_seen_at: string | null;
  last_backup_at: string | null;
}

export interface ExternalDisk {
  id: number;
  serial_number: string;
  display_name: string;
  capacity_gb: number;
  connected: boolean;
  dedicated_backup_disk: boolean;
  allow_existing_data: boolean;
  preferred_root_path: string | null;
  notes: string | null;
  filesystem_type: string | null;
  model_name: string | null;
  mount_path: string | null;
  last_seen_at: string | null;
  detection_reason: string | null;
  candidate_type: string | null;
  trusted: boolean;
  usable_capacity_gb: number | null;
  reserved_capacity_gb: number;
  planning_notes: string | null;
  source: "seed" | "agent";
  active: boolean;
}

export interface BackupRun {
  id: number;
  status: BackupRunStatus;
  started_at: string;
  finished_at: string | null;
  triggered_by: string;
  summary: string | null;
}

export interface Overview {
  total_vms: number;
  protected_vms: number;
  coverage_percent: number;
  connected_disks: number;
  latest_backup_status: BackupRunStatus | null;
  recent_backup_runs: BackupRun[];
}

export interface ProxmoxStatus {
  connected: boolean;
  node_name: string;
  verify_ssl: boolean;
  message: string;
}

export interface ProxmoxSyncSummary {
  synced_vms_count: number;
  synced_cts_count: number;
  total_seen: number;
}

export interface PBSStatus {
  connected: boolean;
  datastore: string;
  verify_ssl: boolean;
  message: string;
}

export interface PBSSyncSummary {
  matched_vms: number;
  matched_cts: number;
  total_snapshots_seen: number;
}

export interface PBSInventoryItem {
  vm_id: number;
  name: string;
  vm_type: VmType;
  last_backup_at: string | null;
  protected: boolean;
}

export interface AgentHeartbeat {
  id: number;
  hostname: string;
  agent_version: string;
  observed_at: string;
}

export interface AgentStatus {
  connected: boolean;
  hostname: string | null;
  last_heartbeat_at: string | null;
  last_report_at: string | null;
  status: "connected" | "degraded" | "disconnected";
  stale_after_minutes: number;
  last_seen_age_seconds: number | null;
}

export interface DiskPlanningSummary {
  disk_id: number;
  serial_number: string;
  display_name: string;
  trusted: boolean;
  available_capacity_gb: number;
  total_planned_gb: number;
  planned_vm_count: number;
  unplanned_vm_count: number;
  fits_all: boolean;
}

export interface UnplannedAsset {
  vm_id: number;
  name: string;
  vm_type: VmType;
  size_gb: number;
  critical: boolean;
}

export interface PlanningOverview {
  trusted_disk_count: number;
  plannable_vm_count: number;
  planned_vm_count: number;
  planning_coverage_percent: number;
}

export interface ExternalBackupPreview {
  target_path: string;
  mode: ExternalBackupMode;
  preserves_existing_data: boolean;
}

export interface ExternalBackupRun {
  id: number;
  disk_id: number;
  disk_name: string;
  status: BackupRunStatus;
  started_at: string;
  finished_at: string | null;
  target_path: string;
  datastore_name: string;
  message: string | null;
  stdout_log: string | null;
  stderr_log: string | null;
  command_summary: string | null;
  mode: ExternalBackupMode;
  created_at: string;
}

export interface DiskPreparationRun {
  id: number;
  disk_id: number;
  mode: DiskPreparationMode;
  status: BackupRunStatus;
  started_at: string;
  finished_at: string | null;
  message: string | null;
  mount_path: string | null;
  filesystem_type: string | null;
  created_at: string;
}
