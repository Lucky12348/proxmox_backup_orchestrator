import { useEffect, useMemo, useState } from "react";
import type { MouseEvent } from "react";

import {
  cancelScheduledBackupRun,
  confirmScheduledBackupRun,
  createScheduledBackupEvent,
  deleteScheduledBackupEvent,
  getScheduledBackupCalendar,
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
  ScheduledBackupCalendarOccurrence,
  ScheduledBackupEvent,
  ScheduledBackupEventPayload,
  ScheduledBackupRun,
} from "../types";
import type { PlanningPageProps } from "./shared";

type CalendarView = "day" | "week" | "month" | "year";
type EventForm = ScheduledBackupEventPayload & { id?: number };

const ACTIVE_STATUSES = new Set(["pending", "waiting_for_disk", "waiting_for_confirmation", "waiting_for_external_backup", "running"]);
const DONE_STATUSES = new Set(["success", "failure", "missed", "cancelled"]);
const HOURS = Array.from({ length: 24 }, (_, hour) => hour);
const VIEW_LABELS: Record<CalendarView, string> = { day: "Jour", week: "Semaine", month: "Mois", year: "Annee" };

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
  const [occurrences, setOccurrences] = useState<ScheduledBackupCalendarOccurrence[]>([]);
  const [calendarView, setCalendarView] = useState<CalendarView>(() => readStoredView());
  const [visibleDate, setVisibleDate] = useState(startOfDay(new Date()));
  const [form, setForm] = useState<EventForm | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ message: string; tone: "info" | "error" } | null>(null);

  const visibleRange = useMemo(() => calendarRange(calendarView, visibleDate), [calendarView, visibleDate]);
  const activeRuns = runs.filter((run) => ACTIVE_STATUSES.has(run.status)).sort(sortRunsAsc);
  const historyRuns = runs.filter((run) => DONE_STATUSES.has(run.status)).sort(sortRunsDesc).slice(0, 12);
  const upcomingRuns = runs.filter((run) => !DONE_STATUSES.has(run.status)).sort(sortRunsAsc).slice(0, 12);
  const nextOccurrence = occurrences.filter((item) => new Date(item.window_starts_at) >= new Date()).sort(sortOccurrences)[0] ?? null;
  const lastRun = runs.slice().sort(sortRunsDesc)[0] ?? null;

  useEffect(() => {
    setEvents(data.scheduledBackupEvents);
    setRuns(data.scheduledBackupRuns);
  }, [data.scheduledBackupEvents, data.scheduledBackupRuns]);

  useEffect(() => {
    window.localStorage.setItem("pbo.planning.calendarView", calendarView);
  }, [calendarView]);

  useEffect(() => {
    let cancelled = false;
    void refreshPlanning({ silent: true, cancelled: () => cancelled });
    const intervalId = window.setInterval(() => {
      void refreshPlanning({ silent: true, cancelled: () => cancelled });
    }, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [visibleRange.startKey, visibleRange.endKey]);

  async function refreshPlanning(options: { silent?: boolean; cancelled?: () => boolean } = {}) {
    try {
      const [nextEvents, nextRuns, nextOccurrences] = await Promise.all([
        getScheduledBackupEvents(),
        getScheduledBackupRuns(),
        getScheduledBackupCalendar(visibleRange.startKey, visibleRange.endKey),
      ]);
      if (options.cancelled?.()) return;
      setEvents(nextEvents);
      setRuns(nextRuns);
      setOccurrences(nextOccurrences);
    } catch (error) {
      if (!options.silent) setBanner({ message: error instanceof Error ? error.message : "Unknown error", tone: "error" });
    }
  }

  function openNewEvent(date: Date) {
    const firstDisk = data.disks[0];
    setForm({
      ...DEFAULT_FORM,
      disk_serial: firstDisk?.serial_number ?? "",
      disk_label_or_model: firstDisk ? diskLabel(firstDisk) : "",
      datastore: data.pbsStatus.datastore,
      window_starts_at: toLocalInputValue(date),
    });
  }

  function editOccurrence(occurrence: ScheduledBackupCalendarOccurrence) {
    const event = events.find((item) => item.id === occurrence.event_id);
    if (event) editEvent(event);
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

  function movePeriod(delta: number) {
    setVisibleDate((current) => addPeriod(current, calendarView, delta));
  }

  function switchToDay(date: Date) {
    setVisibleDate(startOfDay(date));
    setCalendarView("day");
  }

  function switchToMonth(date: Date) {
    setVisibleDate(startOfMonth(date));
    setCalendarView("month");
  }

  return (
    <div className="page-stack">
      <PageHeader title={t.nav.planning} description="Calendrier des sauvegardes externes et capacite planifiee." />

      {banner ? <ErrorBanner dismissLabel={t.dismiss} message={banner.message} onDismiss={() => setBanner(null)} tone={banner.tone} /> : null}

      <section className="stats-grid stats-grid-compact">
        <StatCard label="Prochain backup" value={nextOccurrence ? formatDate(nextOccurrence.window_starts_at) : "Aucun"} />
        <StatCard label="Actif maintenant" value={activeRuns[0] ? `${activeRuns[0].event_title ?? activeRuns[0].event_id}: ${statusLabel(activeRuns[0].status)}` : "Aucun"} />
        <StatCard label="Dernier run" value={lastRun ? `${lastRun.event_title ?? lastRun.event_id}: ${statusLabel(lastRun.status)}` : "Aucun"} />
      </section>

      <section className="panel-card calendar-shell">
        <div className="calendar-toolbar">
          <div className="button-row">
            <button className="ghost-button" onClick={() => setVisibleDate(startOfDay(new Date()))} type="button">Aujourd'hui</button>
            <button className="ghost-button icon-button" aria-label="Periode precedente" onClick={() => movePeriod(-1)} type="button">{"<"}</button>
            <button className="ghost-button icon-button" aria-label="Periode suivante" onClick={() => movePeriod(1)} type="button">{">"}</button>
          </div>
          <h2>{periodTitle(calendarView, visibleDate)}</h2>
          <div className="button-row calendar-view-switcher">
            {(["day", "week", "month", "year"] as CalendarView[]).map((view) => (
              <button className={calendarView === view ? "action-button" : "ghost-button"} key={view} onClick={() => setCalendarView(view)} type="button">
                {VIEW_LABELS[view]}
              </button>
            ))}
            <button className="action-button" onClick={() => openNewEvent(defaultEventDate(visibleDate))} type="button">Nouvel evenement</button>
          </div>
        </div>

        {calendarView === "day" ? (
          <DayView date={visibleDate} occurrences={occurrences} onCreate={openNewEvent} onOpen={editOccurrence} />
        ) : null}
        {calendarView === "week" ? (
          <WeekView start={startOfWeek(visibleDate)} occurrences={occurrences} onCreate={openNewEvent} onOpen={editOccurrence} />
        ) : null}
        {calendarView === "month" ? (
          <MonthView month={visibleDate} occurrences={occurrences} onCreate={(date) => openNewEvent(defaultEventDate(date))} onOpen={editOccurrence} />
        ) : null}
        {calendarView === "year" ? (
          <YearView year={visibleDate.getFullYear()} occurrences={occurrences} onDay={switchToDay} onMonth={switchToMonth} />
        ) : null}
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
              <label>Titre<input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label>
              <label>Disque<select className="truncate-select" value={form.disk_serial} title={selectedDiskTitle(data.disks, form.disk_serial)} onChange={(event) => {
                const disk = data.disks.find((item) => item.serial_number === event.target.value);
                setForm({ ...form, disk_serial: event.target.value, disk_label_or_model: disk ? diskLabel(disk) : event.target.value });
              }}>
                {data.disks.map((disk) => <option key={disk.serial_number} title={diskLabel(disk, false)} value={disk.serial_number}>{diskOptionLabel(disk)}</option>)}
              </select></label>
              <label>Datastore<input value={form.datastore} onChange={(event) => setForm({ ...form, datastore: event.target.value })} /></label>
              <label>Recurrence<select value={form.recurrence_type} onChange={(event) => setForm({ ...form, recurrence_type: event.target.value as EventForm["recurrence_type"] })}>
                <option value="once">Une fois</option>
                <option value="daily">Tous les jours</option>
                <option value="weekly">Chaque semaine</option>
                <option value="monthly">Chaque mois</option>
              </select></label>
              <label>Debut fenetre<input type="datetime-local" value={form.window_starts_at} onChange={(event) => setForm({ ...form, window_starts_at: event.target.value })} /></label>
              <label>Duree minutes<input type="number" min={1} value={form.window_duration_minutes} onChange={(event) => setForm({ ...form, window_duration_minutes: Number(event.target.value) })} /></label>
              <label>Rappel minutes avant<input type="number" min={0} value={form.notify_before_minutes} onChange={(event) => setForm({ ...form, notify_before_minutes: Number(event.target.value) })} /></label>
              <label>Mode demarrage<select value={form.start_mode} onChange={(event) => setForm({ ...form, start_mode: event.target.value as EventForm["start_mode"] })}>
                <option value="manual_confirmation">Confirmation manuelle</option>
                <option value="auto_on_disk_detected">Automatique sur detection disque</option>
              </select></label>
              <label className="checkbox-row"><input checked={form.auto_eject_after_success} onChange={(event) => setForm({ ...form, auto_eject_after_success: event.target.checked })} type="checkbox" /> Auto-eject apres succes</label>
              <label className="checkbox-row"><input checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} type="checkbox" /> Active</label>
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

function DayView({ date, occurrences, onCreate, onOpen }: { date: Date; occurrences: ScheduledBackupCalendarOccurrence[]; onCreate: (date: Date) => void; onOpen: (occurrence: ScheduledBackupCalendarOccurrence) => void }) {
  const dayOccurrences = occurrences.filter((item) => localDateKey(new Date(item.window_starts_at)) === localDateKey(date));
  const today = isToday(date);
  return (
    <div className="calendar-time-grid calendar-day-view">
      <div className="calendar-time-labels">{HOURS.map((hour) => <div key={hour}>{hourLabel(hour)}</div>)}</div>
      <div className={today ? "calendar-time-column calendar-today-column" : "calendar-time-column"} onDoubleClick={(event) => onCreate(slotDateFromClick(date, event))}>
        {HOURS.map((hour) => <button aria-label={`Creer a ${hourLabel(hour)}`} className="calendar-hour-line" key={hour} onClick={() => onCreate(withHour(date, hour))} type="button" />)}
        {today ? <CurrentTimeIndicator /> : null}
        {dayOccurrences.map((occurrence) => <OccurrenceBlock key={occurrence.occurrence_id} occurrence={occurrence} onOpen={onOpen} />)}
      </div>
    </div>
  );
}

function WeekView({ start, occurrences, onCreate, onOpen }: { start: Date; occurrences: ScheduledBackupCalendarOccurrence[]; onCreate: (date: Date) => void; onOpen: (occurrence: ScheduledBackupCalendarOccurrence) => void }) {
  const days = Array.from({ length: 7 }, (_, index) => addDays(start, index));
  return (
    <div className="calendar-week-wrap">
      <div className="calendar-week-header">
        <div />
        {days.map((day) => (
          <button className={isToday(day) ? "calendar-week-day-title calendar-today-header" : "calendar-week-day-title"} key={localDateKey(day)} onClick={() => onCreate(defaultEventDate(day))} type="button">
            <span>{weekdayTitle(day)}</span>
            <span className={isToday(day) ? "calendar-today-number" : "calendar-day-number-inline"}>{day.getDate()}</span>
          </button>
        ))}
      </div>
      <div className="calendar-week-grid">
        <div className="calendar-time-labels">{HOURS.map((hour) => <div key={hour}>{hourLabel(hour)}</div>)}</div>
        {days.map((day) => {
          const dayOccurrences = occurrences.filter((item) => localDateKey(new Date(item.window_starts_at)) === localDateKey(day));
          return (
            <div className={isToday(day) ? "calendar-time-column calendar-today-column" : "calendar-time-column"} key={localDateKey(day)}>
              {HOURS.map((hour) => <button aria-label={`Creer ${localDateKey(day)} ${hourLabel(hour)}`} className="calendar-hour-line" key={hour} onClick={() => onCreate(withHour(day, hour))} type="button" />)}
              {isToday(day) ? <CurrentTimeIndicator compact /> : null}
              {dayOccurrences.map((occurrence) => <OccurrenceBlock key={occurrence.occurrence_id} occurrence={occurrence} onOpen={onOpen} />)}
            </div>
          );
        })}
      </div>
      <div className="calendar-agenda-fallback">
        {occurrences.length === 0 ? <EmptyState title="Aucun evenement cette semaine" /> : occurrences.map((occurrence) => (
          <CalendarListItem key={occurrence.occurrence_id} occurrence={occurrence} onOpen={onOpen} />
        ))}
      </div>
    </div>
  );
}

function MonthView({ month, occurrences, onCreate, onOpen }: { month: Date; occurrences: ScheduledBackupCalendarOccurrence[]; onCreate: (date: Date) => void; onOpen: (occurrence: ScheduledBackupCalendarOccurrence) => void }) {
  const range = monthGridRange(month);
  const days = Array.from({ length: 42 }, (_, index) => addDays(range.start, index));
  const currentMonth = month.getMonth();
  return (
    <>
      <div className="calendar-grid calendar-grid-header">
        {["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"].map((day) => <div key={day}>{day}</div>)}
      </div>
      <div className="calendar-grid">
        {days.map((day) => {
          const items = occurrences.filter((item) => localDateKey(new Date(item.window_starts_at)) === localDateKey(day));
          const visibleItems = items.slice(0, 3);
          const dayClasses = [
            "calendar-day",
            day.getMonth() === currentMonth ? "" : "calendar-day-muted",
            isToday(day) ? "calendar-today-cell" : "",
          ].filter(Boolean).join(" ");
          return (
            <button className={dayClasses} key={localDateKey(day)} onClick={() => onCreate(day)} type="button">
              <span className={isToday(day) ? "calendar-day-number calendar-today-number" : "calendar-day-number"}>{day.getDate()}</span>
              {visibleItems.map((occurrence) => (
                <span className={`calendar-event calendar-event-${occurrence.status ?? "planned"}`} key={occurrence.occurrence_id} onClick={(event) => { event.stopPropagation(); onOpen(occurrence); }}>
                  <span className="calendar-event-title">{timeLabel(occurrence.window_starts_at)} {occurrence.title}</span>
                  {occurrence.status ? <RunStatusBadge status={occurrence.status} compact /> : null}
                </span>
              ))}
              {items.length > visibleItems.length ? <span className="calendar-more">+{items.length - visibleItems.length} autres</span> : null}
            </button>
          );
        })}
      </div>
    </>
  );
}

function YearView({ year, occurrences, onDay, onMonth }: { year: number; occurrences: ScheduledBackupCalendarOccurrence[]; onDay: (date: Date) => void; onMonth: (date: Date) => void }) {
  return (
    <div className="calendar-year-grid">
      {Array.from({ length: 12 }, (_, monthIndex) => {
        const month = new Date(year, monthIndex, 1);
        const firstDayOffset = (month.getDay() || 7) - 1;
        const daysInMonth = new Date(year, monthIndex + 1, 0).getDate();
        const cells = Array.from({ length: firstDayOffset + daysInMonth }, (_, index) => index < firstDayOffset ? null : new Date(year, monthIndex, index - firstDayOffset + 1));
        return (
          <section className="calendar-mini-month" key={monthIndex}>
            <button className="calendar-mini-title" onClick={() => onMonth(month)} type="button">{month.toLocaleDateString("fr-FR", { month: "long" })}</button>
            <div className="calendar-mini-weekdays">
              {["L", "M", "M", "J", "V", "S", "D"].map((day, index) => <span key={`${day}-${index}`}>{day}</span>)}
            </div>
            <div className="calendar-mini-grid">
              {cells.map((day, index) => {
                if (!day) return <span className="calendar-mini-blank" key={`blank-${monthIndex}-${index}`} />;
                const hasEvent = occurrences.some((item) => localDateKey(new Date(item.window_starts_at)) === localDateKey(day));
                return (
                  <button
                    className={["calendar-mini-day", hasEvent ? "calendar-mini-day-event" : "", isToday(day) ? "calendar-today-mini" : ""].filter(Boolean).join(" ")}
                    key={localDateKey(day)}
                    onClick={() => onDay(day)}
                    type="button"
                  >
                    {day.getDate()}
                  </button>
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function OccurrenceBlock({ occurrence, onOpen }: { occurrence: ScheduledBackupCalendarOccurrence; onOpen: (occurrence: ScheduledBackupCalendarOccurrence) => void }) {
  const start = new Date(occurrence.window_starts_at);
  const end = new Date(occurrence.window_ends_at);
  const top = ((start.getHours() * 60 + start.getMinutes()) / 1440) * 100;
  const height = Math.max(4, ((end.getTime() - start.getTime()) / 60000 / 1440) * 100);
  const disk = occurrence.disk_label || occurrence.disk_serial;
  return (
    <button
      className={`calendar-time-event calendar-event-${occurrence.status ?? "planned"}`}
      onClick={() => onOpen(occurrence)}
      style={{ top: `${top}%`, height: `${height}%` }}
      title={`${occurrence.title} - ${disk}`}
      type="button"
    >
      <span className="calendar-event-title">{occurrence.title}</span>
      <span className="calendar-event-disk">{disk}</span>
      {occurrence.status ? <RunStatusBadge status={occurrence.status} compact /> : null}
    </button>
  );
}

function CurrentTimeIndicator({ compact = false }: { compact?: boolean }) {
  const now = new Date();
  const top = ((now.getHours() * 60 + now.getMinutes()) / 1440) * 100;
  return (
    <div className="calendar-now-line" style={{ top: `${top}%` }}>
      <span>{compact ? "" : timeLabel(now.toISOString())}</span>
    </div>
  );
}

function CalendarListItem({ occurrence, onOpen }: { occurrence: ScheduledBackupCalendarOccurrence; onOpen: (occurrence: ScheduledBackupCalendarOccurrence) => void }) {
  return (
    <button className="calendar-agenda-item" onClick={() => onOpen(occurrence)} type="button">
      <span>{formatDate(occurrence.window_starts_at)} - {occurrence.title}</span>
      {occurrence.status ? <RunStatusBadge status={occurrence.status} /> : null}
    </button>
  );
}

function RunTable({ runs, t, onAction, busy, emptyTitle, history = false }: { runs: ScheduledBackupRun[]; t: PlanningPageProps["t"]; onAction: (label: string, callback: () => Promise<unknown>) => Promise<void>; busy: string | null; emptyTitle: string; history?: boolean }) {
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
  const tone = status === "success" ? "success" : status === "failure" || status === "missed" ? "danger" : status === "running" ? "info" : status === "cancelled" ? "neutral" : "warning";
  return <StatusBadge tone={tone}>{compact ? shortStatus(status) : statusLabel(status)}</StatusBadge>;
}

function calendarRange(view: CalendarView, date: Date) {
  if (view === "day") {
    return range(startOfDay(date), startOfDay(date));
  }
  if (view === "week") {
    const start = startOfWeek(date);
    return range(start, addDays(start, 6));
  }
  if (view === "year") {
    return range(new Date(date.getFullYear(), 0, 1), new Date(date.getFullYear(), 11, 31));
  }
  const month = monthGridRange(date);
  return range(month.start, month.end);
}

function range(start: Date, end: Date) {
  return { start, end, startKey: localDateKey(start), endKey: localDateKey(end) };
}

function monthGridRange(month: Date) {
  const first = startOfMonth(month);
  const day = first.getDay() || 7;
  const start = addDays(first, 1 - day);
  return { start, end: addDays(start, 41) };
}

function addPeriod(value: Date, view: CalendarView, delta: number) {
  if (view === "day") return addDays(value, delta);
  if (view === "week") return addDays(value, delta * 7);
  if (view === "year") return new Date(value.getFullYear() + delta, 0, 1);
  return addMonths(value, delta);
}

function periodTitle(view: CalendarView, date: Date) {
  if (view === "day") return date.toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
  if (view === "week") {
    const start = startOfWeek(date);
    const end = addDays(start, 6);
    return `${start.toLocaleDateString("fr-FR", { day: "numeric" })} - ${end.toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" })}`;
  }
  if (view === "year") return String(date.getFullYear());
  return date.toLocaleDateString("fr-FR", { month: "long", year: "numeric" });
}

function readStoredView(): CalendarView {
  const value = window.localStorage.getItem("pbo.planning.calendarView");
  return value === "day" || value === "week" || value === "month" || value === "year" ? value : "month";
}

function defaultEventDate(date: Date) {
  const next = new Date(date);
  next.setHours(1, 0, 0, 0);
  return next;
}

function slotDateFromClick(date: Date, event: MouseEvent<HTMLDivElement>) {
  const rect = event.currentTarget.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
  const hour = Math.floor(ratio * 24);
  return withHour(date, hour);
}

function withHour(value: Date, hour: number) {
  const date = new Date(value);
  date.setHours(hour, 0, 0, 0);
  return date;
}

function startOfDay(value: Date) {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate());
}

function startOfWeek(value: Date) {
  const date = startOfDay(value);
  const day = date.getDay() || 7;
  return addDays(date, 1 - day);
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

function isToday(value: Date) {
  return localDateKey(value) === localDateKey(new Date());
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

function timeLabel(value: string) {
  return new Date(value).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

function hourLabel(hour: number) {
  return `${String(hour).padStart(2, "0")}:00`;
}

function weekdayTitle(date: Date) {
  return date.toLocaleDateString("fr-FR", { weekday: "short" });
}

function shortStatus(status: string) {
  if (status === "waiting_for_confirmation") return "Confirm.";
  if (status === "waiting_for_external_backup") return "Differe";
  if (status === "waiting_for_disk") return "Disque";
  return statusLabel(status);
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    pending: "En attente",
    waiting_for_disk: "En attente disque",
    waiting_for_confirmation: "Confirmation requise",
    waiting_for_external_backup: "Backup externe en cours",
    running: "En cours",
    success: "Succes",
    failure: "Echec",
    missed: "Manque",
    cancelled: "Annule",
  };
  return labels[status] ?? status;
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

function sortOccurrences(a: ScheduledBackupCalendarOccurrence, b: ScheduledBackupCalendarOccurrence) {
  return a.window_starts_at.localeCompare(b.window_starts_at);
}

function sortRunsAsc(a: ScheduledBackupRun, b: ScheduledBackupRun) {
  return a.window_starts_at.localeCompare(b.window_starts_at);
}

function sortRunsDesc(a: ScheduledBackupRun, b: ScheduledBackupRun) {
  return b.window_starts_at.localeCompare(a.window_starts_at);
}
