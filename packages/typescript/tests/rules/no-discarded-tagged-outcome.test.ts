// vitest: shared-module-graph
import { expect, it } from "vitest";

import { RULES } from "../../src/catalog.js";
import rule from "../../src/rules/no-discarded-tagged-outcome.js";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";
import { ruleTester } from "./_tester.js";

ruleTester().run("no-discarded-tagged-outcome", rule, {
  valid: [
  "type Outcome = { ok: true } | { ok: false }; function save(): Outcome { return { ok: true }; } eval('save = () => undefined'); save();",
  "type Outcome = { ok: true } | { ok: false }; function save(): Outcome { return { ok: true }; } Function('globalThis.save = () => undefined')(); save();",

  "type Outcome = { ok: true; value: string } | { ok: false; error: string }; function save(): Outcome { return { ok: true, value: 'saved' }; } const result = save(); if (!result.ok) report(result.error);",
  "type Outcome = { ok: true; value: string } | { ok: false; error: string }; function save(): Outcome { return { ok: true, value: 'saved' }; } function run() { return save(); }",
  "function save(): void { sideEffect(); } save();",
  "type Event = { kind: 'keyboard'; key: string } | { kind: 'mouse'; x: number }; function dispatch(): Event { return { kind: 'mouse', x: 1 }; } dispatch();",
  "import { save } from \"./external.js\"; save();",
  "function save() { return { ok: true }; } save();",
  "type Outcome = { ok: true; value: string } | { ok: false; error: string }; function save(): Outcome { return { ok: true, value: 'saved' }; } function run(save: () => void) { save(); }",
  "type Outcome = { ok: true } | { ok: false } | undefined; function save(): Outcome {} save();",
  "type Outcome = { ok: true } | { ok: false }; async function save(): Promise<Outcome> { return { ok: true }; } save();",
  "type Outcome = { ok: true } | { ok: false }; function save(): void; function save(): Outcome { return { ok: true }; } save();",
  "type Outcome = { ok: true; then(resolve: (value: string) => void): void } | { ok: false; then(resolve: (value: string) => void): void }; function save(): Outcome { return { ok: false, then(resolve) { resolve('handled'); } }; } async function run() { await save(); }"
],
  invalid: [
  {
    "code": "type Outcome = { ok: true; value: string } | { ok: false; error: string }; function save(): Outcome { return { ok: true, value: 'saved' }; } save();",
    "errors": [
      {
        "messageId": "noDiscardedTaggedOutcome"
      }
    ]
  },
  {
    "code": "type Outcome = { ok: true; value: string } | { ok: false; error: string }; function save(): Outcome { return { ok: true, value: 'saved' }; } void save();",
    "errors": [
      {
        "messageId": "noDiscardedTaggedOutcome"
      }
    ]
  },
  {
    "code": "type Outcome = { ok: true } | { ok: false }; const save = (): Outcome => ({ ok: true }); save();",
    "errors": [
      {
        "messageId": "noDiscardedTaggedOutcome"
      }
    ]
  },
  {
    "code": "interface Accepted { kind: 'accepted'; value: string } interface Rejected { kind: 'rejected'; reason: string } type Outcome = Accepted | Rejected; function save(): Outcome { return { kind: 'accepted', value: 'x' }; } save();",
    "errors": [
      {
        "messageId": "noDiscardedTaggedOutcome"
      }
    ]
  },
  {
    "code": "type Outcome = { ok: true } | { ok: false }; async function save(): Promise<Outcome> { return { ok: true }; } async function run() { await save(); }",
    "errors": [
      {
        "messageId": "noDiscardedTaggedOutcome"
      }
    ]
  }
],
});

it("executes the documented examples", async () => {
  await expect(verifyRuleExamples(RULES["no-discarded-tagged-outcome"])).resolves.toBeGreaterThan(0);
});
