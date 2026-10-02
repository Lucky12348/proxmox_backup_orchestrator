// Pure helpers for the host ntfy notification page (no React, so it can be unit-tested with `node --test`).
// Validation rules mirror apps/agent/src/agent/ntfy_notif.py — the agent stays the source of truth.

import type { HostNotifEvent, HostNotifTemplates } from "./types";

export const EVENT_CODE_RE = /^[a-z0-9_]+(\.[a-z0-9_]+)*$/;
export const EMOJI_RE = /^[a-z0-9_+-]{1,40}$/;
export const TOPIC_RE = /^[A-Za-z0-9_-]{1,64}$/;
export const VAR_KEY_RE = /^[A-Za-z0-9_]+$/;
export const TITLE_MAX = 60;
export const MESSAGE_MAX = 200;
export const LATE_AFTER_SEC_MAX = 86400;
export const TEST_VALUE_MAX = 100;

export const CATEGORY_ORDER = ["system", "ups", "net", "disk", "auth", "f2b", "test", "other"] as const;
export type HostNotifCategory = (typeof CATEGORY_ORDER)[number];

export interface BuiltinEventInfo {
  vars: Record<string, string>; // variable -> example value
  label: { fr: string; en: string };
}

// Events emitted by the host scripts. They can be edited/muted but not deleted.
export const BUILTIN_EVENTS: Record<string, BuiltinEventInfo> = {
  test: { vars: { texte: "Ceci est un test" }, label: { fr: "Notification de test", en: "Test notification" } },
  "system.boot": { vars: { kernel: "6.8.12-4-pve" }, label: { fr: "Démarrage de l'hôte", en: "Host boot" } },
  "system.boot_unclean": { vars: { kernel: "6.8.12-4-pve" }, label: { fr: "Démarrage après arrêt brutal", en: "Boot after unclean shutdown" } },
  "system.shutdown": { vars: {}, label: { fr: "Arrêt de l'hôte", en: "Host shutdown" } },
  "ups.onbatt": { vars: { charge: "87", runtime: "1520" }, label: { fr: "Onduleur sur batterie", en: "UPS on battery" } },
  "ups.online": { vars: { charge: "92" }, label: { fr: "Retour secteur", en: "Mains power restored" } },
  "ups.lowbatt": { vars: { charge: "18" }, label: { fr: "Batterie faible", en: "Low battery" } },
  "ups.shutdown": { vars: { charge: "10" }, label: { fr: "Arrêt sur onduleur", en: "UPS-triggered shutdown" } },
  "ups.fsd": { vars: {}, label: { fr: "Arrêt forcé (FSD)", en: "Forced shutdown (FSD)" } },
  "ups.commbad": { vars: {}, label: { fr: "Communication onduleur perdue", en: "UPS communication lost" } },
  "ups.commok": { vars: {}, label: { fr: "Communication onduleur rétablie", en: "UPS communication restored" } },
  "ups.replbatt": { vars: {}, label: { fr: "Batterie à remplacer", en: "Replace battery" } },
  "net.restored": { vars: { debut: "14:02", fin: "14:09", duree: "7 min" }, label: { fr: "Réseau rétabli", en: "Network restored" } },
  "disk.space": { vars: { details: "/ : 92 % utilisé" }, label: { fr: "Espace disque", en: "Disk space" } },
  "auth.web_ok": { vars: { user: "root@pam" }, label: { fr: "Connexion web réussie", en: "Web login succeeded" } },
  "auth.web_fail": { vars: { user: "root@pam", ip: "192.168.1.50" }, label: { fr: "Échec de connexion web", en: "Web login failed" } },
  "auth.ssh_ok": { vars: { user: "root", ip: "192.168.1.50" }, label: { fr: "Connexion SSH réussie", en: "SSH login succeeded" } },
  "auth.ssh_fail": { vars: { user: "root", ip: "203.0.113.7" }, label: { fr: "Échec de connexion SSH", en: "SSH login failed" } },
  "f2b.ban": { vars: { ip: "203.0.113.7", jail: "sshd" }, label: { fr: "IP bannie (fail2ban)", en: "IP banned (fail2ban)" } },
};

