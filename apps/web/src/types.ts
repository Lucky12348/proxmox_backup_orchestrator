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
  ignored: boolean;
  ignore_reason: string | null;
}

export interface AssetIgnore {
  id: number;
  source: string;
  node: string;
  vmid: string;
  ignored: boolean;
  reason: string | null;
  updated_at: string;
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
  handoff_status: string | null;
  proxmox_usb_mapping: string | null;
  pbs_handoff_slot: string | null;
  pbs_visible: boolean;
  pbs_device_path: string | null;
  pbs_datastore_name: string | null;
  pbs_mount_path: string | null;
  pbs_filesystem_type: string | null;
  prepared_as_pbs_datastore: boolean;
}

export interface DiskHandoffStatus {
  disk_id: number;
  serial_number: string;
  handoff_status: string;
  proxmox_usb_mapping: string | null;
  pbs_handoff_slot: string | null;
  pbs_visible: boolean;
  pbs_device_path: string | null;
  message: string;
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
  ignored_vms: number;
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
  last_sync_at: string | null;
  sync_running: boolean;
  last_sync_error: string | null;
}

export interface ProxmoxSyncSummary {
  synced_vms_count: number;
  synced_cts_count: number;
  total_seen: number;
  already_running: boolean;
}

export interface ProxmoxBackupJobAsset {
  vmid: number;
  name: string;
  vm_type: string;
  node: string | null;
  included: boolean;
  ignored: boolean;
}

export interface ProxmoxBackupJob {
  job_id: string;
  enabled: boolean;
  node: string | null;
  schedule: string | null;
  storage: string | null;
  retention: string | null;
  selection_mode: string;
  selected_vmids: number[];
  comment: string | null;
  next_run: string | null;
  supported: boolean;
  unsupported_reason: string | null;
  included_assets: ProxmoxBackupJobAsset[];
  available_assets: ProxmoxBackupJobAsset[];
}

export interface PBSStatus {
  connected: boolean;
  datastore: string;
  verify_ssl: boolean;
  message: string;
  last_sync_at: string | null;
  sync_running: boolean;
  last_sync_error: string | null;
}

export interface PBSSyncSummary {
  matched_vms: number;
  matched_cts: number;
  total_snapshots_seen: number;
  already_running: boolean;
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
  loop_image_size_gb: number | null;
  loop_image_size_warning: boolean;
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
  execution_cwd: string | null;
  return_code: number | null;
  current_step: string | null;
  progress_message: string | null;
  last_log_at: string | null;
  progress_percent: number | null;
  total_groups: number | null;
  completed_groups: number | null;
  current_group: string | null;
  current_snapshot: string | null;
  current_archive: string | null;
  downloaded_bytes: number | null;
  current_speed: string | null;
  last_progress_at: string | null;
  warning_messages: string[] | null;
  failed_groups: Array<{ group: string; reason: string }> | null;
  pbs_sync_job_id: string | null;
  pbs_remote_id: string | null;
  pbs_task_upid: string | null;
  elapsed_seconds: number | null;
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

export interface SystemTime {
  now_utc: string;
  now_local: string;
  timezone: string;
  hostname: string;
}

export interface AutoSyncResult {
  enabled: boolean;
  proxmox_triggered: boolean;
  pbs_triggered: boolean;
}

export interface MaintenanceCommandResult {
  command: string;
  stdout: string | null;
  stderr: string | null;
  return_code: number;
}

export interface MaintenanceComponentStatus {
  component: string;
  branch: string | null;
  local_commit: string | null;
  remote_commit: string | null;
  status: "up_to_date" | "update_available" | "error" | string;
  error: string | null;
  logs: MaintenanceCommandResult[];
}

export interface MaintenanceAction {
  component: string;
  status: MaintenanceComponentStatus;
  logs: MaintenanceCommandResult[];
  action_status: "success" | "error" | string;
  finished_at: string | null;
}

export interface MaintenanceStatus {
  components: MaintenanceComponentStatus[];
}

export type ScheduledBackupRecurrenceType = "once" | "daily" | "weekly" | "monthly";
export type ScheduledBackupStartMode = "auto_on_disk_detected" | "manual_confirmation";
export type ScheduledBackupRunStatus =
  | "pending"
  | "waiting_for_disk"
  | "waiting_for_confirmation"
  | "waiting_for_external_backup"
  | "running"
  | "success"
  | "failure"
  | "missed"
  | "cancelled";

export interface ScheduledBackupRun {
  id: number;
  event_id: number;
  event_title: string | null;
  disk_serial: string | null;
  scheduled_for: string;
  window_starts_at: string;
  window_ends_at: string;
  status: ScheduledBackupRunStatus;
  disk_seen_at: string | null;
  reminder_sent_at: string | null;
  backup_run_id: number | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScheduledBackupEvent {
  id: number;
  title: string;
  enabled: boolean;
  disk_serial: string;
  disk_label_or_model: string | null;
  datastore: string;
  recurrence_type: ScheduledBackupRecurrenceType;
  recurrence_config: Record<string, unknown> | null;
  timezone: string;
  window_starts_at: string;
  window_duration_minutes: number;
  notify_before_minutes: number;
  start_mode: ScheduledBackupStartMode;
  auto_eject_after_success: boolean;
  last_status: string | null;
  last_triggered_at: string | null;
  last_completed_at: string | null;
  next_occurrence_at: string | null;
  active_run: ScheduledBackupRun | null;
  created_at: string;
  updated_at: string;
}

export type ScheduledBackupEventPayload = Omit<
  ScheduledBackupEvent,
  | "id"
  | "last_status"
  | "last_triggered_at"
  | "last_completed_at"
  | "next_occurrence_at"
  | "active_run"
  | "created_at"
  | "updated_at"
>;

export interface ScheduledBackupCalendarOccurrence {
  event_id: number;
  occurrence_id: string;
  scheduled_for: string;
  title: string;
  disk_serial: string;
  disk_label: string | null;
  window_starts_at: string;
  window_ends_at: string;
  status: ScheduledBackupRunStatus | null;
  run_id: number | null;
  start_mode: ScheduledBackupStartMode;
  auto_eject_after_success: boolean;
}

export interface NotificationStatus {
  enabled: boolean;
  provider: string;
  configured: boolean;
  base_url: string | null;
  topic: string | null;
  username: string | null;
  events: Record<string, boolean>;
  low_coverage_threshold_percent: number;
  environment_enabled: boolean;
  preferences_enabled: boolean | null;
  disk_detection_notify_cooldown_seconds: number;
}

export interface NotificationPreferences {
  notifications_enabled_override: boolean | null;
  notify_on_backup_success: boolean;
  notify_on_backup_failure: boolean;
  notify_on_disk_eject_ready: boolean;
  notify_on_update_result: boolean;
  notify_on_agent_degraded: boolean;
  notify_on_low_coverage: boolean;
  notify_on_disk_new_detected: boolean;
  notify_on_disk_known_detected: boolean;
  notify_on_planned_disk_detected: boolean;
  notify_on_planned_backup_reminder: boolean;
  notify_on_planned_backup_started: boolean;
  notify_on_planned_confirmation_required: boolean;
  notify_on_planned_backup_missed: boolean;
  low_coverage_threshold_percent: number;
  disk_detection_notify_cooldown_seconds: number;
  updated_at: string | null;
}

export interface NotificationTestResult {
  sent: boolean;
  message: string;
}
