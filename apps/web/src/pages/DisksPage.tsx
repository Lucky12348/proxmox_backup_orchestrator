import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { formatDateTime } from "../utils";
import type { DisksPageProps } from "./shared";

export function DisksPage({
  data,
  language,
  savingKey,
  t,
  onDiskToggleRequest,
  onDiskFieldChange,
  onExternalBackupRequest,
  onDiskPreparationRequest,
}: DisksPageProps) {
  return (
    <div className="page-stack">
      <PageHeader title={t.nav.disks} description={t.disksIntro} />

      {data.disks.length === 0 ? (
        <EmptyState description={t.disksEmptyDescription} title={t.emptyDisks} />
      ) : (
        <DataTable>
          <table>
            <thead>
              <tr>
                <th>{t.diskSerial}</th>
                <th>{t.diskName}</th>
                <th>{t.diskModel}</th>
                <th>{t.diskCapacity}</th>
                <th>{t.diskFilesystem}</th>
                <th>{t.diskMountPath}</th>
                <th>{t.diskConnected}</th>
                <th>{t.diskCandidateType}</th>
                <th>{t.diskDetectionReason}</th>
                <th>{t.diskTrusted}</th>
                <th>{t.diskDedicated}</th>
                <th>{t.diskAllowExistingData}</th>
                <th>{t.diskUsableCapacity}</th>
                <th>{t.diskReservedCapacity}</th>
                <th>{t.diskPlanningNotes}</th>
                <th>{t.prepareDiskAction}</th>
                <th>{t.externalBackupAction}</th>
                <th>{t.diskLastSeen}</th>
              </tr>
            </thead>
            <tbody>
              {data.disks.map((disk) => (
                <tr key={disk.id}>
                  <td>{disk.serial_number}</td>
                  <td>{disk.display_name}</td>
                  <td>{disk.model_name ?? t.notAvailable}</td>
                  <td>{disk.capacity_gb} GB</td>
                  <td>{disk.filesystem_type ?? t.notAvailable}</td>
                  <td>{disk.mount_path ?? t.notAvailable}</td>
                  <td>
                    <StatusBadge tone={disk.connected ? "success" : "neutral"}>
                      {disk.connected ? t.connected : t.disconnected}
                    </StatusBadge>
                  </td>
                  <td>{disk.candidate_type ?? t.notAvailable}</td>
                  <td>{disk.detection_reason ?? t.notAvailable}</td>
                  <td>
                    <label className="checkbox-cell">
                      <input
                        checked={disk.trusted}
                        disabled={savingKey === `disk-${disk.id}`}
                        onChange={(event) =>
                          onDiskToggleRequest({
                            disk,
                            field: "trusted",
                            value: event.target.checked,
                          })
                        }
                        type="checkbox"
                      />
                      <span>{disk.trusted ? t.yes : t.no}</span>
                    </label>
                  </td>
                  <td>
                    <label className="checkbox-cell">
                      <input
                        checked={disk.dedicated_backup_disk}
                        disabled={savingKey === `disk-${disk.id}`}
                        onChange={(event) =>
                          onDiskToggleRequest({
                            disk,
                            field: "dedicated_backup_disk",
                            value: event.target.checked,
                          })
                        }
                        type="checkbox"
                      />
                      <span>{disk.dedicated_backup_disk ? t.yes : t.no}</span>
                    </label>
                  </td>
                  <td>
                    <label className="checkbox-cell">
                      <input
                        checked={disk.allow_existing_data}
                        disabled={savingKey === `disk-${disk.id}`}
                        onChange={(event) =>
                          onDiskToggleRequest({
                            disk,
                            field: "allow_existing_data",
                            value: event.target.checked,
                          })
                        }
                        type="checkbox"
                      />
                      <span>{disk.allow_existing_data ? t.yes : t.no}</span>
                    </label>
                  </td>
                  <td>
                    <input
                      className="number-input"
                      defaultValue={disk.usable_capacity_gb ?? ""}
                      disabled={savingKey === `disk-${disk.id}`}
                      min={0}
                      onBlur={(event) =>
                        onDiskFieldChange(disk.id, {
                          usable_capacity_gb:
                            event.target.value === "" ? null : Number(event.target.value),
                        })
                      }
                      type="number"
                    />
                  </td>
                  <td>
                    <input
                      className="number-input"
                      defaultValue={disk.reserved_capacity_gb}
                      disabled={savingKey === `disk-${disk.id}`}
                      min={0}
                      onBlur={(event) =>
                        onDiskFieldChange(disk.id, {
                          reserved_capacity_gb: Number(event.target.value || 0),
                        })
                      }
                      type="number"
                    />
                  </td>
                  <td>
                    <input
                      className="text-input"
                      defaultValue={disk.planning_notes ?? ""}
                      disabled={savingKey === `disk-${disk.id}`}
                      onBlur={(event) =>
                        onDiskFieldChange(disk.id, {
                          planning_notes: event.target.value || null,
                        })
                      }
                      type="text"
                    />
                  </td>
                  <td>
                    <button
                      className="ghost-button"
                      disabled={savingKey === `disk-prep-${disk.id}`}
                      onClick={() => onDiskPreparationRequest(disk)}
                      type="button"
                    >
                      {savingKey === `disk-prep-${disk.id}` ? t.preparingDisk : t.prepareDiskAction}
                    </button>
                  </td>
                  <td>
                    <button
                      className="action-button"
                      disabled={savingKey === `external-backup-${disk.id}`}
                      onClick={() => onExternalBackupRequest(disk)}
                      type="button"
                    >
                      {t.externalBackupAction}
                    </button>
                  </td>
                  <td>{formatDateTime(disk.last_seen_at, language, t.notAvailable)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </DataTable>
      )}
    </div>
  );
}
