import { useMemo, useState } from "react";

import {
  createProxmoxBackupJob,
  deleteProxmoxBackupJob,
  replaceProxmoxBackupJob,
} from "../api";
import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import type { ProxmoxBackupJob, ProxmoxBackupJobFormValues } from "../types";
import { formatDateTime, getRuntimeTone, getSourceTone } from "../utils";
import type { AssetPageProps } from "./shared";

const DAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
type DayCode = (typeof DAY_CODES)[number];
const DAY_LABELS: Record<DayCode, string> = {
  mon: "Lun",
  tue: "Mar",
  wed: "Mer",
  thu: "Jeu",
  fri: "Ven",
  sat: "Sam",
  sun: "Dim",
};

interface JobFormState {
  mode: "create" | "edit";
  jobId: string | null;
  storage: string;
  scheduleDays: Set<DayCode>;
  scheduleTime: string;
  node: string;
  jobMode: string;
  enabled: boolean;
  comment: string;
  keepLast: string;
  keepDaily: string;
  keepWeekly: string;
  keepMonthly: string;
  keepYearly: string;
  selectedVmids: Set<number>;
}

function blankJobForm(): Omit<JobFormState, "mode" | "jobId" | "selectedVmids"> {
  return {
    storage: "",
    scheduleDays: new Set(DAY_CODES),
    scheduleTime: "03:00",
    node: "",
    jobMode: "snapshot",
    enabled: true,
    comment: "",
    keepLast: "",
    keepDaily: "",
    keepWeekly: "",
    keepMonthly: "",
    keepYearly: "",
  };
}

function parseRetention(retention: string | null): Record<string, string> {
  const parsed: Record<string, string> = {};
  if (!retention) return parsed;
  for (const part of retention.split(",")) {
    const [key, value] = part.split("=");
    if (key && value) parsed[key.trim()] = value.trim();
  }
  return parsed;
}

// Proxmox schedules are systemd-style calendar events; this only understands
// (and only ever produces) the common "day1,day2,... HH:MM" shape shown in
// Proxmox's own job editor — anything else falls back to every day at 03:00
// rather than guessing, and the raw value stays visible via the job list.
function parseSchedule(schedule: string | null): { days: Set<DayCode>; time: string } {
  const fallback = { days: new Set<DayCode>(DAY_CODES), time: "03:00" };
  const match = schedule?.trim().match(/^([a-z,]+)\s+(\d{1,2}:\d{2})$/i);
  if (!match) return fallback;
  const days = new Set<DayCode>();
  for (const token of match[1].toLowerCase().split(",")) {
    if ((DAY_CODES as readonly string[]).includes(token)) days.add(token as DayCode);
  }
  return { days: days.size > 0 ? days : fallback.days, time: match[2] };
}

function buildSchedule(days: Set<DayCode>, time: string): string {
  const ordered = DAY_CODES.filter((day) => days.has(day));
  const dayPart = ordered.length === 0 || ordered.length === DAY_CODES.length ? DAY_CODES.join(",") : ordered.join(",");
  return `${dayPart} ${time || "03:00"}`;
}

function jobFormFromExisting(job: ProxmoxBackupJob): JobFormState {
  const retention = parseRetention(job.retention);
  const schedule = parseSchedule(job.schedule);
  return {
    mode: "edit",
    jobId: job.job_id,
    storage: job.storage ?? "",
    scheduleDays: schedule.days,
    scheduleTime: schedule.time,
    node: job.node ?? "",
    jobMode: "snapshot",
    enabled: job.enabled,
    comment: job.comment ?? "",
    keepLast: retention["keep-last"] ?? "",
    keepDaily: retention["keep-daily"] ?? "",
    keepWeekly: retention["keep-weekly"] ?? "",
    keepMonthly: retention["keep-monthly"] ?? "",
    keepYearly: retention["keep-yearly"] ?? "",
    selectedVmids: new Set(job.selected_vmids),
  };
}

function toFormValues(form: JobFormState): ProxmoxBackupJobFormValues {
  const toOptionalInt = (value: string) => (value.trim() === "" ? null : Number(value));
  return {
    storage: form.storage.trim(),
    schedule: buildSchedule(form.scheduleDays, form.scheduleTime),
    node: form.node.trim() || null,
    selected_vmids: Array.from(form.selectedVmids).sort((a, b) => a - b),
    mode: form.jobMode,
    enabled: form.enabled,
    comment: form.comment.trim() || null,
    keep_last: toOptionalInt(form.keepLast),
    keep_daily: toOptionalInt(form.keepDaily),
    keep_weekly: toOptionalInt(form.keepWeekly),
    keep_monthly: toOptionalInt(form.keepMonthly),
    keep_yearly: toOptionalInt(form.keepYearly),
  };
}

