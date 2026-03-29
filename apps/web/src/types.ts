export type VmType = "vm" | "ct";
export type BackupRunStatus = "pending" | "running" | "success" | "failed";

export interface VirtualMachine {
  id: number;
  name: string;
  vm_type: VmType;
  critical: boolean;
  size_gb: number;
  enabled: boolean;
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
