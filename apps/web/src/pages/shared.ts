import type { AppDataState } from "../hooks/useAppData";
import type { Language, TranslationDictionary } from "../i18n";
import type { ExternalBackupRun, ExternalDisk, VirtualMachine } from "../types";

export interface PageCommonProps {
  data: AppDataState;
  language: Language;
  t: TranslationDictionary;
}

export interface AssetPageProps extends PageCommonProps {
  pbsInventoryByVmId: Map<number, { protected: boolean; last_backup_at: string | null }>;
  savingKey: string | null;
  onVmCriticalChange: (vmId: number, critical: boolean) => void;
}

export interface DiskActionRequest {
  disk: ExternalDisk;
  field: "trusted" | "dedicated_backup_disk" | "allow_existing_data";
  value: boolean;
}

export interface DisksPageProps extends PageCommonProps {
  savingKey: string | null;
  onDiskToggleRequest: (request: DiskActionRequest) => void;
  onExternalBackupRequest: (disk: ExternalDisk) => void;
  onDiskFieldChange: (
    diskId: number,
    payload: Partial<
      Pick<
        ExternalDisk,
        | "usable_capacity_gb"
        | "reserved_capacity_gb"
        | "planning_notes"
        | "display_name"
      >
    >,
  ) => void;
}

export interface DashboardPageProps extends PageCommonProps {
  latestBackupLabel: string;
}

export interface IntegrationsPageProps extends PageCommonProps {
  proxmoxSyncing: boolean;
  pbsSyncing: boolean;
  onProxmoxSyncRequest: () => void;
  onPBSSyncRequest: () => void;
}

export interface PlanningPageProps extends PageCommonProps {}

export interface ActivityPageProps extends PageCommonProps {
  externalBackupRuns: ExternalBackupRun[];
}

export interface SettingsPageProps {
  t: TranslationDictionary;
}

export interface PlanningRowVm extends VirtualMachine {
  protectedState: boolean;
}
