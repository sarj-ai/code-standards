// vitest: shared-module-graph
import rule from "../../src/rules/prefer-named-literal-union.js";
import { ruleTester } from "./_tester.js";

const REPEATED = "interface State { current: 'queued' | 'running' | 'done'; previous: 'queued' | 'running' | 'done' }";

ruleTester().run("prefer-named-literal-union", rule, {
  valid: [
    "interface Single { direction: 'down' | 'flat' | 'up' }",
    "type State = 'queued' | 'running'; interface Item { current: State; previous: State }",
    "interface Worker { runNext(): Promise<'progress' | 'idle'>; retry(): Promise<'progress' | 'idle'> }",
    "interface Draft { current: 'queued' | 'running' | 'done'; previous: 'queued' | 'running' | 'failed' }",
    "interface Draft { current: 'queued' | 'running' | number; previous: 'queued' | 'running' | number }",
    "interface Row { id: string; name: string; state: string } type A = Pick<Row, 'id' | 'name' | 'state'>; type B = Pick<Row, 'id' | 'name' | 'state'>;",
    "type State = 'queued' | 'running' | 'done'; interface Draft { state: 'queued' | 'running' | 'done' | null }",
    "interface Draft { current: 'queued' | 'running' | null; previous: 'queued' | 'running' | null }",
    "interface Draft { current: 'queued' | 'running' | 'queued'; previous: 'running' | 'queued' | 'running' }",
    "export interface Exported { update: (state: 'down' | 'flat' | 'up') => void; close: (state: 'up' | 'flat' | 'down') => void }",
    { filename: "src/drafts.test.ts", code: REPEATED },
    { filename: "src/drafts.generated.ts", code: REPEATED },
    { code: "// @generated\n" + REPEATED },
  ],
  invalid: [
    {
      name: "reports later three-member uses across distinct type shapes",
      code: "interface A { type: 'boolean' | 'number' | 'text' }\ntype B = { type: 'number' | 'text' | 'boolean' };\ntype C = { type: 'text' | 'boolean' | 'number' };",
      output: null,
      errors: [{ messageId: "nameRepeatedUnion", line: 2 }, { messageId: "nameRepeatedUnion", line: 3 }],
    },
    {
      name: "reports two repeated three-member annotations",
      code: "interface A { direction: 'down' | 'flat' | 'up' }\ninterface B { direction: 'down' | 'flat' | 'up' }",
      errors: [{ messageId: "nameRepeatedUnion", line: 2 }],
    },
    {
      name: "reports later two-member uses after three occurrences",
      code: "interface A { kind: 'demo' | 'poc' }\ninterface B { kind: 'poc' | 'demo' }\ninterface C { kind: 'demo' | 'poc' }",
      errors: [{ messageId: "nameRepeatedUnion", line: 2 }, { messageId: "nameRepeatedUnion", line: 3 }],
    },
    {
      name: "fixes a single inline use of an exported alias declared later",
      code: "interface Receipt { channel: 'whatsapp' | 'email' | 'client_slack' } export type Channel = 'whatsapp' | 'email' | 'client_slack';",
      output: "interface Receipt { channel: Channel } export type Channel = 'whatsapp' | 'email' | 'client_slack';",
      errors: [{ messageId: "useExistingAlias" }],
    },
    {
      name: "reuses a private alias by literal value while preserving null and undefined",
      code: 'type State = "queued" | "running" | null | undefined; interface Draft { state: undefined | \'running\' | null | \'queued\' }',
      output: 'type State = "queued" | "running" | null | undefined; interface Draft { state: State }',
      errors: [{ messageId: "useExistingAlias" }],
    },
    {
      name: "leaves two visible aliases for the author to disambiguate",
      code: "type A = 'a' | 'b'; type B = 'a' | 'b'; interface Item { kind: 'a' | 'b' }",
      output: null,
      errors: [{ messageId: "useExistingAlias" }],
    },
    {
      name: "preserves a use shadowed by a type parameter",
      code: "type Kind = 'a' | 'b'; interface Item<Kind> { kind: 'a' | 'b' }",
      output: null,
      errors: [{ messageId: "useExistingAlias" }],
    },
    {
      name: "resolves the type alias past a value-only binding",
      code: "type Kind = 'a' | 'b'; function f() { const Kind = 2; const item: 'a' | 'b' = 'a'; return { Kind, item }; }",
      output: "type Kind = 'a' | 'b'; function f() { const Kind = 2; const item: Kind = 'a'; return { Kind, item }; }",
      errors: [{ messageId: "useExistingAlias" }],
    },
    {
      name: "preserves aliases that require type arguments",
      code: "type Kind<T> = 'a' | 'b'; interface Item { kind: 'a' | 'b' }",
      output: null,
      errors: [{ messageId: "useExistingAlias" }],
    },
    {
      name: "preserves comments inside an inline union",
      code: "type Kind = 'a' | 'b'; interface Item { kind: 'a' /* useful */ | 'b' }",
      output: null,
      errors: [{ messageId: "useExistingAlias" }],
    },
    {
      name: "leaves the exported callback occurrence to its owning rule",
      code: "export interface Options { change: (direction: 'down' | 'flat' | 'up') => void }\ninterface Item { direction: 'down' | 'flat' | 'up' }",
      errors: [{ messageId: "nameRepeatedUnion", line: 2 }],
    },
  ],
});
