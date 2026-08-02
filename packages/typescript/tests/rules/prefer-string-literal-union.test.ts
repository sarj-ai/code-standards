import { join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/prefer-string-literal-union.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: {
      projectService: {
        allowDefaultProject: ["*.ts*", "*/*.ts*", "*/*/*.ts*"],
      },
      tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
    },
  },
});

ruleTester.run("prefer-string-literal-union", rule, {
  valid: [
    // Already the prescribed pattern — a string-literal union.
    { code: 'type Status = "active" | "inactive";' },
    { code: 'interface Foo { status: "active" | "inactive"; }' },
    // Lone `status: string` with no corroboration — an open-set API DTO field.
    { code: "interface ApiUser { id: string; status: string; name: string; }" },
    { code: "class Dto { status: string = ''; }" },
    // DB-row cast whose `status` is also compared in a cluster elsewhere in the
    // file: the field must NOT be corroborated by the file-wide cluster.
    {
      code: "type Row = { status: string }; function ok(r: Row) { return true; }",
    },
    // Non-choice names never fire, even alongside a union sibling.
    {
      code: 'interface Foo { name: string; kind: "a" | "b"; }',
    },
    // A single-literal comparison is not a cluster.
    {
      code: "function f(x: string) { return x === 'active'; }",
    },
    {
      name: "requires two distinct comparison values",
      code: "function f(x: string) { return x === 'active' || x !== 'active'; }",
    },
    {
      name: "does not combine comparisons from different functions",
      code: "function first(x: string) { return x === 'active'; } function second(x: string) { return x === 'inactive'; }",
    },
    // Comparison against a single literal in a switch is not a cluster.
    {
      code: "function f(x: string) { switch (x) { case 'active': return 1; } }",
    },
    // Generated files opt out even with obvious violations.
    {
      code: "interface Foo { status: string; kind: 'a' | 'b'; } function g(x: string){ return x === 'a' || x === 'b'; }",
      filename: "api.gen.ts",
    },
    {
      code: "interface Foo { status: string; kind: 'a' | 'b'; }",
      filename: "src/generated/api.ts",
    },
    {
      code: "// @generated\ninterface Foo { status: string; kind: 'a' | 'b'; }",
    },
    {
      code: "interface Foo { status: string; kind: 'a' | 'b'; }",
      filename: "api.d.ts",
    },
    // Uppercase / long literals are not enum-shaped tokens.
    {
      code: "function f(x: string) { return x === 'Active Status Here' || x === 'Another Long Value'; }",
    },
    {
      name: "ignores tokens longer than 31 characters",
      code: "function f(x: string) { return x === 'abcdefghijklmnopqrstuvwxyzabcdef' || x === 'abcdefghijklmnopqrstuvwxyzabcdeg'; }",
    },
    // Boolean-ish string comparison is not a closed enum — it wants a boolean.
    {
      code: "function f(x: string) { return x === 'true' || x === 'false'; }",
    },
    // File paths are not enum tokens (contain `/` and `.`).
    {
      code: "function f(p: string) { return p === 'src/index.ts' || p === 'src/main.ts'; }",
    },
    // URLs are not enum tokens (contain `:` and `/`).
    {
      code: "function f(u: string) { return u === 'https://a.com' || u === 'https://b.com'; }",
    },
    // Dotted i18n keys are not enum tokens.
    {
      code: "function f(k: string) { return k === 'common.save' || k === 'common.cancel'; }",
    },
    // Single-character comparisons are flags/algebra, not a closed enum.
    {
      code: "function f(c: string) { return c === 'a' || c === 'b'; }",
    },
    // Empty-string guard mixed with a token stays below the token bar.
    {
      code: "function f(s: string) { return s === '' || s === 'active'; }",
    },
    // Operand already a string-literal union — comparing it is the target state,
    // not a violation. This is the whole point of the type-aware gate: without
    // it, every one of these fired.
    {
      code: "function f(m: 'read' | 'write') { return m === 'read' || m === 'write'; }",
    },
    // Same, via a switch.
    {
      code: "function f(r: 'admin' | 'user') { switch (r) { case 'admin': return 1; case 'user': return 2; default: return 0; } }",
    },
    // Operand typed via a NAMED union (the dominant real-world false positive: a
    // syntactic rule can't see through `CallStatus`; the type checker can).
    {
      code: "type CallStatus = 'open' | 'closed'; function h(s: CallStatus) { return s === 'open' || s === 'closed'; }",
    },
    // Named union reached through a member expression.
    {
      code: "type Tier = 'gold' | 'silver'; interface Account { plan: { tier: Tier } } function g(u: Account) { return u.plan.tier === 'gold' || u.plan.tier === 'silver'; }",
    },
    // Discriminated-union tag — `.type` is a literal union per member.
    {
      code: "type Ev = { type: 'add'; n: number } | { type: 'del'; id: string }; function r(e: Ev) { switch (e.type) { case 'add': return 1; case 'del': return 2; } }",
    },
    // Object-type param property already a union — member cluster is fine.
    {
      code: "function f(o: { tier: 'gold' | 'silver' }) { return o.tier === 'gold' || o.tier === 'silver'; }",
    },
    // Local variable already typed as a union.
    {
      code: "function f(x: string) { const m: 'read' | 'write' = x as 'read' | 'write'; return m === 'read' || m === 'write'; }",
    },
    // Multiple bare choice fields but no union sibling to corroborate — a
    // passthrough DTO from an untyped backend.
    {
      code: "interface Api { status: string; type: string; mode: string; }",
    },
    // Destructured prop already typed as a union (the shadcn/React shape).
    {
      code: 'function SheetContent({ side = "right" }: { side?: "top" | "right" | "bottom" | "left" }) { return side === "right" || side === "left"; }',
    },
    // Shorthand destructure with a direct inline union annotation.
    {
      code: 'function Badge({ variant }: { variant: "default" | "outline" | "ghost" }) { return variant === "default" || variant === "outline"; }',
    },
    // Union that mixes a named type and a literal — already a closed union.
    {
      code: 'type AgentState = "idle" | "running"; function g(x: AgentState | "connecting") { return x === "connecting" || x === "idle"; }',
    },
    // Provenance guard: the value comes from a type we do not own, so a union is
    // not an available fix. DOM `getComputedStyle().overflowY` is `string` in
    // lib.dom, read directly...
    {
      code: 'function f(el: Element) { return getComputedStyle(el).overflowY === "auto" || getComputedStyle(el).overflowY === "scroll"; }',
    },
    // ...and via a local const bound to that external property access.
    {
      code: 'function f(el: Element) { const o = getComputedStyle(el).overflowY; if (o === "auto" || o === "scroll") return 1; return 0; }',
    },
    // A property member on a DOM type (`Navigator.language`), typed `string`.
    {
      code: 'function f() { return navigator.language === "en" || navigator.language === "fr"; }',
    },
    // The return of an external method (`URLSearchParams.get`).
    {
      code: 'function f(p: URLSearchParams) { const e = p.get("error"); if (e === "duplicate" || e === "missing") return 1; return 0; }',
    },
    // A standard-library string method chain (`.toLowerCase()`).
    {
      code: 'function f(name: string) { const ext = name.split(".").pop()!.toLowerCase(); if (ext === "csv" || ext === "xlsx") return 1; return 0; }',
    },
    // Keys from `Object.entries` are structurally `string`, not our field.
    {
      code: 'function f(o: Record<string, unknown>) { for (const [key] of Object.entries(o)) { if (key === "from" || key === "to") continue; } }',
    },
    // FP-5: the PARSER that produces the union. Its parameter must be `string` —
    // this is the narrowing boundary, and the declared return type is the very
    // union the literals belong to. Rewriting `s` as the union is impossible.
    {
      code: "type StatusFilter = 'expired' | 'pending' | 'passed' | 'failed' | null;\nfunction parseStatusFilter(s: string): StatusFilter {\n  return s === 'expired' || s === 'pending' || s === 'passed' || s === 'failed' ? s : null;\n}",
    },
    // FP-5: same narrowing boundary via a `switch`.
    {
      code: "type Mode = 'read' | 'write';\nfunction parseMode(s: string): Mode | null { switch (s) { case 'read': return 'read'; case 'write': return 'write'; default: return null; } }",
    },
    // FP-5: through an async boundary — `Promise<Mode | null>` is awaited first.
    {
      code: "type Mode = 'read' | 'write';\nasync function parseMode(s: string): Promise<Mode | null> { if (s === 'read') return 'read'; if (s === 'write') return 'write'; return null; }",
    },
    // FP-5: a vendor-owned OPEN set (Slack ships dozens of `subtype`s and adds
    // more) listed in `ignoreFields`.
    {
      code: 'interface SlackEvent { subtype: string; kind: "message" | "reaction"; }',
      options: [{ ignoreFields: ["subtype"] }],
    },
  ],
  invalid: [
    // Choice field corroborated by a sibling string-literal union.
    {
      code: 'interface Order { status: string; kind: "a" | "b"; }',
      errors: [{ messageId: "bareChoiceField", data: { name: "status" } }],
    },
    {
      name: "reports a trailing choice word in a type literal",
      code: 'type Order = { callStatus: string; kind: "a" | "b" };',
      errors: [
        { messageId: "bareChoiceField", data: { name: "callStatus" } },
      ],
    },
    {
      name: "reports a quoted snake-case choice field",
      code: 'type Job = { "delivery_mode": string; stage: "new" | "done" };',
      errors: [
        { messageId: "bareChoiceField", data: { name: "delivery_mode" } },
      ],
    },
    // A comparison cluster on a raw-`string` field fires the cluster diagnostic.
    {
      code: "interface Order { callStatus: string; } function h(o: Order) { return o.callStatus === 'open' || o.callStatus === 'closed'; }",
      errors: [{ messageId: "comparisonCluster" }],
    },
    // Class field corroborated by sibling union.
    {
      code: 'class Job { state: string; priority: "low" | "high" = "low"; }',
      errors: [{ messageId: "bareChoiceField", data: { name: "state" } }],
    },
    // Pure comparison cluster on a raw-`string` param: 2 distinct literals.
    {
      code: "function route(mode: string) { if (mode === 'read') return 1; if (mode === 'write') return 2; return 0; }",
      errors: [{ messageId: "comparisonCluster", data: { key: "mode" } }],
    },
    {
      name: "recognizes loose and reversed inequality comparisons",
      code: "function route(mode: string) { const reading = mode != 'read'; const writing = 'write' != mode; return reading || writing; }",
      errors: [{ messageId: "comparisonCluster", data: { key: "mode" } }],
    },
    {
      name: "accepts underscores and hyphens in enum-shaped tokens",
      code: "function route(status: string) { return status === 'in_progress' || status === 'on-hold'; }",
      errors: [{ messageId: "comparisonCluster", data: { key: "status" } }],
    },
    {
      name: "does not use a same-named comparison to corroborate a field",
      code: "type Row = { status: string }; function route(status: string) { return status === 'active' || status === 'inactive'; }",
      errors: [{ messageId: "comparisonCluster", data: { key: "status" } }],
    },
    // Cluster via `switch` on a raw-`string` param.
    {
      code: "function pick(role: string) { switch (role) { case 'admin': return 1; case 'user': return 2; default: return 0; } }",
      errors: [{ messageId: "comparisonCluster", data: { key: "role" } }],
    },
    // Member-expression cluster where the member is raw `string`.
    {
      code: "function f(o: { tier: string }) { return o.tier === 'gold' || o.tier === 'silver'; }",
      errors: [{ messageId: "comparisonCluster", data: { key: "o.tier" } }],
    },
    // Bare member-expression cluster, member typed `string` through a named type.
    {
      code: "interface Account { plan: { tier: string } } function g(u: Account) { return u.plan.tier === 'gold' || u.plan.tier === 'silver'; }",
      errors: [{ messageId: "comparisonCluster", data: { key: "u.plan.tier" } }],
    },
    // A genuine 2-element enum on a raw-`string` member still fires.
    {
      code: "function d(o: { direction: string }) { return o.direction === 'inbound' || o.direction === 'outbound'; }",
      errors: [{ messageId: "comparisonCluster", data: { key: "o.direction" } }],
    },
    // `string | undefined` still counts as raw string — the general-string
    // member is present, so a nullable pseudo-enum is flagged.
    {
      code: "function f(x: string | undefined) { return x === 'on' || x === 'off'; }",
      errors: [{ messageId: "comparisonCluster", data: { key: "x" } }],
    },
    // FP-5 must not over-suppress: a declared string-literal return that does
    // NOT contain the compared literals is not the narrowing boundary for them.
    {
      code: "type Mode = 'read' | 'write';\nfunction pick(kind: string): Mode { return kind === 'inbound' || kind === 'outbound' ? 'read' : 'write'; }",
      errors: [{ messageId: "comparisonCluster", data: { key: "kind" } }],
    },
    // FP-5 must not over-suppress: a raw-`string` return type exempts nothing.
    {
      code: "function route(mode: string): string { if (mode === 'read') return 'r'; if (mode === 'write') return 'w'; return ''; }",
      errors: [{ messageId: "comparisonCluster", data: { key: "mode" } }],
    },
    // FP-5: `ignoreFields` is scoped to the listed names — a sibling choice
    // field that is NOT listed still fires.
    {
      code: 'interface SlackEvent { subtype: string; status: string; kind: "message" | "reaction"; }',
      options: [{ ignoreFields: ["subtype"] }],
      errors: [{ messageId: "bareChoiceField", data: { name: "status" } }],
    },
  ],
});

const syntaxOnlyRuleTester = new RuleTester({
  languageOptions: { parser: tsParser },
});

syntaxOnlyRuleTester.run("prefer-string-literal-union without type information", rule, {
  valid: [
    {
      name: "leaves comparison clusters inert without resolved types",
      code: "function route(mode: string) { return mode === 'read' || mode === 'write'; }",
    },
  ],
  invalid: [],
});
