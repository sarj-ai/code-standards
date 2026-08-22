import { join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { REQUIRE_ASSERT_NEVER_DOCUMENTATION } from "../../src/rules/require-assert-never.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
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

RULE_TESTER.run("require-assert-never", rule, {
  valid: [
    { name: "accepts the documented exhaustive default", code: REQUIRE_ASSERT_NEVER_DOCUMENTATION.examples[0].files[0].source },
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
    { name: "reports the documented empty default", code: REQUIRE_ASSERT_NEVER_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "missingAssertNever" }], output: null },
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
});