// Common ntfy emoji shortcodes (ntfy uses GitHub/gemoji names) with their rendering for the preview.
export const EMOJI_CATALOG: [string, string][] = [
  ["warning", "⚠️"], ["rotating_light", "🚨"], ["sos", "🆘"], ["stop_sign", "🛑"], ["no_entry", "⛔"],
  ["no_entry_sign", "🚫"], ["x", "❌"], ["exclamation", "❗"], ["bangbang", "‼️"], ["question", "❓"],
  ["information_source", "ℹ️"], ["white_check_mark", "✅"], ["heavy_check_mark", "✔️"], ["ok", "🆗"], ["new", "🆕"],
  ["bell", "🔔"], ["no_bell", "🔕"], ["loudspeaker", "📢"], ["mega", "📣"], ["tada", "🎉"],
  ["fire", "🔥"], ["skull", "💀"], ["zap", "⚡"], ["electric_plug", "🔌"], ["battery", "🔋"],
  ["low_battery", "🪫"], ["bulb", "💡"], ["computer", "💻"], ["desktop_computer", "🖥️"], ["floppy_disk", "💾"],
  ["cd", "💿"], ["minidisc", "💽"], ["file_folder", "📁"], ["card_file_box", "🗃️"], ["package", "📦"],
  ["globe_with_meridians", "🌐"], ["satellite", "📡"], ["signal_strength", "📶"], ["link", "🔗"], ["lock", "🔒"],
  ["unlock", "🔓"], ["key", "🔑"], ["closed_lock_with_key", "🔐"], ["shield", "🛡️"], ["cop", "👮"],
  ["bust_in_silhouette", "👤"], ["busts_in_silhouette", "👥"], ["door", "🚪"], ["hammer", "🔨"], ["wrench", "🔧"],
  ["gear", "⚙️"], ["hammer_and_wrench", "🛠️"], ["construction", "🚧"], ["arrows_counterclockwise", "🔄"], ["recycle", "♻️"],
  ["hourglass", "⌛"], ["hourglass_flowing_sand", "⏳"], ["stopwatch", "⏱️"], ["alarm_clock", "⏰"], ["calendar", "📅"],
  ["chart_with_upwards_trend", "📈"], ["chart_with_downwards_trend", "📉"], ["bar_chart", "📊"], ["thermometer", "🌡️"], ["snowflake", "❄️"],
  ["red_circle", "🔴"], ["orange_circle", "🟠"], ["yellow_circle", "🟡"], ["green_circle", "🟢"], ["large_blue_circle", "🔵"],
  ["heart", "❤️"], ["green_heart", "💚"], ["broken_heart", "💔"], ["+1", "👍"], ["-1", "👎"],
  ["eyes", "👀"], ["mag", "🔍"], ["memo", "📝"], ["clipboard", "📋"], ["email", "📧"],
  ["inbox_tray", "📥"], ["outbox_tray", "📤"], ["house", "🏠"], ["rocket", "🚀"], ["robot", "🤖"],
  ["penguin", "🐧"], ["whale", "🐳"], ["bug", "🐛"], ["test_tube", "🧪"], ["ghost", "👻"],
  ["sleeping", "😴"], ["scream", "😱"], ["partying_face", "🥳"], ["wave", "👋"], ["dart", "🎯"],
];

const EMOJI_MAP = new Map(EMOJI_CATALOG);

export function emojiChar(shortcode: string): string | null {
  return EMOJI_MAP.get(shortcode) ?? null;
}

export function isBuiltinEvent(code: string): boolean {
  return Object.prototype.hasOwnProperty.call(BUILTIN_EVENTS, code);
}

export function eventCategory(code: string): HostNotifCategory {
  const prefix = code.split(".")[0];
  return (CATEGORY_ORDER as readonly string[]).includes(prefix) && prefix !== "other" ? (prefix as HostNotifCategory) : "other";
}

export function groupEventCodes(codes: string[]): [HostNotifCategory, string[]][] {
  const groups = new Map<HostNotifCategory, string[]>();
  for (const code of codes) {
    const category = eventCategory(code);
    groups.set(category, [...(groups.get(category) ?? []), code]);
  }
  return CATEGORY_ORDER.filter((category) => groups.has(category)).map((category) => [
    category,
    (groups.get(category) ?? []).sort(),
  ]);
}

export function extractVariables(...texts: string[]): string[] {
  const found = new Set<string>();
  for (const text of texts) {
    for (const match of text.matchAll(/\{([A-Za-z0-9_]+)\}/g)) {
      found.add(match[1]);
    }
  }
  return [...found];
}

// Known variables first (in their documented order), then any extra `{var}` used in the texts.
export function eventVariables(code: string, event: Pick<HostNotifEvent, "title" | "message">): string[] {
  const known = Object.keys(BUILTIN_EVENTS[code]?.vars ?? {});
  const extra = extractVariables(event.title, event.message).filter((name) => !known.includes(name));
  return [...known, ...extra];
}

export function exampleVars(code: string, event: Pick<HostNotifEvent, "title" | "message">): Record<string, string> {
  const examples = BUILTIN_EVENTS[code]?.vars ?? {};
  return Object.fromEntries(eventVariables(code, event).map((name) => [name, examples[name] ?? name]));
}

export function renderTemplate(text: string, vars: Record<string, string>): string {
  return text.replace(/\{([A-Za-z0-9_]+)\}/g, (whole, name: string) =>
    Object.prototype.hasOwnProperty.call(vars, name) ? vars[name] : whole,
  );
}

export function isHttpUrl(value: string): boolean {
  if (value.length > 500 || /\s/.test(value)) return false;
  try {
    const url = new URL(value);
    return (url.protocol === "http:" || url.protocol === "https:") && url.host !== "";
  } catch {
    return false;
  }
}

