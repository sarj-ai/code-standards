import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/require-assert-never.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester();

ruleTester.run("require-assert-never", rule, {
  valid: [
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
      name: "allows a default that breaks",
      code: `
        switch (kind) {
          case 'a': break;
          default: break;
        }
      `,
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
      name: "reports an undocumented empty default",
      code: `
        switch (kind) {
          case 'a': break;
          default:
        }
      `,
      errors: [{ messageId: "missingAssertNever" }],
      output: null,
    },
    {
      name: "reports an undocumented empty block",
      code: `
        switch (kind) {
          case 'a': break;
          default: {}
        }
      `,
      errors: [{ messageId: "missingAssertNever" }],
      output: null,
    },
    {
      name: "reports an empty statement in a default",
      code: `
        switch (kind) {
          case 'a': break;
          default: ;
        }
      `,
      errors: [{ messageId: "missingAssertNever" }],
      output: null,
    },
    {
      name: "reports nested empty blocks in a default",
      code: `
        switch (kind) {
          case 'a': break;
          default: { { } }
        }
      `,
      errors: [{ messageId: "missingAssertNever" }],
      output: null,
    },
  ],
});
