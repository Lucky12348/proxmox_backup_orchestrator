import type { BackupRunStatus, PBSInventoryItem } from "./types";
import type { Language, TranslationDictionary } from "./i18n";

const LOCALE_BY_LANGUAGE: Record<Language, string> = {
  en: "en-US",
  fr: "fr-FR",
};

export function formatDateTime(value: string | null, language: Language, fallback: string) {
  if (!value) {
    return fallback;
  }

  return new Intl.DateTimeFormat(LOCALE_BY_LANGUAGE[language], {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function getBackupStatusTone(status: BackupRunStatus | null) {
  switch (status) {
    case "success":
      return "success";
    case "failed":
      return "danger";
    case "running":
      return "info";
    case "pending":
      return "warning";
    default:
      return "neutral";
  }
}

export function getRuntimeTone(status: string | null) {
  if (!status) {
    return "neutral";
  }

  if (status === "running") {
    return "success";
  }

  if (status === "stopped") {
    return "neutral";
  }

  return "warning";
}

export function getSourceTone(source: string) {
  if (source === "proxmox") {
    return "info";
  }

  if (source === "agent") {
    return "success";
  }

  return "warning";
}

export function getLatestStatusLabel(
  status: BackupRunStatus | null,
  t: TranslationDictionary,
) {
  if (!status) {
    return t.status.unknown;
  }

  return t.status[status];
}

export function getProtectedState(
  vmId: number,
  inventoryByVmId: Map<number, PBSInventoryItem>,
  fallbackLastBackupAt: string | null,
) {
  const pbsState = inventoryByVmId.get(vmId);

  return {
    protected: pbsState?.protected ?? fallbackLastBackupAt !== null,
    lastBackupAt: pbsState?.last_backup_at ?? fallbackLastBackupAt,
  };
}
