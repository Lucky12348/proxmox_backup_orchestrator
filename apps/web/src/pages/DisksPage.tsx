import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { formatDateTime } from "../utils";
import type { DisksPageProps } from "./shared";

function CapacityBar({ used, total }: { used: number | null; total: number }) {
  const pct = used !== null ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const cls = pct >= 90 ? "danger" : pct >= 70 ? "warn" : "";

  return (
    <div className="cap-wrap">
      <div className="cap-nums">
        <span>{used ?? "?"} GB</span>
        <span>{total} GB</span>
      </div>
      <div className="cap-bar">
        <div className={`cap-fill ${cls}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function DisksPage({
  data,
  language,
  savingKey,
  t,
  onDiskToggleRequest,
  onExternalBackupRequest,
  onDiskEjectRequest,
}: DisksPageProps) {
  const activeExternalBackup = data.externalBackupRuns.find((run) => run.status === "pending" || run.status === "running");
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
                <th>{t.diskName}</th>
                <th>{t.diskConnected}</th>
                <th>{t.diskCapacity}</th>
                <th>{t.diskTrusted}</th>
                <th>{t.diskPbsVisible}</th>
                <th>{t.diskLastSeen}</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.disks.map((disk) => {
                const unusable = isUnusableDisk(disk);
                return (
                <tr key={disk.id}>
                  <td>
                    <div style={{ fontWeight: 500, color: "var(--t1)", fontSize: 13 }}>
                      {disk.display_name}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 2 }}>
                      {disk.serial_number}
                      {disk.model_name ? ` - ${disk.model_name}` : ""}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 4 }}>
                      <div>{t.diskCanonicalSerial}: {disk.canonical_serial_number ?? disk.serial_number}</div>
                      <div>{t.diskReportedSerial}: {disk.reported_serial_number ?? disk.serial_number}</div>
                      <div>{t.diskReportedModel}: {disk.reported_model_name ?? disk.model_name ?? t.notAvailable}</div>
                      <div>{t.diskReportedPath}: {disk.reported_mount_path ?? disk.mount_path ?? t.notAvailable}</div>
                      <div>{t.diskAliases}: {disk.serial_aliases?.join(", ") || t.notAvailable}</div>
                      {disk.candidate_type === "unusable" && disk.detection_reason ? (
                        <div style={{ color: "var(--danger)", marginTop: 4 }}>{disk.detection_reason}</div>
                      ) : null}
                    </div>
                  </td>
                  <td>
                    <StatusBadge tone={disk.connected ? "success" : "neutral"}>
                      {disk.connected ? t.connected : t.disconnected}
                    </StatusBadge>
                  </td>
                  <td>
                    <CapacityBar used={disk.usable_capacity_gb} total={disk.capacity_gb} />
                  </td>
                  <td>
                    <label className="toggle">
                      <input
                        type="checkbox"
                        checked={disk.trusted}
                        disabled={savingKey === `disk-${disk.id}` || unusable}
                        onChange={(event) =>
                          onDiskToggleRequest({
                            disk,
                            field: "trusted",
                            value: event.target.checked,
                          })
                        }
                      />
                      <span className="toggle-slider" />
                    </label>
                  </td>
                  <td>
                    <StatusBadge tone={disk.pbs_visible ? "success" : "neutral"}>
                      {disk.pbs_visible ? t.yes : t.no}
                    </StatusBadge>
                  </td>
                  <td style={{ fontSize: 12, color: "var(--t3)" }}>
                    {formatDateTime(disk.last_seen_at, language, t.notAvailable)}
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      <button
                        className="action-button"
                        disabled={savingKey === `external-backup-${disk.id}` || !disk.connected || unusable || Boolean(activeExternalBackup)}
                        onClick={() => {
                          if (activeExternalBackup) {
                            window.location.hash = "#activity";
                            return;
                          }
                          onExternalBackupRequest(disk);
                        }}
                        type="button"
                        style={{ fontSize: 11, padding: "0 10px", minHeight: 28 }}
                        title={unusable ? disk.detection_reason ?? undefined : activeExternalBackup ? "Un backup externe est deja en cours" : undefined}
                      >
                        {t.externalBackupAction}
                      </button>
                      <button
                        className="ghost-button"
                        disabled={savingKey === `disk-eject-${disk.id}` || !disk.connected}
                        onClick={() => onDiskEjectRequest(disk)}
                        type="button"
                        style={{ fontSize: 11, padding: "0 10px", minHeight: 28 }}
                      >
                        {savingKey === `disk-eject-${disk.id}` ? t.ejectingDisk : t.ejectDiskAction}
                      </button>
                    </div>
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </DataTable>
      )}
    </div>
  );
}

function isUnusableDisk(disk: DisksPageProps["data"]["disks"][number]) {
  return disk.capacity_gb <= 0 || disk.candidate_type === "unusable";
}
