import { useMemo, useState } from "react";

import {
  cancelScheduledBackupRun,
  confirmScheduledBackupRun,
  createScheduledBackupEvent,
  deleteScheduledBackupEvent,
  getScheduledBackupEvents,
  getScheduledBackupRuns,
  runScheduledBackupNow,
  updateScheduledBackupEvent,
} from "../api";
import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { ErrorBanner } from "../components/ErrorBanner";
import { PageHeader } from "../components/PageHeader";
import { StatCard } from "../components/StatCard";
import { StatusBadge } from "../components/StatusBadge";
import type { ScheduledBackupEvent, ScheduledBackupEventPayload, ScheduledBackupRun } from "../types";
import type { PlanningPageProps } from "./shared";

type EventForm = ScheduledBackupEventPayload & { id?: number };

const DEFAULT_FORM: EventForm = {
  title: "Backup externe hebdomadaire",
  enabled: true,
  disk_serial: "",
  disk_label_or_model: "",
  datastore: "backup-store",
  recurrence_type: "weekly",
  recurrence_config: null,
  timezone: "Europe/Paris",
  window_starts_at: "",
  window_duration_minutes: 300,
  notify_before_minutes: 60,
  start_mode: "manual_confirmation",
  auto_eject_after_success: false,
};

export function PlanningPage({ data, t }: PlanningPageProps) {
  const [events, setEvents] = useState(data.scheduledBackupEvents);
  const [runs, setRuns] = useState(data.scheduledBackupRuns);
  const [form, setForm] = useState<EventForm | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ message: string; tone: "info" | "error" } | null>(null);

  const calendarDays = useMemo(() => buildCalendarDays(events), [events]);
  const upcomingRuns = runs.slice().sort((a, b) => a.window_starts_at.localeCompare(b.window_starts_at)).slice(0, 8);

  async function refreshPlanning() {
    const [nextEvents, nextRuns] = await Promise.all([getScheduledBackupEvents(), getScheduledBackupRuns()]);
    setEvents(nextEvents);
    setRuns(nextRuns);
  }

  function newEvent() {
    const firstDisk = data.disks[0];
    setForm({
      ...DEFAULT_FORM,
      disk_serial: firstDisk?.serial_number ?? "",
      disk_label_or_model: firstDisk ? `${firstDisk.display_name} / ${firstDisk.model_name ?? firstDisk.serial_number}` : "",
      datastore: data.pbsStatus.datastore,
      window_starts_at: toLocalInputValue(nextSundayAtOne()),
    });
  }

  function editEvent(event: ScheduledBackupEvent) {
    setForm({
      title: event.title,
      enabled: event.enabled,
      disk_serial: event.disk_serial,
      disk_label_or_model: event.disk_label_or_model,
      datastore: event.datastore,
      recurrence_type: event.recurrence_type,
      recurrence_config: event.recurrence_config,
      timezone: event.timezone,
      window_starts_at: toLocalInputValue(event.window_starts_at),
      window_duration_minutes: event.window_duration_minutes,
      notify_before_minutes: event.notify_before_minutes,
      start_mode: event.start_mode,
      auto_eject_after_success: event.auto_eject_after_success,
      id: event.id,
    });
  }

  async function saveEvent() {
    if (!form) return;
    setBusy("save-event");
    setBanner(null);
    const payload: ScheduledBackupEventPayload = {
      ...form,
      window_starts_at: new Date(form.window_starts_at).toISOString(),
    };
    delete (payload as Partial<EventForm>).id;
    try {
      if (form.id) await updateScheduledBackupEvent(form.id, payload);
      else await createScheduledBackupEvent(payload);
      setForm(null);
      await refreshPlanning();
      setBanner({ message: "Planning sauvegarde.", tone: "info" });
    } catch (error) {
      setBanner({ message: error instanceof Error ? error.message : "Unknown error", tone: "error" });
    } finally {
      setBusy(null);
    }
  }

  async function action(label: string, callback: () => Promise<unknown>) {
    setBusy(label);
    setBanner(null);
    try {
      await callback();
      await refreshPlanning();
    } catch (error) {
      setBanner({ message: error instanceof Error ? error.message : "Unknown error", tone: "error" });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="page-stack">
      <PageHeader title={t.nav.planning} description="Calendrier des sauvegardes externes et capacite planifiee." />

      {banner ? <ErrorBanner dismissLabel={t.dismiss} message={banner.message} onDismiss={() => setBanner(null)} tone={banner.tone} /> : null}

      <section className="stats-grid stats-grid-compact">
        <StatCard label={t.planningCoverage} value={`${data.planningOverview.planning_coverage_percent}%`} />
        <StatCard label="Evenements actifs" value={events.filter((event) => event.enabled).length} />
        <StatCard label="Runs en attente" value={runs.filter((run) => ["pending", "waiting_for_disk", "waiting_for_confirmation", "running"].includes(run.status)).length} />
      </section>

      <section className="panel-card">
        <div className="panel-card-header">
          <h2>Agenda</h2>
          <button className="action-button" onClick={newEvent} type="button">Nouvel evenement</button>
        </div>
        <div className="calendar-grid">
          {calendarDays.map((day) => (
            <div className="calendar-day" key={day.date}>
              <div className="calendar-day-number">{day.label}</div>
              {day.events.map((event) => (
                <button className="calendar-event" key={event.id} onClick={() => editEvent(event)} type="button">
                  {event.title}
                </button>
              ))}
            </div>
          ))}
        </div>
      </section>

      <section className="panel-card">
        <div className="panel-card-header">
          <h2>Evenements planifies</h2>
        </div>
        {events.length === 0 ? (
          <EmptyState description="Creez un evenement pour associer une fenetre de backup a un disque exact." title="Aucun backup planifie" />
        ) : (
          <DataTable>
            <table>
              <thead>
                <tr>
                  <th>Titre</th>
                  <th>Disque</th>
                  <th>Prochaine occurrence</th>
                  <th>Mode</th>
                  <th>Dernier statut</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.id}>
                    <td>{event.title}</td>
                    <td>{event.disk_label_or_model || event.disk_serial}</td>
                    <td>{formatDate(event.next_occurrence_at)}</td>
                    <td>{event.start_mode === "auto_on_disk_detected" ? "Auto detection" : "Confirmation"}</td>
                    <td><RunStatusBadge status={event.active_run?.status ?? event.last_status ?? "pending"} /></td>
                    <td>
                      <div className="button-row">
                        <button className="ghost-button" onClick={() => editEvent(event)} type="button">Editer</button>
                        <button className="ghost-button" disabled={busy === `run-${event.id}`} onClick={() => void action(`run-${event.id}`, () => runScheduledBackupNow(event.id))} type="button">Run now</button>
                        <button className="ghost-button" onClick={() => void action(`toggle-${event.id}`, () => updateScheduledBackupEvent(event.id, { enabled: !event.enabled }))} type="button">{event.enabled ? "Desactiver" : "Activer"}</button>
                        <button className="danger-button" onClick={() => void action(`delete-${event.id}`, () => deleteScheduledBackupEvent(event.id))} type="button">Supprimer</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </DataTable>
        )}
      </section>

      <section className="panel-card">
        <div className="panel-card-header">
          <h2>Runs planifies</h2>
        </div>
        <DataTable>
          <table>
            <thead>
              <tr>
                <th>Evenement</th>
                <th>Fenetre</th>
                <th>Statut</th>
                <th>Backup</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {upcomingRuns.map((run) => (
                <tr key={run.id}>
                  <td>{run.event_title ?? run.event_id}</td>
                  <td>{formatDate(run.window_starts_at)} {"->"} {formatDate(run.window_ends_at)}</td>
                  <td><RunStatusBadge status={run.status} /></td>
                  <td>{run.backup_run_id ? `#${run.backup_run_id}` : t.notAvailable}</td>
                  <td>
                    <div className="button-row">
                      <button className="ghost-button" disabled={run.status !== "waiting_for_confirmation"} onClick={() => void action(`confirm-${run.id}`, () => confirmScheduledBackupRun(run.id))} type="button">Confirmer</button>
                      <button className="ghost-button" disabled={["success", "failure", "missed", "cancelled"].includes(run.status)} onClick={() => void action(`cancel-${run.id}`, () => cancelScheduledBackupRun(run.id))} type="button">Annuler</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </DataTable>
      </section>

      {form ? (
        <div className="modal-backdrop">
          <div className="modal-card planning-modal">
            <div className="panel-card-header">
              <h2>{form.id ? "Modifier evenement" : "Nouvel evenement"}</h2>
              <button className="ghost-button" onClick={() => setForm(null)} type="button">{t.cancel}</button>
            </div>
            <div className="planning-form-grid">
              <label>Titre<input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
              <label>Disque<select value={form.disk_serial} onChange={(e) => {
                const disk = data.disks.find((item) => item.serial_number === e.target.value);
                setForm({ ...form, disk_serial: e.target.value, disk_label_or_model: disk ? `${disk.display_name} / ${disk.model_name ?? disk.serial_number}` : e.target.value });
              }}>
                {data.disks.map((disk) => <option key={disk.serial_number} value={disk.serial_number}>{disk.display_name} - {disk.serial_number}</option>)}
              </select></label>
              <label>Datastore<input value={form.datastore} onChange={(e) => setForm({ ...form, datastore: e.target.value })} /></label>
              <label>Recurrence<select value={form.recurrence_type} onChange={(e) => setForm({ ...form, recurrence_type: e.target.value as EventForm["recurrence_type"] })}>
                <option value="once">Une fois</option>
                <option value="daily">Tous les jours</option>
                <option value="weekly">Chaque semaine</option>
                <option value="monthly">Chaque mois</option>
              </select></label>
              <label>Debut fenetre<input type="datetime-local" value={form.window_starts_at} onChange={(e) => setForm({ ...form, window_starts_at: e.target.value })} /></label>
              <label>Duree minutes<input type="number" min={1} value={form.window_duration_minutes} onChange={(e) => setForm({ ...form, window_duration_minutes: Number(e.target.value) })} /></label>
              <label>Rappel minutes avant<input type="number" min={0} value={form.notify_before_minutes} onChange={(e) => setForm({ ...form, notify_before_minutes: Number(e.target.value) })} /></label>
              <label>Mode demarrage<select value={form.start_mode} onChange={(e) => setForm({ ...form, start_mode: e.target.value as EventForm["start_mode"] })}>
                <option value="manual_confirmation">Confirmation manuelle</option>
                <option value="auto_on_disk_detected">Automatique sur detection disque</option>
              </select></label>
              <label className="checkbox-row"><input checked={form.auto_eject_after_success} onChange={(e) => setForm({ ...form, auto_eject_after_success: e.target.checked })} type="checkbox" /> Auto-eject apres succes</label>
              <label className="checkbox-row"><input checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} type="checkbox" /> Active</label>
            </div>
            <div className="button-row">
              <button className="action-button" disabled={busy === "save-event" || !form.disk_serial || !form.window_starts_at} onClick={() => void saveEvent()} type="button">{t.confirm}</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function RunStatusBadge({ status }: { status: string }) {
  const tone = status === "success" ? "success" : status === "failure" || status === "missed" ? "danger" : status === "running" ? "info" : "warning";
  return <StatusBadge tone={tone}>{status}</StatusBadge>;
}

function buildCalendarDays(events: ScheduledBackupEvent[]) {
  const now = new Date();
  const first = new Date(now.getFullYear(), now.getMonth(), 1);
  return Array.from({ length: 35 }, (_, index) => {
    const date = new Date(first);
    date.setDate(first.getDate() + index);
    const key = date.toISOString().slice(0, 10);
    return {
      date: key,
      label: String(date.getDate()),
      events: events.filter((event) => (event.next_occurrence_at ?? event.window_starts_at).slice(0, 10) === key),
    };
  });
}

function nextSundayAtOne() {
  const date = new Date();
  date.setDate(date.getDate() + ((7 - date.getDay()) % 7 || 7));
  date.setHours(1, 0, 0, 0);
  return date;
}

function toLocalInputValue(value: string | Date) {
  const date = value instanceof Date ? value : new Date(value);
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function formatDate(value: string | null) {
  if (!value) return "N/A";
  return new Date(value).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}