export function AssetsPage({
  data,
  language,
  pbsInventoryByVmId,
  isSaving,
  t,
  onAssetIgnoreChange,
  onBackupJobSelectionChange,
  onRefresh,
}: AssetPageProps) {
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | "vm" | "ct">("all");
  const [protectedFilter, setProtectedFilter] = useState<"all" | "protected" | "unprotected" | "ignored">(
    "all",
  );
  const [selectedJobId, setSelectedJobId] = useState<string>("");
  const [manageJobId, setManageJobId] = useState<string | null>(null);
  const [selectionDraft, setSelectionDraft] = useState<Set<number>>(new Set());
  const [jobForm, setJobForm] = useState<JobFormState | null>(null);
  const [jobFormError, setJobFormError] = useState<string | null>(null);
  const [jobFormSaving, setJobFormSaving] = useState(false);
  const [jobDeleting, setJobDeleting] = useState<string | null>(null);

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

  function openCreateJobForm() {
    setJobFormError(null);
    setJobForm({ mode: "create", jobId: null, selectedVmids: new Set(), ...blankJobForm() });
  }

  function openEditJobForm(job: ProxmoxBackupJob) {
    setJobFormError(null);
    setJobForm(jobFormFromExisting(job));
  }

  function closeJobForm() {
    setJobForm(null);
    setJobFormError(null);
  }

  function updateJobForm(patch: Partial<JobFormState>) {
    setJobForm((current) => (current ? { ...current, ...patch } : current));
  }

  function toggleScheduleDay(day: DayCode) {
    setJobForm((current) => {
      if (!current) return current;
      const next = new Set(current.scheduleDays);
      if (next.has(day)) next.delete(day);
      else next.add(day);
      return { ...current, scheduleDays: next };
    });
  }

  function toggleJobFormVmid(vmid: number) {
    setJobForm((current) => {
      if (!current) return current;
      const next = new Set(current.selectedVmids);
      if (next.has(vmid)) next.delete(vmid);
      else next.add(vmid);
      return { ...current, selectedVmids: next };
    });
  }

  async function submitJobForm() {
    if (!jobForm) return;
    if (!jobForm.storage.trim() || !jobForm.scheduleTime.trim()) {
      setJobFormError("Le stockage et l'heure de planification sont obligatoires.");
      return;
    }
    if (jobForm.selectedVmids.size === 0) {
      setJobFormError("Selectionnez au moins une VM/CT pour ce job.");
      return;
    }

    setJobFormError(null);
    setJobFormSaving(true);
    try {
      const values = toFormValues(jobForm);
      if (jobForm.mode === "create") {
        await createProxmoxBackupJob(values);
      } else if (jobForm.jobId) {
        await replaceProxmoxBackupJob(jobForm.jobId, values);
      }
      await onRefresh();
      setJobForm(null);
    } catch (submitError) {
      setJobFormError(submitError instanceof Error ? submitError.message : "Erreur inconnue.");
    } finally {
      setJobFormSaving(false);
    }
  }

  async function requestDeleteJob(job: ProxmoxBackupJob) {
    if (!window.confirm(`Supprimer definitivement le job Proxmox ${job.schedule ?? ""} / ${job.storage ?? ""} ?`)) {
      return;
    }
    setJobDeleting(job.job_id);
    try {
      await deleteProxmoxBackupJob(job.job_id);
      await onRefresh();
    } catch (deleteError) {
      window.alert(deleteError instanceof Error ? deleteError.message : "Erreur inconnue lors de la suppression.");
    } finally {
      setJobDeleting(null);
    }
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
          <button className="action-button" onClick={openCreateJobForm} type="button">
            + Nouveau job
          </button>
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
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  <button
                    className="action-button secondary"
                    disabled={!job.supported || isSaving(`backup-job-${job.job_id}`)}
                    onClick={() => openSelectionModal(job.job_id)}
                    type="button"
                  >
                    Gerer la selection
                  </button>
                  <button
                    className="ghost-button"
                    onClick={() => openEditJobForm(job)}
                    type="button"
                  >
                    Modifier
                  </button>
                  <button
                    className="ghost-button action-danger"
                    disabled={jobDeleting === job.job_id}
                    onClick={() => void requestDeleteJob(job)}
                    type="button"
                  >
                    {jobDeleting === job.job_id ? "Suppression..." : "Supprimer"}
                  </button>
                </div>
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

      {jobForm ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <section className="modal-card selection-modal">
            <div className="modal-header">
              <h2 className="page-title">
                {jobForm.mode === "create" ? "Nouveau job de sauvegarde Proxmox" : "Modifier le job"}
              </h2>
              <button className="icon-button" onClick={closeJobForm} type="button">x</button>
            </div>
            <p className="modal-description">
              Champs de base uniquement (noeud, stockage, planning, VM, retention simple). Pour les
              notifications, le modele de note ou les options avancees, utilise directement Proxmox.
            </p>

            <div className="job-form-grid">
              <label className="field">
                <span>Stockage *</span>
                <input
                  onChange={(event) => updateJobForm({ storage: event.target.value })}
                  placeholder="pbs"
                  value={jobForm.storage}
                />
              </label>
              <label className="field">
                <span>Noeud (vide = tous)</span>
                <input
                  onChange={(event) => updateJobForm({ node: event.target.value })}
                  placeholder="promox"
                  value={jobForm.node}
                />
              </label>
              <div className="field" style={{ gridColumn: "1 / -1" }}>
                <span>Planning *</span>
                <div className="schedule-picker">
                  <div className="schedule-days">
                    {DAY_CODES.map((day) => (
                      <button
                        className={`day-toggle${jobForm.scheduleDays.has(day) ? " day-toggle-active" : ""}`}
                        key={day}
                        onClick={() => toggleScheduleDay(day)}
                        type="button"
                      >
                        {DAY_LABELS[day]}
                      </button>
                    ))}
                  </div>
                  <input
                    onChange={(event) => updateJobForm({ scheduleTime: event.target.value })}
                    type="time"
                    value={jobForm.scheduleTime}
                  />
                </div>
              </div>
              <label className="field">
                <span>Mode</span>
                <select
                  onChange={(event) => updateJobForm({ jobMode: event.target.value })}
                  value={jobForm.jobMode}
                >
                  <option value="snapshot">Snapshot</option>
                  <option value="suspend">Suspend</option>
                  <option value="stop">Stop</option>
                </select>
              </label>
              <label className="field">
                <span>Commentaire</span>
                <input
                  onChange={(event) => updateJobForm({ comment: event.target.value })}
                  value={jobForm.comment}
                />
              </label>
              <label className="toggle-field">
                <input
                  checked={jobForm.enabled}
                  onChange={(event) => updateJobForm({ enabled: event.target.checked })}
                  type="checkbox"
                />
                <span>Job actif</span>
              </label>
            </div>

            <div className="retention-row">
              <span className="retention-label">Retention (vide = illimite) :</span>
              <label className="retention-field">
                <span>Dernier</span>
                <input
                  inputMode="numeric"
                  onChange={(event) => updateJobForm({ keepLast: event.target.value })}
                  value={jobForm.keepLast}
                />
              </label>
              <label className="retention-field">
                <span>Jour</span>
                <input
                  inputMode="numeric"
                  onChange={(event) => updateJobForm({ keepDaily: event.target.value })}
                  value={jobForm.keepDaily}
                />
              </label>
              <label className="retention-field">
                <span>Semaine</span>
                <input
                  inputMode="numeric"
                  onChange={(event) => updateJobForm({ keepWeekly: event.target.value })}
                  value={jobForm.keepWeekly}
                />
              </label>
              <label className="retention-field">
                <span>Mois</span>
                <input
                  inputMode="numeric"
                  onChange={(event) => updateJobForm({ keepMonthly: event.target.value })}
                  value={jobForm.keepMonthly}
                />
              </label>
              <label className="retention-field">
                <span>Annee</span>
                <input
                  inputMode="numeric"
                  onChange={(event) => updateJobForm({ keepYearly: event.target.value })}
                  value={jobForm.keepYearly}
                />
              </label>
            </div>

            <p className="modal-description" style={{ marginTop: 16 }}>
              VM/CT a sauvegarder ({jobForm.selectedVmids.size} selectionnes) :
            </p>
            <div className="selection-grid">
              {selectableAssets.map(({ vm, vmid }) => {
                const selected = jobForm.selectedVmids.has(vmid);
                return (
                  <label className={`selection-row ${vm.ignored ? "asset-row-ignored" : ""}`} key={`job-form-${vm.source}-${vm.node_name}-${vmid}`}>
                    <input checked={selected} onChange={() => toggleJobFormVmid(vmid)} type="checkbox" />
                    <span className="selection-main">
                      <strong>{vm.name}</strong>
                      <small>{vm.node_name ?? t.notAvailable} - VMID {vmid}</small>
                    </span>
                    {vm.ignored ? <StatusBadge tone="neutral">Ignore</StatusBadge> : null}
                  </label>
                );
              })}
            </div>

            {jobFormError ? <p className="form-error">{jobFormError}</p> : null}

            <div className="modal-actions">
              <button className="secondary-button" onClick={closeJobForm} type="button">{t.cancel}</button>
              <button className="action-button" disabled={jobFormSaving} onClick={() => void submitJobForm()} type="button">
                {jobFormSaving ? "Enregistrement..." : "Enregistrer"}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
