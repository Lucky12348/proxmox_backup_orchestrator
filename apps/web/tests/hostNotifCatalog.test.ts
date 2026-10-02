import assert from "node:assert/strict";
import test from "node:test";

import {
  eventCategory,
  eventVariables,
  exampleVars,
  formatAge,
  formatParisDateTime,
  groupEventCodes,
  isBuiltinEvent,
  normalizeTemplates,
  stableStringify,
  renderTemplate,
  validateTemplates,
} from "../src/hostNotifCatalog.ts";

const valid = {
  defaults: { topic: "pve-alerts", click: "https://pve.lan:8006", icon: "", late_after_sec: 300 },
  events: {
    "ups.onbatt": { enabled: true, priority: 4, emoji: "battery", title: "Sur batterie", message: "{charge}% / {runtime}s" },
  },
};

test("categories come from the code prefix, unknown prefixes go to other", () => {
  assert.equal(eventCategory("ups.onbatt"), "ups");
  assert.equal(eventCategory("test"), "test");
  assert.equal(eventCategory("backup.nightly_ok"), "other");
  assert.equal(eventCategory("other.x"), "other");
  assert.deepEqual(
    groupEventCodes(["test", "ups.online", "auth.ssh_ok", "ups.fsd", "zzz"]).map(([category, codes]) => [category, codes]),
    [["ups", ["ups.fsd", "ups.online"]], ["auth", ["auth.ssh_ok"]], ["test", ["test"]], ["other", ["zzz"]]],
  );
});

test("known variables come first, then extra ones used in the texts", () => {
  assert.deepEqual(eventVariables("f2b.ban", { title: "Ban {ip}", message: "{jail} {host}" }), ["ip", "jail", "host"]);
  assert.deepEqual(exampleVars("custom.x", { title: "{a}", message: "" }), { a: "a" });
  assert.equal(isBuiltinEvent("system.shutdown"), true);
  assert.equal(isBuiltinEvent("backup.nightly_ok"), false);
});

test("renderTemplate replaces known variables and keeps unknown placeholders", () => {
  assert.equal(renderTemplate("{charge}% left, {missing}", { charge: "80" }), "80% left, {missing}");
});

test("validateTemplates accepts a valid document", () => {
  assert.deepEqual(validateTemplates(valid), []);
});

test("validateTemplates mirrors the agent rules", () => {
  const broken = structuredClone(valid) as typeof valid & { events: Record<string, any> };
  broken.defaults.topic = "bad topic";
  broken.defaults.click = "ftp://x";
  broken.defaults.late_after_sec = 90000;
  broken.events["ups.onbatt"] = { enabled: true, priority: 7, emoji: "Battery", title: "x".repeat(61), message: "y".repeat(201) };
  broken.events["Bad.Code"] = { enabled: true, priority: 3, emoji: "bell", title: "t", message: "" };
  broken.events["auth.ssh_ok"] = { enabled: true, priority: 3, emoji: "bell", title: "  ", message: "", topic: "a/b" };
  const codes = validateTemplates(broken).map((issue) => `${issue.field}:${issue.code}`);
  assert.deepEqual(codes.sort(), [
    "defaults.click:urlInvalid",
    "defaults.late_after_sec:lateInvalid",
    "defaults.topic:topicInvalid",
    "events.Bad.Code:codeInvalid",
    "events.auth.ssh_ok.title:titleEmpty",
    "events.auth.ssh_ok.topic:topicInvalid",
    "events.ups.onbatt.emoji:emojiInvalid",
    "events.ups.onbatt.message:messageInvalid",
    "events.ups.onbatt.priority:priorityInvalid",
    "events.ups.onbatt.title:titleTooLong",
  ].sort());
});

test("title length counts characters, not UTF-16 units", () => {
  const doc = structuredClone(valid);
  doc.events["ups.onbatt"].title = "🔋".repeat(60);
  assert.deepEqual(validateTemplates(doc), []);
});

test("formatting helpers", () => {
  assert.equal(formatAge(42, "fr"), "42 s");
  assert.equal(formatAge(720, "fr"), "12 min");
  assert.equal(formatAge(3 * 3600 + 5 * 60, "fr"), "3 h 05");
  assert.equal(formatAge(5 * 86400, "en"), "5 d");
  // 2026-01-15T12:00:00Z is 13:00 in Paris (CET), 2026-07-15T12:00:00Z is 14:00 (CEST).
  assert.match(formatParisDateTime(Date.UTC(2026, 0, 15, 12) / 1000, "fr"), /13:00:00/);
  assert.match(formatParisDateTime(Date.UTC(2026, 6, 15, 12) / 1000, "fr"), /14:00:00/);
  assert.equal(formatParisDateTime(null, "fr"), "—");
});

test("normalizeTemplates never crashes on a malformed templates.json", () => {
  assert.deepEqual(normalizeTemplates(null), { defaults: { topic: "" }, events: {} });
  assert.deepEqual(normalizeTemplates({ defaults: [], events: "x" }), { defaults: { topic: "" }, events: {} });
  const result = normalizeTemplates({ defaults: { topic: "t", icon: "" }, events: { "ups.fsd": { title: 3, tags: ["x"] }, bad: null } });
  assert.deepEqual(result.events["ups.fsd"], { title: "", tags: ["x"], enabled: false, priority: 3, emoji: "", message: "" });
  assert.equal(result.events.bad.message, "");
  assert.equal(result.defaults.icon, "");
});

test("stableStringify ignores key order and undefined values", () => {
  assert.equal(stableStringify({ b: 1, a: { d: 2, c: [1, { y: 1, x: 2 }] } }), stableStringify({ a: { c: [1, { x: 2, y: 1 }], d: 2 }, b: 1 }));
  assert.equal(stableStringify({ a: 1, topic: undefined }), stableStringify({ a: 1 }));
  assert.notEqual(stableStringify({ a: 1 }), stableStringify({ a: 2 }));
  assert.equal(stableStringify(null), "null");
});
