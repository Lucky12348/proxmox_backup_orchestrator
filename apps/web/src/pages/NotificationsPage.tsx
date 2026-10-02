import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  getHostNotifHistory,
  getHostNotifQueue,
  getHostNotifTemplates,
  saveHostNotifTemplates,
  testHostNotifEvent,
} from "../api";
import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { ErrorBanner } from "../components/ErrorBanner";
import { LoadingBlock } from "../components/LoadingBlock";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import {
  EMOJI_CATALOG,
  EMOJI_RE,
  EVENT_CODE_RE,
  MESSAGE_MAX,
  TEST_VALUE_MAX,
  TITLE_MAX,
  BUILTIN_EVENTS,
  emojiChar,
  eventVariables,
  exampleVars,
  formatAge,
  formatParisDateTime,
  groupEventCodes,
  isBuiltinEvent,
  newCustomEvent,
  normalizeTemplates,
  stableStringify,
  renderTemplate,
  validateTemplates,
  type ValidationIssue,
} from "../hostNotifCatalog";
import type { Language, TranslationDictionary } from "../i18n";
import type {
  HostNotifEvent,
  HostNotifHistory,
  HostNotifHistoryStatus,
  HostNotifQueue,
  HostNotifTemplates,
  HostNotifTestResult,
} from "../types";

interface NotificationsPageProps {
  language: Language;
  t: TranslationDictionary;
}

type Tab = "templates" | "history";
type Banner = { message: string; tone: "info" | "error" } | null;
type HostNotifText = TranslationDictionary["hostNotif"];

const QUEUE_REFRESH_MS = 30000;

