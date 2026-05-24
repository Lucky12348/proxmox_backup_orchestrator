import { useEffect, useMemo, useState } from "react";

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
import type {
  ExternalDisk,
  ScheduledBackupEvent,
  ScheduledBackupEventPayload,
  ScheduledBackupRun,
  ScheduledBackupRunStatus,
} from "../types";
import type { PlanningPageProps } from "./shared";

type EventForm = ScheduledBackupEventPayload & { id?: number };
type CalendarOccurrence = {
  key: string;
  event: ScheduledBackupEvent;
  startsAt: string;
  endsAt: string;
  run: ScheduledBackupRun | null;
};

const ACTIVE_STATUSES = new Set(["pending", "waiting_for_disk", "waiting_for_confirmation", "running"]);
const DONE_STATUSES = new Set(["success", "failure", "missed", "cancelled"]);

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
  const [visibleMonth, setVisibleMonth] = useState(startOfMonth(new Date()));
  const [form, setForm] = useState<EventForm | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ message: string; tone: "info" | "error" } | null>(null);

  useEffect(() => {
    setEvents(data.scheduledBackupEvents);
    setRuns(data.scheduledBackupRuns);
  }, [data.scheduledBackupEvents, data.scheduledBackupRuns]);

  useEffect(() => {
    let cancelled = false;
    const intervalId = window.setInterval(() => {
      void refreshPlanning({ silent: true, cancelled: () => cancelled });
    }, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, []);

  const monthRange = useMemo(() => calendarRange(visibleMonth), [visibleMonth]);
  const occurrences = useMemo(
    () => expandVisibleOccurrences(events, runs, monthRange.start, monthRange.end),
    [events, runs, monthRange.start, monthRange.end],
  );
  const calendarDays = useMemo(() => buildCalendarDays(monthRange.start, occurrences), [monthRange.start, occurrences]);
  const activeRuns = runs.filter((run) => ACTIVE_STATUSES.has(run.status)).sort(sortRunsAsc);
  const historyRuns = runs.filter((run) => DONE_STATUSES.has(run.status)).sort(sortRunsDesc).slice(0, 12);
  const upcomingRuns = runs.filter((run) => !DONE_STATUSES.has(run.status)).sort(sortRunsAsc).slice(0, 12);
  const nextOccurrence = occurrences.filter((item) => new Date(item.startsAt) >= new Date()).sort((a, b) => a.startsAt.localeCompare(b.startsAt))[0] ?? null;
  const lastRun = runs.slice().sort(sortRunsDesc)[0] ?? null;

  async function refreshPlanning(options: { silent?: boolean; cancelled?: () => boolean } = {}) {
    try {
      const [nextEvents, nextRuns] = await Promise.all([getScheduledBackupEvents(), getScheduledBackupRuns()]);
      if (options.cancelled?.()) return;
      setEvents(nextEvents);
      setRuns(nextRuns);
    } catch (error) {
      if (!options.silent) setBanner({ message: error instanceof Error ? error.message : "Unknown error", tone: "error" });
    }
  }

  function newEvent() {
    const firstDisk = data.disks[0];
    setForm({
      ...DEFAULT_FORM,
      disk_serial: firstDisk?.serial_number ?? "",
      disk_label_or_model: firstDisk ? diskLabel(firstDisk) : "",
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

  async function deleteEvent(event: ScheduledBackupEvent) {
    const confirmed = window.confirm("Supprimer cet evenement ? L'historique des runs sera conserve.");
    if (!confirmed) return;
    await action(`delete-${event.id}`, () => deleteScheduledBackupEvent(event.id));
  }

  return (
    <div className="page-stack">
      <PageHeader title={t.nav.planning} description="Calendrier des sauvegardes externes et capacite planifiee." />

      {banner ? <ErrorBanner dismissLabel={t.dismiss} message={banner.message} onDismiss={() => setBanner(null)} tone={banner.tone} /> : null}

      <section className="stats-grid stats-grid-compact">
        <StatCard label="Prochain backup" value={nextOccurrence ? formatDate(nextOccurrence.startsAt) : "Aucun"} />
        <StatCard label="Actif maintenant" value={activeRuns[0] ? `${activeRuns[0].event_title ?? activeRuns[0].event_id}: ${activeRuns[0].status}` : "Aucun"} />
        <StatCard label="Dernier run" value={lastRun ? `${lastRun.event_title ?? lastRun.event_id}: ${lastRun.status}` : "Aucun"} />
      </section>

      <section className="panel-card">
        <div className="panel-card-header">
          <h2>{monthTitle(visibleMonth)}</h2>
          <div className="button-row">
            <button className="ghost-button" onClick={() => setVisibleMonth(addMonths(visibleMonth, -1))} type="button">Mois precedent</button>
            <button className="ghost-button" onClick={() => setVisibleMonth(startOfMonth(new Date()))} type="button">Aujourd'hui</button>
            <button className="ghost-button" onClick={() => setVisibleMonth(addMonths(visibleMonth, 1))} type="button">Mois suivant</button>
            <button className="action-button" onClick={newEvent} type="button">Nouvel evenement</button>
          </div>
        </div>
        <div className="calendar-grid calendar-grid-header">
          {["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"].map((day) => <div key={day}>{day}</div>)}
        </div>
        <div className="calendar-grid">
          {calendarDays.map((day) => (
            <div className={day.inMonth ? "calendar-day" : "calendar-day calendar-day-muted"} key={day.date}>
              <div className="calendar-day-number">{day.label}</div>
              {day.occurrences.map((occurrence) => (
                <button className="calendar-event" key={occurrence.key} onClick={() => editEvent(occurrence.event)} type="button">
                  <span className="calendar-event-title">{occurrence.event.title}</span>
                  {occurrence.run ? <RunStatusBadge status={occurrence.run.status} compact /> : null}
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
                    <td className="truncate-cell">{event.title}</td>
                    <td className="truncate-cell" title={event.disk_label_or_model || event.disk_serial}>{event.disk_label_or_model || event.disk_serial}</td>
                    <td>{formatDate(event.next_occurrence_at)}</td>
                    <td>{event.start_mode === "auto_on_disk_detected" ? "Auto detection" : "Confirmation"}</td>
                    <td><RunStatusBadge status={event.active_run?.status ?? event.last_status ?? "pending"} /></td>
                    <td>
                      <div className="button-row">
                        <button className="ghost-button" onClick={() => editEvent(event)} type="button">Editer</button>
                        <button className="ghost-button" disabled={busy === `run-${event.id}`} onClick={() => void action(`run-${event.id}`, () => runScheduledBackupNow(event.id))} type="button">Run now</button>
                        <button className="ghost-button" onClick={() => void action(`toggle-${event.id}`, () => updateScheduledBackupEvent(event.id, { enabled: !event.enabled }))} type="button">{event.enabled ? "Desactiver" : "Activer"}</button>
                        <button className="danger-button" onClick={() => void deleteEvent(event)} type="button">Supprimer</button>
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
          <h2>Actifs et a venir</h2>
        </div>
        <RunTable emptyTitle="Aucun run actif ou a venir" runs={upcomingRuns} t={t} onAction={action} busy={busy} />
      </section>

      <section className="panel-card">
        <div className="panel-card-header">
          <h2>Historique</h2>
        </div>
        <RunTable emptyTitle="Aucun historique planifie" runs={historyRuns} t={t} onAction={action} busy={busy} history />
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
              <label>Disque<select className="truncate-select" value={form.disk_serial} title={selectedDiskTitle(data.disks, form.disk_serial)} onChange={(e) => {
                const disk = data.disks.find((item) => item.serial_number === e.target.value);
                setForm({ ...form, disk_serial: e.target.value, disk_label_or_model: disk ? diskLabel(disk) : e.target.value });
              }}>
                {data.disks.map((disk) => <option key={disk.serial_number} title={diskLabel(disk, false)} value={disk.serial_number}>{diskOptionLabel(disk)}</option>)}
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

function RunTable({
  runs,
  t,
  onAction,
  busy,
  emptyTitle,
  history = false,
}: {
  runs: ScheduledBackupRun[];
  t: PlanningPageProps["t"];
  onAction: (label: string, callback: () => Promise<unknown>) => Promise<void>;
  busy: string | null;
  emptyTitle: string;
  history?: boolean;
}) {
  if (runs.length === 0) return <EmptyState title={emptyTitle} />;
  return (
    <DataTable>
      <table>
        <thead>
          <tr>
            <th>Evenement</th>
            <th>Fenetre</th>
            <th>Statut</th>
            <th>Backup</th>
            <th>Erreur</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td className="truncate-cell">{run.event_title ?? run.event_id}</td>
              <td>{formatDate(run.window_starts_at)} {"->"} {formatDate(run.window_ends_at)}</td>
              <td><RunStatusBadge status={run.status} /></td>
              <td>{run.backup_run_id ? `#${run.backup_run_id}` : t.notAvailable}</td>
              <td className="truncate-cell" title={run.error ?? ""}>{run.error ?? t.notAvailable}</td>
              <td>
                <div className="button-row">
                  <button className="ghost-button" disabled={history || run.status !== "waiting_for_confirmation" || busy === `confirm-${run.id}`} onClick={() => void onAction(`confirm-${run.id}`, () => confirmScheduledBackupRun(run.id))} type="button">Confirmer</button>
                  <button className="ghost-button" disabled={history || DONE_STATUSES.has(run.status)} onClick={() => void onAction(`cancel-${run.id}`, () => cancelScheduledBackupRun(run.id))} type="button">Annuler</button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </DataTable>
  );
}

function RunStatusBadge({ status, compact = false }: { status: string; compact?: boolean }) {
  const tone = status === "success" ? "success" : status === "failure" || status === "missed" ? "danger" : status === "running" ? "info" : "warning";
  return <StatusBadge tone={tone}>{compact ? shortStatus(status) : status}</StatusBadge>;
}

function expandVisibleOccurrences(events: ScheduledBackupEvent[], runs: ScheduledBackupRun[], rangeStart: Date, rangeEnd: Date): CalendarOccurrence[] {
  const runByEventAndTime = new Map(runs.map((run) => [`${run.event_id}:${new Date(run.scheduled_for).toISOString()}`, run]));
  const occurrences: CalendarOccurrence[] = [];
  for (const event of events) {
    for (const startsAt of expandEventDates(event, rangeStart, rangeEnd)) {
      const endsAt = new Date(startsAt.getTime() + event.window_duration_minutes * 60000);
      const iso = startsAt.toISOString();
      occurrences.push({
        key: `${event.id}:${iso}`,
        event,
        startsAt: iso,
        endsAt: endsAt.toISOString(),
        run: runByEventAndTime.get(`${event.id}:${iso}`) ?? null,
      });
    }
  }
  return occurrences.sort((a, b) => a.startsAt.localeCompare(b.startsAt));
}

function expandEventDates(event: ScheduledBackupEvent, rangeStart: Date, rangeEnd: Date) {
  const start = new Date(event.window_starts_at);
  const dates: Date[] = [];
  if (event.recurrence_type === "once") {
    if (start >= rangeStart && start <= rangeEnd) dates.push(start);
    return dates;
  }
  let cursor = new Date(start);
  const stepDays = event.recurrence_type === "daily" ? 1 : event.recurrence_type === "weekly" ? 7 : 0;
  if (stepDays > 0) {
    while (cursor < rangeStart) cursor = addDays(cursor, stepDays);
    while (cursor <= rangeEnd) {
      dates.push(new Date(cursor));
      cursor = addDays(cursor, stepDays);
    }
    return dates;
  }
  while (cursor < rangeStart) cursor = addMonths(cursor, 1);
  while (cursor <= rangeEnd) {
    dates.push(new Date(cursor));
    cursor = addMonths(cursor, 1);
  }
  return dates;
}

function buildCalendarDays(rangeStart: Date, occurrences: CalendarOccurrence[]) {
  return Array.from({ length: 42 }, (_, index) => {
    const date = addDays(rangeStart, index);
    const key = localDateKey(date);
    return {
      date: key,
      label: String(date.getDate()),
      inMonth: date.getMonth() === addDays(rangeStart, 14).getMonth(),
      occurrences: occurrences.filter((item) => localDateKey(new Date(item.startsAt)) === key),
    };
  });
}

function calendarRange(month: Date) {
  const first = startOfMonth(month);
  const day = first.getDay() || 7;
  const start = addDays(first, 1 - day);
  return { start, end: addDays(start, 41) };
}

function nextSundayAtOne() {
  const date = new Date();
  date.setDate(date.getDate() + ((7 - date.getDay()) % 7 || 7));
  date.setHours(1, 0, 0, 0);
  return date;
}

function startOfMonth(value: Date) {
  return new Date(value.getFullYear(), value.getMonth(), 1);
}

function addDays(value: Date, days: number) {
  const date = new Date(value);
  date.setDate(date.getDate() + days);
  return date;
}

function addMonths(value: Date, months: number) {
  const date = new Date(value);
  date.setMonth(date.getMonth() + months);
  return date;
}

function localDateKey(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function monthTitle(value: Date) {
  return value.toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
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

function shortStatus(status: string) {
  if (status === "waiting_for_confirmation") return "confirm";
  if (status === "waiting_for_disk") return "disk";
  return status;
}

function diskLabel(disk: ExternalDisk, compact = true) {
  const model = disk.model_name || disk.display_name;
  const serial = compact ? shortSerial(disk.serial_number) : disk.serial_number;
  const capacity = disk.usable_capacity_gb || disk.capacity_gb;
  return `${model} - ${serial}${capacity ? ` - ${capacity} GB` : ""}`;
}

function diskOptionLabel(disk: ExternalDisk) {
  return diskLabel(disk, true);
}

function selectedDiskTitle(disks: ExternalDisk[], serial: string) {
  const disk = disks.find((item) => item.serial_number === serial);
  return disk ? diskLabel(disk, false) : serial;
}

function shortSerial(serial: string) {
  return serial.length <= 12 ? serial : `${serial.slice(0, 6)}...${serial.slice(-4)}`;
}

function sortRunsAsc(a: ScheduledBackupRun, b: ScheduledBackupRun) {
  return a.window_starts_at.localeCompare(b.window_starts_at);
}

function sortRunsDesc(a: ScheduledBackupRun, b: ScheduledBackupRun) {
  return b.window_starts_at.localeCompare(a.window_starts_at);
}
