import rule from "../../src/rules/require-assert-never.js";
import { FIXTURES, RuleTester, ruleTester, typed } from "./_tester.js";

const RULE_TESTER = ruleTester({ cwd: FIXTURES });

const ASSERT_NEVER_DEFAULT_EXAMPLE =
  "function assertNever(value: never): never { throw new Error(`Unexpected kind: ${String(value)}`); }\ndeclare const kind: 'a' | 'b';\nswitch (kind) { case 'a': break; case 'b': break; default: assertNever(kind); }";
const EMPTY_DEFAULT_EXAMPLE = "declare const kind: 'a' | 'b';\nswitch (kind) { case 'a': break; case 'b': break; default: }";
const SAFE_AUTOFIX_EXAMPLE =
  "function assertNever(_value: never): void {}\nexport function render(kind: 'a' | 'b'): number { switch (kind) { case 'a': return 1; case 'b': return 2; default: break; } return 0; }";
const SAFE_AUTOFIX_FIXED_EXAMPLE =
  "function assertNever(_value: never): void {}\nexport function render(kind: 'a' | 'b'): number { switch (kind) { case 'a': return 1; case 'b': return 2; default: void (kind satisfies never); break; } return 0; }";
const SYMBOL_SWITCH_ISOLATION =
  "declare const left: unique symbol; declare const right: unique symbol; declare const state: typeof left | typeof right; switch (state) { case left: break; case right: break; default: break; } switch (state) { case left: break; default: break; }";

new RuleTester({ eslintCompat: true, languageOptions: { parserOptions: { lang: "ts" } } }).run("require-assert-never without type information", rule, {
  valid: [{ name: "reports nothing without types", code: EMPTY_DEFAULT_EXAMPLE, settings: { sarj: { typeAware: false } } }],
  invalid: [],
});