export type ValidationCode =
  | "codeInvalid"
  | "topicInvalid"
  | "urlInvalid"
  | "lateInvalid"
  | "priorityInvalid"
  | "emojiInvalid"
  | "titleEmpty"
  | "titleTooLong"
  | "titleNewline"
  | "messageInvalid";

export interface ValidationIssue {
  field: string; // e.g. "defaults.topic" or "events.ups.onbatt.title"
  code: ValidationCode;
}

const CONTROL_CHARS_RE = /[\u0000-\u001f\u007f]/;
const CONTROL_CHARS_NO_NL_RE = /[\u0000-\u0009\u000b-\u001f\u007f]/;

export function validateTemplates(templates: HostNotifTemplates): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const { defaults, events } = templates;

  if (!TOPIC_RE.test(defaults.topic ?? "")) issues.push({ field: "defaults.topic", code: "topicInvalid" });
  for (const key of ["click", "icon"] as const) {
    const value = defaults[key];
    if (value !== undefined && value !== "" && !isHttpUrl(value)) issues.push({ field: `defaults.${key}`, code: "urlInvalid" });
  }
  if (defaults.late_after_sec !== undefined) {
    const value = defaults.late_after_sec;
    if (!Number.isInteger(value) || value < 0 || value > LATE_AFTER_SEC_MAX) {
      issues.push({ field: "defaults.late_after_sec", code: "lateInvalid" });
    }
  }

  for (const [code, event] of Object.entries(events)) {
    const prefix = `events.${code}`;
    if (code.length > 64 || !EVENT_CODE_RE.test(code)) {
      issues.push({ field: prefix, code: "codeInvalid" });
      continue;
    }
    if (!Number.isInteger(event.priority) || event.priority < 1 || event.priority > 5) {
      issues.push({ field: `${prefix}.priority`, code: "priorityInvalid" });
    }
    if (!EMOJI_RE.test(event.emoji)) issues.push({ field: `${prefix}.emoji`, code: "emojiInvalid" });
    if (!event.title.trim()) issues.push({ field: `${prefix}.title`, code: "titleEmpty" });
    else if ([...event.title].length > TITLE_MAX) issues.push({ field: `${prefix}.title`, code: "titleTooLong" });
    else if (CONTROL_CHARS_RE.test(event.title)) issues.push({ field: `${prefix}.title`, code: "titleNewline" });
    if ([...event.message].length > MESSAGE_MAX || CONTROL_CHARS_NO_NL_RE.test(event.message)) {
      issues.push({ field: `${prefix}.message`, code: "messageInvalid" });
    }
    if (event.topic !== undefined && !TOPIC_RE.test(event.topic)) issues.push({ field: `${prefix}.topic`, code: "topicInvalid" });
    for (const key of ["click", "icon"] as const) {
      const value = event[key];
      if (value !== undefined && value !== "" && !isHttpUrl(value)) issues.push({ field: `${prefix}.${key}`, code: "urlInvalid" });
    }
  }
  return issues;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// templates.json is hand-editable on the host: coerce it into a shape the page can render
// without crashing. Anything still invalid is reported by validateTemplates / the agent on save.
export function normalizeTemplates(raw: unknown): HostNotifTemplates {
  const source = isRecord(raw) ? raw : {};
  const defaults = isRecord(source.defaults) ? { ...source.defaults } : {};
  const events: Record<string, HostNotifEvent> = {};
  if (isRecord(source.events)) {
    for (const [code, value] of Object.entries(source.events)) {
      const event = isRecord(value) ? value : {};
      events[code] = {
        ...event,
        enabled: typeof event.enabled === "boolean" ? event.enabled : false,
        priority: typeof event.priority === "number" ? event.priority : 3,
        emoji: typeof event.emoji === "string" ? event.emoji : "",
        title: typeof event.title === "string" ? event.title : "",
        message: typeof event.message === "string" ? event.message : "",
      } as HostNotifEvent;
    }
  }
  return {
    defaults: { ...defaults, topic: typeof defaults.topic === "string" ? defaults.topic : "" } as HostNotifTemplates["defaults"],
    events,
  };
}

// Key-order-independent serialization, so removing then re-adding an optional key
// (e.g. an event topic) is not reported as an unsaved change.
export function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (isRecord(value)) {
    return `{${Object.keys(value)
      .filter((key) => value[key] !== undefined)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

export function newCustomEvent(code: string): HostNotifEvent {
  return { enabled: true, priority: 3, emoji: "bell", title: code.slice(0, TITLE_MAX), message: "" };
}

export function formatAge(seconds: number, language: "fr" | "en"): string {
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h ${String(minutes % 60).padStart(2, "0")}`;
  const days = Math.floor(hours / 24);
  return language === "fr" ? `${days} j` : `${days} d`;
}

export function formatParisDateTime(epochSeconds: number | null, language: "fr" | "en"): string {
  if (epochSeconds === null || !Number.isFinite(epochSeconds)) return "—";
  return new Intl.DateTimeFormat(language === "fr" ? "fr-FR" : "en-GB", {
    timeZone: "Europe/Paris",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(epochSeconds * 1000));
}