function fill(template: string, params: Record<string, string | number>) {
  return template.replace(/\{(\w+)\}/g, (whole, key: string) => (key in params ? String(params[key]) : whole));
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

export function NotificationsPage({ language, t }: NotificationsPageProps) {
  const h = t.hostNotif;
  const [tab, setTab] = useState<Tab>("templates");
  const [baseline, setBaseline] = useState<HostNotifTemplates | null>(null);
  const [draft, setDraft] = useState<HostNotifTemplates | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [banner, setBanner] = useState<Banner>(null);
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [queue, setQueue] = useState<HostNotifQueue | null>(null);
  const [queueError, setQueueError] = useState(false);

  const dirty = useMemo(() => stableStringify(draft) !== stableStringify(baseline), [draft, baseline]);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const templates = normalizeTemplates((await getHostNotifTemplates()).templates);
      setBaseline(templates);
      setDraft(templates);
      setIssues([]);
    } catch (error) {
      setLoadError(`${h.loadError} ${errorMessage(error)}`);
    } finally {
      setLoading(false);
    }
  }, [h.loadError]);

  const loadQueue = useCallback(async () => {
    try {
      setQueue(await getHostNotifQueue());
      setQueueError(false);
    } catch {
      setQueueError(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadQueue();
    const id = window.setInterval(() => void loadQueue(), QUEUE_REFRESH_MS);
    return () => window.clearInterval(id);
  }, [loadQueue]);

  // Warn before closing/reloading the tab with unsaved edits.
  useEffect(() => {
    if (!dirty) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = h.leaveWarning;
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty, h.leaveWarning]);

  function patchDefaults(patch: Partial<HostNotifTemplates["defaults"]>) {
    setDraft((current) => {
      if (!current) return current;
      const defaults = { ...current.defaults, ...patch };
      // `undefined` means "remove the key" so templates.json keeps its original shape.
      for (const key of Object.keys(defaults) as (keyof typeof defaults)[]) {
        if (defaults[key] === undefined) delete defaults[key];
      }
      return { ...current, defaults };
    });
  }

  function patchEvent(code: string, patch: Partial<HostNotifEvent>) {
    setDraft((current) => {
      if (!current) return current;
      const event = { ...current.events[code], ...patch };
      for (const key of Object.keys(event) as (keyof HostNotifEvent)[]) {
        if (event[key] === undefined) delete event[key];
      }
      return { ...current, events: { ...current.events, [code]: event } };
    });
  }

  function addEvent(code: string) {
    setDraft((current) => (current ? { ...current, events: { ...current.events, [code]: newCustomEvent(code) } } : current));
  }

  function deleteEvent(code: string) {
    if (isBuiltinEvent(code)) return;
    if (!window.confirm(fill(h.deleteConfirm, { code }))) return;
    setDraft((current) => {
      if (!current) return current;
      const events = { ...current.events };
      delete events[code];
      return { ...current, events };
    });
  }

  async function save() {
    if (!draft) return;
    const found = validateTemplates(draft);
    setIssues(found);
    if (found.length > 0) {
      setBanner({ message: h.validationFailed, tone: "error" });
      return;
    }
    setSaving(true);
    setBanner(null);
    try {
      const result = await saveHostNotifTemplates(draft);
      const saved = normalizeTemplates(result.templates);
      setBaseline(saved);
      setDraft(saved);
      setBanner({
        message: [h.saved, result.backup_path ? fill(h.savedBackup, { path: result.backup_path }) : null].filter(Boolean).join(" "),
        tone: "info",
      });
    } catch (error) {
      setBanner({ message: errorMessage(error), tone: "error" });
    } finally {
      setSaving(false);
    }
  }

  function revert() {
    setDraft(baseline);
    setIssues([]);
    setBanner(null);
  }

  const issuesByField = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const issue of issues) {
      map.set(issue.field, [...(map.get(issue.field) ?? []), h.validation[issue.code] ?? issue.code]);
    }
    return map;
  }, [issues, h.validation]);

  // Re-validate live once the user has tried to save, so errors disappear as they are fixed.
  useEffect(() => {
    if (draft && issues.length > 0) setIssues(validateTemplates(draft));
  }, [draft]);

  return (
    <div className="page-stack">
      <PageHeader
        title={t.nav.notifications}
        description={h.intro}
        actions={<QueueBadge error={queueError} h={h} language={language} queue={queue} />}
      />

      {/* Same view-switcher pattern as the Planning page (active = action-button). */}
      <div className="button-row">
        {(["templates", "history"] as Tab[]).map((item) => (
          <button
            aria-pressed={tab === item}
            className={tab === item ? "action-button" : "ghost-button"}
            key={item}
            onClick={() => setTab(item)}
            type="button"
          >
            {item === "templates" ? h.tabTemplates : h.tabHistory}
            {item === "templates" && dirty ? <span className="hn-dirty-dot" title={h.unsaved} /> : null}
          </button>
        ))}
      </div>

      {tab === "history" ? (
        <HistoryTab codes={Object.keys(draft?.events ?? {})} h={h} language={language} t={t} />
      ) : loading ? (
        <LoadingBlock label={t.loading} />
      ) : loadError || !draft || !baseline ? (
        <section className="panel-card">
          <ErrorBanner dismissLabel={t.dismiss} message={loadError ?? h.loadError} />
          <div className="button-row">
            <button className="action-button" onClick={() => void load()} type="button">{t.retry}</button>
          </div>
        </section>
      ) : (
        <>
          {banner ? (
            <ErrorBanner dismissLabel={t.dismiss} message={banner.message} onDismiss={() => setBanner(null)} tone={banner.tone} />
          ) : null}
          {issues.length > 0 ? (
            <section className="panel-card hn-issues">
              <strong>{h.validationFailed}</strong>
              <ul>
                {issues.map((issue, index) => (
                  <li key={`${issue.field}-${index}`}>
                    <code>{issue.field}</code> — {h.validation[issue.code] ?? issue.code}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <GeneralSettings defaults={draft.defaults} h={h} issuesByField={issuesByField} onChange={patchDefaults} />

          <section className="panel-card">
            <div className="panel-card-header">
              <h2>{h.eventsTitle}</h2>
              <AddEventForm existing={Object.keys(draft.events)} h={h} onAdd={addEvent} />
            </div>
            {groupEventCodes(Object.keys(draft.events)).map(([category, codes]) => (
              <details className="hn-category" key={category} open>
                <summary>
                  {h.categories[category] ?? category} <span className="muted-text">({codes.length})</span>
                </summary>
                <div className="hn-event-list">
                  {codes.map((code) => (
                    <EventCard
                      code={code}
                      defaultTopic={draft.defaults.topic}
                      event={draft.events[code]}
                      h={h}
                      issuesByField={issuesByField}
                      key={code}
                      language={language}
                      onChange={(patch) => patchEvent(code, patch)}
                      onDelete={() => deleteEvent(code)}
                      savedEvent={baseline.events[code]}
                      t={t}
                    />
                  ))}
                </div>
              </details>
            ))}
          </section>

          <div className={dirty ? "hn-savebar hn-savebar-dirty" : "hn-savebar"}>
            <span>{dirty ? h.unsaved : h.upToDate}</span>
            <div className="button-row">
              <button className="ghost-button" disabled={!dirty || saving} onClick={revert} type="button">{h.revert}</button>
              <button className="action-button" disabled={!dirty || saving} onClick={() => void save()} type="button">
                {saving ? <><span className="inline-spinner" /> {h.saving}</> : h.save}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function QueueBadge({ queue, error, h, language }: { queue: HostNotifQueue | null; error: boolean; h: HostNotifText; language: Language }) {
  if (error) return <StatusBadge tone="danger">{h.queueUnknown}</StatusBadge>;
  if (!queue) return <StatusBadge tone="neutral">…</StatusBadge>;
  if (queue.count === 0) return <StatusBadge tone="success">{h.queueOk}</StatusBadge>;
  return (
    <StatusBadge tone="warning">
      {fill(h.queuePending, {
        count: queue.count,
        age: queue.oldest_age_seconds !== null ? formatAge(queue.oldest_age_seconds, language) : "?",
      })}
    </StatusBadge>
  );
}

function FieldErrors({ messages }: { messages?: string[] }) {
  if (!messages?.length) return null;
  return <span className="hn-field-error">{messages.join(" · ")}</span>;
}

function GeneralSettings({
  defaults,
  h,
  issuesByField,
  onChange,
}: {
  defaults: HostNotifTemplates["defaults"];
  h: HostNotifText;
  issuesByField: Map<string, string[]>;
  onChange: (patch: Partial<HostNotifTemplates["defaults"]>) => void;
}) {
  return (
    <section className="panel-card">
      <div className="panel-card-header">
        <h2>{h.generalTitle}</h2>
      </div>
      <div className="settings-input-grid">
        <label>
          <span>{h.defaultTopic}</span>
          <input maxLength={64} onChange={(e) => onChange({ topic: e.target.value })} value={defaults.topic ?? ""} />
          <FieldErrors messages={issuesByField.get("defaults.topic")} />
        </label>
        <label>
          <span>{h.defaultClick} <em className="muted-text">({h.optional})</em></span>
          <input
            onChange={(e) => onChange({ click: e.target.value })}
            placeholder="https://"
            type="url"
            value={defaults.click ?? ""}
          />
          <FieldErrors messages={issuesByField.get("defaults.click")} />
        </label>
        <label>
          <span>{h.defaultIcon} <em className="muted-text">({h.optional})</em></span>
          <input
            onChange={(e) => onChange({ icon: e.target.value })}
            placeholder="https://"
            type="url"
            value={defaults.icon ?? ""}
          />
          <FieldErrors messages={issuesByField.get("defaults.icon")} />
        </label>
        <label>
          <span>{h.lateAfter}</span>
          <input
            max={86400}
            min={0}
            onChange={(e) => onChange({ late_after_sec: e.target.value === "" ? undefined : Number(e.target.value) })}
            step={1}
            type="number"
            value={defaults.late_after_sec ?? ""}
          />
          <span className="muted-text">{h.lateAfterHint}</span>
          <FieldErrors messages={issuesByField.get("defaults.late_after_sec")} />
        </label>
      </div>
    </section>
  );
}

function AddEventForm({ existing, h, onAdd }: { existing: string[]; h: HostNotifText; onAdd: (code: string) => void }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit() {
    const value = code.trim();
    if (value.length > 64 || !EVENT_CODE_RE.test(value)) {
      setError(h.addEventInvalid);
      return;
    }
    if (existing.includes(value)) {
      setError(h.addEventExists);
      return;
    }
    onAdd(value);
    setCode("");
    setError(null);
  }

  return (
    <div className="hn-add-event">
      <div className="button-row">
        <input
          aria-label={h.addEvent}
          className="text-input"
          maxLength={64}
          onChange={(e) => { setCode(e.target.value); setError(null); }}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } }}
          placeholder={h.addEventPlaceholder}
          value={code}
        />
        <button className="ghost-button" disabled={!code.trim()} onClick={submit} title={h.addEvent} type="button">
          + {h.addEventButton}
        </button>
      </div>
      {error ? <span className="hn-field-error">{error}</span> : null}
    </div>
  );
}

interface EventCardProps {
  code: string;
  event: HostNotifEvent;
  savedEvent: HostNotifEvent | undefined;
  defaultTopic: string;
  h: HostNotifText;
  t: TranslationDictionary;
  language: Language;
  issuesByField: Map<string, string[]>;
  onChange: (patch: Partial<HostNotifEvent>) => void;
  onDelete: () => void;
}

function EventCard({ code, event, savedEvent, defaultTopic, h, t, language, issuesByField, onChange, onDelete }: EventCardProps) {
  const builtin = isBuiltinEvent(code);
  const titleRef = useRef<HTMLInputElement>(null);
  const messageRef = useRef<HTMLTextAreaElement>(null);
  const lastFocused = useRef<"title" | "message">("message");
  const [testOpen, setTestOpen] = useState(false);
  const variables = eventVariables(code, event);
  const examples = exampleVars(code, event);
  const prefix = `events.${code}`;
  const changed = stableStringify(event) !== stableStringify(savedEvent);

  function insertVariable(name: string) {
    const field = lastFocused.current;
    const element = field === "title" ? titleRef.current : messageRef.current;
    const token = `{${name}}`;
    const current = field === "title" ? event.title : event.message;
    const start = element?.selectionStart ?? current.length;
    const end = element?.selectionEnd ?? current.length;
    const next = current.slice(0, start) + token + current.slice(end);
    onChange(field === "title" ? { title: next } : { message: next });
    window.requestAnimationFrame(() => {
      element?.focus();
      element?.setSelectionRange(start + token.length, start + token.length);
    });
  }

  return (
    <article className={event.enabled ? "hn-event" : "hn-event hn-event-disabled"}>
      <div className="hn-event-head">
        <label className="toggle" title={h.enabled}>
          <input checked={event.enabled} onChange={(e) => onChange({ enabled: e.target.checked })} type="checkbox" />
          <span className="toggle-slider" />
        </label>
        <div className="hn-event-name">
          <code>{code}</code>
          <span className="muted-text">
            {BUILTIN_EVENTS[code]?.label[language] ?? h.custom}
            {builtin ? ` · ${h.builtin}` : ""}
          </span>
        </div>
        {changed ? <span className="hn-dirty-dot" title={h.unsaved} /> : null}
        <div className="button-row hn-event-actions">
          <button className="ghost-button" onClick={() => setTestOpen((open) => !open)} type="button">
            {h.test}
          </button>
          {!builtin ? (
            <button className="danger-button" onClick={onDelete} type="button">
              {h.deleteEvent}
            </button>
          ) : null}
        </div>
      </div>

      <div className="hn-event-body">
        <div className="hn-event-fields">
          <div className="hn-row">
            <div className="hn-field hn-field-emoji">
              <span>{h.emoji}</span>
              <EmojiPicker h={h} onChange={(emoji) => onChange({ emoji })} value={event.emoji} />
              <FieldErrors messages={issuesByField.get(`${prefix}.emoji`)} />
            </div>
            <label className="hn-field hn-field-grow">
              <span>
                {h.title} <em className="muted-text">{[...event.title].length}/{TITLE_MAX}</em>
              </span>
              <input
                maxLength={TITLE_MAX * 2}
                onChange={(e) => onChange({ title: e.target.value })}
                onFocus={() => { lastFocused.current = "title"; }}
                ref={titleRef}
                value={event.title}
              />
              <FieldErrors messages={issuesByField.get(`${prefix}.title`)} />
            </label>
          </div>
          <label className="hn-field">
            <span>
              {h.message} <em className="muted-text">{[...event.message].length}/{MESSAGE_MAX}</em>
            </span>
            <textarea
              onChange={(e) => onChange({ message: e.target.value })}
              onFocus={() => { lastFocused.current = "message"; }}
              ref={messageRef}
              rows={2}
              value={event.message}
            />
            <FieldErrors messages={issuesByField.get(`${prefix}.message`)} />
          </label>
          <div className="hn-field">
            <span>{h.variables}</span>
            {variables.length === 0 ? (
              <span className="muted-text">{h.noVariables}</span>
            ) : (
              <div className="hn-chips">
                {variables.map((name) => (
                  <button
                    className="hn-chip"
                    key={name}
                    onClick={() => insertVariable(name)}
                    onMouseDown={(e) => e.preventDefault()}
                    title={examples[name]}
                    type="button"
                  >
                    {`{${name}}`}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="hn-row">
            <label className="hn-field">
              <span>{h.priority}</span>
              <select onChange={(e) => onChange({ priority: Number(e.target.value) })} value={event.priority}>
                {[1, 2, 3, 4, 5].map((value) => (
                  <option key={value} value={value}>{value} · {h.priorities[value]}</option>
                ))}
              </select>
              <FieldErrors messages={issuesByField.get(`${prefix}.priority`)} />
            </label>
            <label className="hn-field hn-field-grow">
              <span>{h.topic} <em className="muted-text">({h.optional})</em></span>
              <input
                maxLength={64}
                onChange={(e) => onChange({ topic: e.target.value === "" ? undefined : e.target.value })}
                placeholder={fill(h.topicPlaceholder, { topic: defaultTopic })}
                value={event.topic ?? ""}
              />
              <FieldErrors messages={issuesByField.get(`${prefix}.topic`)} />
            </label>
          </div>
        </div>

        <NotificationPreview defaultTopic={defaultTopic} event={event} h={h} vars={examples} />
      </div>

      {testOpen ? (
        <TestPanel
          code={code}
          dirty={changed}
          examples={examples}
          h={h}
          // Remount when the variable set changes so new `{var}` fields get their example value.
          key={variables.join(",")}
          saved={savedEvent !== undefined}
          t={t}
        />
      ) : null}
    </article>
  );
}

function EmojiPicker({ value, onChange, h }: { value: string; onChange: (value: string) => void; h: HostNotifText }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const preview = emojiChar(value);

  useEffect(() => {
    if (!open) return;
    const handler = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const filtered = EMOJI_CATALOG.filter(([name]) => name.includes(query.trim().toLowerCase()));
  const custom = query.trim().toLowerCase();

  return (
    <div className="hn-emoji" ref={rootRef}>
      <button className="hn-emoji-button" onClick={() => setOpen((current) => !current)} title={value} type="button">
        <span className="hn-emoji-char">{preview ?? "❔"}</span>
        <span className="hn-emoji-code">{value || "—"}</span>
      </button>
      {open ? (
        <div className="hn-emoji-pop">
          <input
            autoFocus
            className="text-input"
            onChange={(e) => setQuery(e.target.value)}
            placeholder={h.emojiSearch}
            value={query}
          />
          <div className="hn-emoji-grid">
            {filtered.map(([name, char]) => (
              <button
                className={name === value ? "hn-emoji-cell hn-emoji-cell-active" : "hn-emoji-cell"}
                key={name}
                onClick={() => { onChange(name); setOpen(false); setQuery(""); }}
                title={name}
                type="button"
              >
                {char}
              </button>
            ))}
          </div>
          {custom && EMOJI_RE.test(custom) && !filtered.some(([name]) => name === custom) ? (
            <button className="ghost-button" onClick={() => { onChange(custom); setOpen(false); setQuery(""); }} type="button">
              {h.emojiCustom} : <code>{custom}</code>
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function NotificationPreview({
  event,
  vars,
  defaultTopic,
  h,
}: {
  event: HostNotifEvent;
  vars: Record<string, string>;
  defaultTopic: string;
  h: HostNotifText;
}) {
  const emoji = emojiChar(event.emoji);
  // ntfy shows emoji tags in front of the title; unknown shortcodes are shown as plain tags.
  const title = renderTemplate(event.title, vars);
  return (
    <div className="hn-preview-wrap">
      <span className="hn-preview-label">{h.preview}</span>
      <div className={event.enabled ? "hn-preview" : "hn-preview hn-preview-muted"}>
        <div className="hn-preview-top">
          <span className="hn-preview-app">n</span>
          <span>ntfy</span>
          <span>·</span>
          <span>{event.topic || defaultTopic}</span>
          <span>·</span>
          <span>{h.previewNow}</span>
          {event.priority !== 3 ? (
            <span className={event.priority >= 4 ? "hn-preview-prio hn-preview-prio-high" : "hn-preview-prio"}>
              {event.priority >= 4 ? "▲".repeat(event.priority - 3) : "▼".repeat(3 - event.priority)}
            </span>
          ) : null}
        </div>
        <div className="hn-preview-title">
          {emoji ? `${emoji} ` : ""}
          {title || "…"}
        </div>
        <div className="hn-preview-body">{renderTemplate(event.message, vars)}</div>
        {!emoji && event.emoji ? <div className="hn-preview-tags">{event.emoji}</div> : null}
      </div>
      {!event.enabled ? <span className="muted-text">{h.previewMuted}</span> : null}
    </div>
  );
}

function TestPanel({
  code,
  examples,
  dirty,
  saved,
  h,
  t,
}: {
  code: string;
  examples: Record<string, string>;
  dirty: boolean;
  saved: boolean;
  h: HostNotifText;
  t: TranslationDictionary;
}) {
  const [values, setValues] = useState<Record<string, string>>(examples);
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<HostNotifTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function send() {
    setSending(true);
    setError(null);
    setResult(null);
    try {
      setResult(await testHostNotifEvent(code, values));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSending(false);
    }
  }

  const invalid = Object.values(values).some((value) => value.length > TEST_VALUE_MAX || /[\r\n]/.test(value));

  return (
    <div className="hn-test">
      <strong>{h.testTitle}</strong>
      {!saved ? <p className="warning-text">{h.testNotSaved}</p> : dirty ? <p className="warning-text">{h.testUsesSaved}</p> : null}
      {Object.keys(values).length > 0 ? (
        <div className="hn-test-vars">
          {Object.entries(values).map(([name, value]) => (
            <label className="hn-field" key={name}>
              <span>{name}</span>
              <input
                maxLength={TEST_VALUE_MAX}
                onChange={(e) => setValues((current) => ({ ...current, [name]: e.target.value.replace(/[\r\n]/g, " ") }))}
                value={value}
              />
            </label>
          ))}
        </div>
      ) : null}
      <div className="button-row">
        <button className="action-button" disabled={sending || !saved || invalid} onClick={() => void send()} type="button">
          {sending ? <><span className="inline-spinner" /> {h.testSending}</> : h.testSend}
        </button>
      </div>
      {error ? <ErrorBanner dismissLabel={t.dismiss} message={error} onDismiss={() => setError(null)} /> : null}
      {result ? (
        <div className={result.ok ? "hn-test-result" : "hn-test-result hn-test-result-error"}>
          {fill(result.ok ? h.testOk : h.testFailed, { code: result.return_code ?? "—" })}
          {!result.ok && result.message ? <> {result.message}</> : null}
          {result.stdout_log || result.stderr_log ? (
            <pre className="log-pre">{[result.stdout_log, result.stderr_log].filter(Boolean).join("\n")}</pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function HistoryTab({ codes, h, language, t }: { codes: string[]; h: HostNotifText; language: Language; t: TranslationDictionary }) {
  const [event, setEvent] = useState("");
  const [status, setStatus] = useState<HostNotifHistoryStatus | "">("");
  const [limit, setLimit] = useState(200);
  const [history, setHistory] = useState<HostNotifHistory | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setHistory(await getHostNotifHistory({ limit, event, status }));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [limit, event, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const eventOptions = useMemo(
    () => [...new Set([...codes, ...(history?.entries.map((entry) => entry.event) ?? [])])].filter(Boolean).sort(),
    [codes, history],
  );

  return (
    <section className="panel-card">
      <div className="hn-history-filters">
        <label className="field">
          <span>{h.historyEvent}</span>
          <select onChange={(e) => setEvent(e.target.value)} value={event}>
            <option value="">{h.historyAll}</option>
            {eventOptions.map((code) => <option key={code} value={code}>{code}</option>)}
          </select>
        </label>
        <label className="field">
          <span>{h.historyStatus}</span>
          <select onChange={(e) => setStatus(e.target.value as HostNotifHistoryStatus | "")} value={status}>
            <option value="">{h.historyAll}</option>
            {(["sent", "queued", "muted"] as const).map((item) => (
              <option key={item} value={item}>{h.statusLabels[item]}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>{h.historyLimit}</span>
          <select onChange={(e) => setLimit(Number(e.target.value))} value={limit}>
            {[50, 200, 500, 1000].map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <button className="ghost-button" disabled={loading} onClick={() => void load()} type="button">
          {loading ? <><span className="inline-spinner" /> {t.refresh}</> : t.refresh}
        </button>
      </div>

      {error ? <ErrorBanner dismissLabel={t.dismiss} message={error} onDismiss={() => setError(null)} /> : null}
      {history && history.skipped_lines > 0 ? (
        <p className="muted-text">{fill(h.historySkipped, { count: history.skipped_lines })}</p>
      ) : null}

      {!history && loading ? (
        <LoadingBlock label={t.loading} />
      ) : !history || history.entries.length === 0 ? (
        <EmptyState description="" title={h.historyEmpty} />
      ) : (
        <DataTable>
          <table>
            <thead>
              <tr>
                <th>{h.historyDate}</th>
                <th>{h.historyEvent}</th>
                <th>{h.historyStatus}</th>
                <th>{h.historyTitle}</th>
                <th>{h.historyMessage}</th>
              </tr>
            </thead>
            <tbody>
              {history.entries.map((entry, index) => (
                <tr key={`${entry.ts}-${entry.event}-${entry.status}-${index}`}>
                  <td className="hn-nowrap">{formatParisDateTime(entry.ts, language)}</td>
                  <td><code>{entry.event}</code></td>
                  <td>
                    <StatusBadge tone={entry.status === "sent" ? "success" : entry.status === "queued" ? "warning" : "neutral"}>
                      {h.statusLabels[entry.status] ?? entry.status}
                    </StatusBadge>
                  </td>
                  <td>{entry.title ?? "—"}</td>
                  <td className="hn-history-message">{entry.message ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </DataTable>
      )}
    </section>
  );
}
