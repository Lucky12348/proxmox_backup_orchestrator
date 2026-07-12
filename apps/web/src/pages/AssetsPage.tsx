import { useMemo, useState } from "react";

import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { formatDateTime, getRuntimeTone, getSourceTone } from "../utils";
import type { AssetPageProps } from "./shared";

export function AssetsPage({
  data,
  language,
  pbsInventoryByVmId,
  isSaving,
  t,
  onAssetIgnoreChange,
  onBackupJobSelectionChange,
}: AssetPageProps) {
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | "vm" | "ct">("all");
  const [protectedFilter, setProtectedFilter] = useState<"all" | "protected" | "unprotected" | "ignored">(
    "all",
  );
  const [selectedJobId, setSelectedJobId] = useState<string>("");
  const [manageJobId, setManageJobId] = useState<string | null>(null);
  const [selectionDraft, setSelectionDraft] = useState<Set<number>>(new Set());

  const defaultJob = useMemo(() => {
    const enabledPbsJob = data.proxmoxBackupJobs.find((job) => job.enabled && job.storage === "pbs");
    return enabledPbsJob ?? data.proxmoxBackupJobs.find((job) => job.enabled) ?? data.proxmoxBackupJobs[0] ?? null;
  }, [data.proxmoxBackupJobs]);

  const targetJob = useMemo(() => {
    return data.proxmoxBackupJobs.find((job) => job.job_id === (selectedJobId || defaultJob?.job_id)) ?? defaultJob;
  }, [data.proxmoxBackupJobs, defaultJob, selectedJobId]);

  function vmidForAsset(vm: { external_id: string | null; id: number }) {
    const parsed = Number(vm.external_id ?? vm.id);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function openSelectionModal(jobId: string) {
    const job = data.proxmoxBackupJobs.find((item) => item.job_id === jobId);
    if (!job) return;
    setManageJobId(jobId);
    setSelectionDraft(new Set(job.selected_vmids));
  }

  function toggleSelection(vmid: number) {
    setSelectionDraft((current) => {
      const next = new Set(current);
      if (next.has(vmid)) next.delete(vmid);
      else next.add(vmid);
      return next;
    });
  }

  function saveSelection() {
    const job = data.proxmoxBackupJobs.find((item) => item.job_id === manageJobId);
    if (!job) return;
    if (!window.confirm(`Modifier la selection du job Proxmox ${job.schedule ?? ""}/${job.storage ?? ""} ?`)) {
      return;
    }
    onBackupJobSelectionChange(job.job_id, Array.from(selectionDraft).sort((a, b) => a - b));
    setManageJobId(null);
  }

  const filteredAssets = useMemo(() => {
    return data.vms.filter((vm) => {
      const backup = pbsInventoryByVmId.get(vm.id);
      const protectedState = backup?.protected ?? vm.last_backup_at !== null;
      const ignored = vm.ignored;

      if (typeFilter !== "all" && vm.vm_type !== typeFilter) {
        return false;
      }

      if (protectedFilter === "ignored" && !ignored) {
        return false;
      }

      if (protectedFilter === "protected" && (ignored || !protectedState)) {
        return false;
      }

      if (protectedFilter === "unprotected" && (ignored || protectedState)) {
        return false;
      }

      if (!query.trim()) {
        return true;
      }

      const normalized = query.trim().toLowerCase();
      return (
        vm.name.toLowerCase().includes(normalized) ||
        (vm.node_name ?? "").toLowerCase().includes(normalized) ||
        (vm.external_id ?? "").toLowerCase().includes(normalized)
      );
    });
  }, [data.vms, pbsInventoryByVmId, protectedFilter, query, typeFilter]);

  const managedJob = data.proxmoxBackupJobs.find((job) => job.job_id === manageJobId) ?? null;
  const selectableAssets = data.vms
    .map((vm) => ({ vm, vmid: vmidForAsset(vm) }))
    .filter((item): item is { vm: (typeof data.vms)[number]; vmid: number } => item.vmid !== null);

  return (
    <div className="page-stack">
      <PageHeader title={t.nav.assets} description={t.assetsIntro} />

      <section className="panel-card protection-jobs-card">
        <div className="panel-card-header">
          <h2>Jobs de sauvegarde Proxmox</h2>
          {data.proxmoxBackupJobs.length > 1 ? (
            <select
              className="compact-select"
              value={selectedJobId || defaultJob?.job_id || ""}
              onChange={(event) => setSelectedJobId(event.target.value)}
            >
              {data.proxmoxBackupJobs.map((job) => (
                <option key={job.job_id} value={job.job_id}>
                  {job.schedule ?? "sans planning"} / {job.storage ?? "stockage ?"}
                </option>
              ))}
            </select>
          ) : null}
        </div>
        {data.proxmoxBackupJobs.length === 0 ? (
          <p className="muted-text">Aucun job Proxmox existant disponible.</p>
        ) : (
          <div className="protection-job-list">
            {data.proxmoxBackupJobs.map((job) => (
              <article className="protection-job" key={job.job_id}>
                <div>
                  <div className="protection-job-title">
                    <StatusBadge tone={job.enabled ? "success" : "neutral"}>{job.enabled ? "Active" : "Desactive"}</StatusBadge>
                    <strong>{job.comment || `Job ${job.job_id}`}</strong>
                  </div>
                  <p className="muted-text">
                    {job.schedule ?? "sans planning"} - {job.storage ?? "stockage inconnu"} - {job.retention ?? "retention Proxmox"}
                  </p>
                  <p className="muted-text">{job.selected_vmids.length} VM/CT selectionnes</p>
                  {!job.supported ? <p className="form-error">{job.unsupported_reason}</p> : null}
                </div>
                <button
                  className="action-button secondary"
                  disabled={!job.supported || isSaving(`backup-job-${job.job_id}`)}
                  onClick={() => openSelectionModal(job.job_id)}
                  type="button"
                >
                  Gerer la selection
                </button>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="filters-bar">
        <label className="field">
          <span>{t.search}</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>

        <label className="field">
          <span>{t.filterType}</span>
          <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as "all" | "vm" | "ct")}>
            <option value="all">{t.all}</option>
            <option value="vm">VM</option>
            <option value="ct">CT</option>
          </select>
        </label>

        <label className="field">
          <span>{t.filterProtection}</span>
          <select
            value={protectedFilter}
            onChange={(event) =>
              setProtectedFilter(event.target.value as "all" | "protected" | "unprotected" | "ignored")
            }
          >
            <option value="all">{t.all}</option>
            <option value="protected">{t.filterProtected}</option>
            <option value="unprotected">{t.filterUnprotected}</option>
            <option value="ignored">Ignores</option>
          </select>
        </label>
      </section>

      {filteredAssets.length === 0 ? (
        <EmptyState description={t.assetsEmptyDescription} title={t.emptyVms} />
      ) : (
        <DataTable>
          <table>
            <thead>
              <tr>
                <th>{t.vmName}</th>
                <th>{t.vmType}</th>
                <th>{t.vmSource}</th>
                <th>{t.vmNode}</th>
                <th>{t.vmRuntimeStatus}</th>
                <th>{t.vmProtected}</th>
                <th>Ignorer</th>
                <th>{t.vmSize}</th>
                <th>{t.vmLastBackup}</th>
                <th>Job Proxmox</th>
              </tr>
            </thead>
            <tbody>
              {filteredAssets.map((vm) => {
                const backup = pbsInventoryByVmId.get(vm.id);
                const protectedState = backup?.protected ?? vm.last_backup_at !== null;
                const lastBackup = backup?.last_backup_at ?? vm.last_backup_at;

                const ignored = vm.ignored;
                const vmid = vmidForAsset(vm);
                const includedInTarget = targetJob && vmid !== null ? targetJob.selected_vmids.includes(vmid) : false;

                return (
                  <tr className={ignored ? "asset-row-ignored" : ""} key={vm.id}>
                    <td>
                      <div className="asset-name-cell">
                        <span>{vm.name}</span>
                        {ignored ? <StatusBadge tone="neutral">Ignore</StatusBadge> : null}
                      </div>
                    </td>
                    <td>
                      <span className={vm.vm_type === "vm" ? "type-pill vm-pill" : "type-pill ct-pill"}>
                        {vm.vm_type.toUpperCase()}
                      </span>
                    </td>
                    <td>
                      <StatusBadge tone={getSourceTone(vm.source)}>
                        {t.source[vm.source]}
                      </StatusBadge>
                    </td>
                    <td>{vm.node_name ?? t.notAvailable}</td>
                    <td>
                      <StatusBadge tone={getRuntimeTone(vm.runtime_status)}>
                        {vm.runtime_status ?? t.notAvailable}
                      </StatusBadge>
                    </td>
                    <td>
                      <StatusBadge tone={protectedState ? "success" : "warning"}>
                        {protectedState ? t.protectedLabel : t.unprotectedLabel}
                      </StatusBadge>
                    </td>
                    <td>
                      <label className="toggle" title={ignored ? "Ne plus ignorer cet actif" : "Ignorer cet actif"}>
                        <input
                          type="checkbox"
                          checked={ignored}
                          disabled={isSaving(`vm-ignore-${vm.id}`)}
                          onChange={(event) => onAssetIgnoreChange(vm, event.target.checked)}
                        />
                        <span className="toggle-slider" />
                      </label>
                    </td>
                    <td>{vm.size_gb} GB</td>
                    <td>{formatDateTime(lastBackup, language, t.notAvailable)}</td>
                    <td>
                      {targetJob && vmid !== null ? (
                        <button
                          className="tiny-action"
                          disabled={!targetJob.supported || isSaving(`backup-job-${targetJob.job_id}`)}
                          onClick={() => {
                            const next = includedInTarget
                              ? targetJob.selected_vmids.filter((item) => item !== vmid)
                              : [...targetJob.selected_vmids, vmid];
                            onBackupJobSelectionChange(targetJob.job_id, next);
                          }}
                          type="button"
                        >
                          {includedInTarget ? "Retirer du job" : "Inclure dans le job"}
                        </button>
                      ) : t.notAvailable}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </DataTable>
      )}

      {managedJob ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <section className="modal-card selection-modal">
            <div className="modal-header">
              <h2 className="page-title">Gerer la selection</h2>
              <button className="icon-button" onClick={() => setManageJobId(null)} type="button">x</button>
            </div>
            <p className="modal-description">
              Job {managedJob.schedule ?? "sans planning"} / {managedJob.storage ?? "stockage inconnu"}.
              Seule la liste des VMID selectionnes sera modifiee.
            </p>
            <div className="selection-grid">
              {selectableAssets.map(({ vm, vmid }) => {
                const selected = selectionDraft.has(vmid);
                return (
                  <label className={`selection-row ${vm.ignored ? "asset-row-ignored" : ""}`} key={`${vm.source}-${vm.node_name}-${vmid}`}>
                    <input checked={selected} onChange={() => toggleSelection(vmid)} type="checkbox" />
                    <span className="selection-main">
                      <strong>{vm.name}</strong>
                      <small>{vm.node_name ?? t.notAvailable} - VMID {vmid}</small>
                    </span>
                    {vm.ignored ? <StatusBadge tone="neutral">Ignore</StatusBadge> : null}
                  </label>
                );
              })}
            </div>
            <div className="modal-actions">
              <button className="secondary-button" onClick={() => setManageJobId(null)} type="button">{t.cancel}</button>
              <button className="action-button" onClick={saveSelection} type="button">Enregistrer</button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
