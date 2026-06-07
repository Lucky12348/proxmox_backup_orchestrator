import type { ExternalDisk } from "./types";

export function getDiskDisplayCapacityGb(disk: Pick<ExternalDisk, "usable_capacity_gb" | "capacity_gb">): number {
  return disk.usable_capacity_gb ?? disk.capacity_gb;
}

export function getDiskFilesystemUsage(
  disk: Pick<ExternalDisk, "filesystem_total_gb" | "filesystem_used_gb" | "filesystem_free_gb">,
): { total: number; used: number; free: number } | null {
  if (
    disk.filesystem_total_gb === null
    || disk.filesystem_used_gb === null
    || disk.filesystem_free_gb === null
  ) {
    return null;
  }
  return {
    total: disk.filesystem_total_gb,
    used: disk.filesystem_used_gb,
    free: disk.filesystem_free_gb,
  };
}

export function isAutoEjectEligibleDisk(
  disk: Pick<ExternalDisk, "dedicated_backup_disk" | "prepared_as_pbs_datastore">,
): boolean {
  return disk.dedicated_backup_disk || disk.prepared_as_pbs_datastore;
}

export function coerceAutoEjectAfterSuccess(
  disk: Pick<ExternalDisk, "dedicated_backup_disk" | "prepared_as_pbs_datastore"> | null,
  autoEjectAfterSuccess: boolean,
): boolean {
  if (!autoEjectAfterSuccess) return false;
  return Boolean(disk && isAutoEjectEligibleDisk(disk));
}
