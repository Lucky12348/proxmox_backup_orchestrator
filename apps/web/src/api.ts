import type { BackupRun, ExternalDisk, Overview, VirtualMachine } from "./types";

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
    const message = await response.text();
    throw new Error(message || `Request failed with status ${response.status}`);
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

export function updateDisk(
  id: number,
  payload: Partial<
    Pick<
      ExternalDisk,
      "dedicated_backup_disk" | "allow_existing_data" | "preferred_root_path" | "notes"
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