RULE_TESTER.run("require-assert-never", rule, typed({
  valid: [
    {
      name: "distinct unique symbols with identical display names are not interchangeable states",
      code: "declare const left: unique symbol; declare const right: unique symbol; declare const state: typeof left | typeof right; switch (state) { case left: break; default: break; }",
    },
    {
      name: "duplicate cases for one symbol do not cover a different symbol",
      code: "declare const left: unique symbol; declare const right: unique symbol; declare const state: typeof left | typeof right; switch (state) { case left: break; case left: break; default: break; }",
    },
    {
      name: "unique symbol properties retain their nominal identities",
      code: "interface Left { readonly tag: unique symbol } interface Right { readonly tag: unique symbol } declare const left: Left; declare const state: Left['tag'] | Right['tag']; switch (state) { case left.tag: break; default: break; }",
    },
    {
      name: "numeric case values do not cover opaque symbol identities",
      code: "declare const token: unique symbol; declare const state: typeof token | 86; switch (state) { case 86: break; default: break; }",
    },
    {
      name: "does not treat one union-valued case as covering every possible value",
      code: "declare const kind: 'a' | 'b'; declare const choice: 'a' | 'b'; switch (kind) { case choice: break; default: }",
    },
    {
      name: "does not count an open case expression as finite coverage",
      code: "declare const kind: 'a' | 'b'; declare const choice: string; switch (kind) { case choice: break; default: }",
    },
    {
      name: "accepts the documented exhaustive default",
      code: ASSERT_NEVER_DEFAULT_EXAMPLE,
    },
    {
      name: "allows a switch with no default",
      code: `
        switch (kind) {
          case 'a': break;
          case 'b': break;
        }
      `,
    },
    {
      name: "does not require assertNever for an open string discriminant",
      code: `declare const kind: string;
        switch (kind) {
          case 'a': break;
          default:
        }
      `,
    },
    {
      name: "does not report a non-exhaustive finite union",
      code: `declare const kind: 'a' | 'b';
        switch (kind) {
          case 'a': break;
          default:
        }
      `,
    },
    {
      name: "allows a bare assertNever call",
      code: `
        switch (kind) {
          case 'a': break;
          default: assertNever(kind);
        }
      `,
    },
    {
      name: "allows throwing the result of assertNever",
      code: `
        switch (kind) {
          case 'a': break;
          default: throw assertNever(kind);
        }
      `,
    },
    {
      name: "allows a namespaced assertNever call",
      code: `
        switch (kind) {
          case 'a': break;
          default: utils.assertNever(kind);
        }
      `,
    },
    {
      name: "allows returning a namespaced assertNever call",
      code: `
        switch (kind) {
          case 'a': return 1;
          default: return utils.assertNever(kind);
        }
      `,
    },
    {
      name: "allows assertNever inside a block",
      code: `
        switch (kind) {
          case 'a': break;
          default: {
            const _exhaustive = kind;
            assertNever(_exhaustive);
          }
        }
      `,
    },
    {
      name: "allows a reducer default that returns existing state",
      code: `
        switch (action.type) {
          case 'inc': return state + 1;
          case 'dec': return state - 1;
          default: return state;
        }
      `,
    },
    {
      name: "allows a default that returns a fallback call",
      code: `
        switch (httpStatus) {
          case 200: return ok();
          case 404: return notFound();
          default: return fallback();
        }
      `,
    },
    {
      name: "allows a default that throws an error",
      code: `
        switch (kind) {
          case 'a': break;
          default: throw new Error('unreachable');
        }
      `,
    },
    {
      name: "allows a default that calls a handler",
      code: `
        switch (kind) {
          case 'a': break;
          default: logUnknown(kind);
        }
      `,
    },
    {
      name: "leaves a non-exhaustive break default to the upstream rule",
      code: `declare const kind: 'a' | 'b' | 'c';
        switch (kind) {
          case 'a': break;
          case 'b': break;
          default: break;
        }
      `,
    },
    {
      name: "allows a fully covered boolean default",
      code: `declare const enabled: boolean;
        switch (enabled) {
          case true: break;
          case false: break;
          default: break;
        }
      `,
      filename: "covered-boolean.ts",
    },
    {
      name: "allows conditional runtime handling",
      code: `
        switch (kind) {
          case 'a': break;
          default: if (shouldHandle) handle(kind);
        }
      `,
    },
    {
      name: "allows an initial default that falls through",
      code: `
        switch (plurality) {
          default:
          case CursorPlurality.Single:
            handleSingle();
            break;
        }
      `,
    },
    {
      name: "allows a middle default that falls through",
      code: `
        switch (kind) {
          case 'a':
          default:
          case 'b':
            handle();
            break;
        }
      `,
    },
    {
      name: "allows a comment-documented empty default",
      code: `
        switch (setting) {
          case 'on': enable(); break;
          default: // Do nothing, defaults should be used
        }
      `,
    },
    {
      name: "allows a comment-documented empty block",
      code: `
        switch (setting) {
          case 'on': enable(); break;
          default: { /* intentionally left blank */ }
        }
      `,
    },
  ],
  invalid: [
    {
      name: "symbol coverage does not leak from another switch in the same program",
      code: SYMBOL_SWITCH_ISOLATION,
      errors: [{ messageId: "missingAssertNever", line: 1, column: SYMBOL_SWITCH_ISOLATION.indexOf("default") + 1 }],
      output: null,
    },
    {
      name: "all distinct symbol identities establish exhaustive coverage",
      code: "declare const left: unique symbol; declare const right: unique symbol; declare const state: typeof left | typeof right; switch (state) { case left: break; case right: break; default: break; }",
      errors: [{ messageId: "missingAssertNever" }],
      output: null,
    },
    {
      name: "a typed symbol alias covers its original identity",
      code: "declare const left: unique symbol; declare const right: unique symbol; const alias: typeof left = left; declare const state: typeof left | typeof right; switch (state) { case alias: break; case right: break; default: break; }",
      errors: [{ messageId: "missingAssertNever" }],
      output: null,
    },
    {
      name: "keeps the witness local when an existing no-op helper is present",
      code: SAFE_AUTOFIX_EXAMPLE,
      errors: [{ messageId: "missingAssertNever" }],
      output:
        SAFE_AUTOFIX_FIXED_EXAMPLE,
    },
    {
      name: "adds a self-contained witness without a module helper",
      code: "export function render(kind: 'a' | 'b'): number { switch (kind) { case 'a': return 1; case 'b': return 2; default: break; } return 0; }",
      errors: [{ messageId: "missingAssertNever" }],
      output: "export function render(kind: 'a' | 'b'): number { switch (kind) { case 'a': return 1; case 'b': return 2; default: void (kind satisfies never); break; } return 0; }",
    },
    {
      name: "a parameter shadowing the unused helper remains local",
      code: SAFE_AUTOFIX_EXAMPLE.replaceAll("kind", "assertNever"),
      errors: [{ messageId: "missingAssertNever" }],
      output: SAFE_AUTOFIX_FIXED_EXAMPLE.replaceAll("kind", "assertNever"),
    },
    {
      name: "retains singleton literal case aliases",
      code: "declare const kind: 'a' | 'b'; const first = 'a' as const; const second = 'b' as const; switch (kind) { case first: break; case second: break; default: }",
      errors: [{ messageId: "missingAssertNever" }],
      output: null,
    },
    {
      name: "reports the documented empty default",
      code: EMPTY_DEFAULT_EXAMPLE,
      errors: [{ messageId: "missingAssertNever" }],
      output: null,
    },
    {
      name: "reports an undocumented empty default",
      code: `declare const kind: 'a' | 'b';
        switch (kind) {
          case 'a': break;
          case 'b': break;
          default:
        }
      `,
      errors: [{ messageId: "missingAssertNever" }],
      output: null,
    },
    {
      name: "reports an undocumented empty block",
      code: `type DomainEvent = { kind: 'created' } | { kind: 'deleted' };
        declare const domainEvent: DomainEvent;
        switch (domainEvent.kind) {
          case 'created': break;
          case 'deleted': break;
          default: {}
        }
      `,
      filename: "empty-block-discriminated-default.ts",
      errors: [{ messageId: "missingAssertNever" }],
      output: null,
    },
    {
      name: "reports a break-only discriminated default",
      code: `type DomainEvent = { kind: 'created' } | { kind: 'deleted' };
        declare const domainEvent: DomainEvent;
        switch (domainEvent.kind) {
          case 'created': break;
          case 'deleted': break;
          default: break;
        }
      `,
      filename: "break-only-discriminated-default.ts",
      errors: [{ messageId: "missingAssertNever" }],
      output: null,
    },
    {
      name: "reports an empty statement in a default",
      code: `declare const kind: 'a' | 'b';
        switch (kind) {
          case 'a': break;
          case 'b': break;
          default: ;
        }
      `,
      errors: [{ messageId: "missingAssertNever" }],
      output: null,
    },
    {
      name: "reports nested empty blocks in a default",
      code: `declare const kind: 'a' | 'b';
        switch (kind) {
          case 'a': break;
          case 'b': break;
          default: { { } }
        }
      `,
      errors: [{ messageId: "missingAssertNever" }],
      output: null,
    },
    {
      name: "reports a default containing only erased type declarations",
      code: `declare const kind: 'a' | 'b';
        switch (kind) {
          case 'a': break;
          case 'b': break;
          default: { type Remaining = typeof kind; interface Marker {} }
        }
      `,
      errors: [{ messageId: "missingAssertNever" }],
      output: null,
    },
  ],
}));
