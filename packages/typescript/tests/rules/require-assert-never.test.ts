import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/require-assert-never.js";

// Bind vitest to RuleTester for proper test reporting
RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester();

ruleTester.run("require-assert-never", rule, {
  valid: [
    // Switch with no default — rule only flags a present, no-op default
    {
      code: `
        switch (kind) {
          case 'a': break;
          case 'b': break;
        }
      `,
    },
    // Default case calls assertNever() as an expression statement
    {
      code: `
        switch (kind) {
          case 'a': break;
          default: assertNever(kind);
        }
      `,
    },
    // Default case throws assertNever()
    {
      code: `
        switch (kind) {
          case 'a': break;
          default: throw assertNever(kind);
        }
      `,
    },
    // Namespaced assertNever — utils.assertNever(x)
    {
      code: `
        switch (kind) {
          case 'a': break;
          default: utils.assertNever(kind);
        }
      `,
    },
    // Namespaced assertNever via return
    {
      code: `
        switch (kind) {
          case 'a': return 1;
          default: return utils.assertNever(kind);
        }
      `,
    },
    // Default with multiple statements but at least one assertNever()
    {
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
    // Reducer-style: default returns the existing state (legitimate runtime default)
    {
      code: `
        switch (action.type) {
          case 'inc': return state + 1;
          case 'dec': return state - 1;
          default: return state;
        }
      `,
    },
    // HTTP-status style: default returns a fallback (legitimate runtime default)
    {
      code: `
        switch (httpStatus) {
          case 200: return ok();
          case 404: return notFound();
          default: return fallback();
        }
      `,
    },
    // Default that throws a regular Error — runtime handling, not flagged.
    {
      code: `
        switch (kind) {
          case 'a': break;
          default: throw new Error('unreachable');
        }
      `,
    },
    // Default that calls a non-assertNever function — runtime handling.
    {
      code: `
        switch (kind) {
          case 'a': break;
          default: logUnknown(kind);
        }
      `,
    },
    // Default that just breaks — explicit runtime no-op handling.
    {
      code: `
        switch (kind) {
          case 'a': break;
          default: break;
        }
      `,
    },
    // Fallthrough default — an empty default that hands control to a following
    // case which does the work. (VS Code CursorPlurality)
    {
      code: `
        switch (plurality) {
          default:
          case CursorPlurality.Single:
            handleSingle();
            break;
        }
      `,
    },
    // Fallthrough default sitting between two cases.
    {
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
    // Deliberate, comment-documented no-op default on a config-string switch —
    // assertNever would throw at runtime here. (Next.js)
    {
      code: `
        switch (setting) {
          case 'on': enable(); break;
          default: // Do nothing, defaults should be used
        }
      `,
    },
    // Comment-documented empty block default.
    {
      code: `
        switch (setting) {
          case 'on': enable(); break;
          default: { /* intentionally left blank */ }
        }
      `,
    },
  ],
  invalid: [
    // Default with no body — an empty, do-nothing default that should either
    // handle the case or assert exhaustiveness.
    {
      code: `
        switch (kind) {
          case 'a': break;
          default:
        }
      `,
      errors: [{ messageId: "missingAssertNever" }],
    },
    // Default block that does nothing.
    {
      code: `
        switch (kind) {
          case 'a': break;
          default: {}
        }
      `,
      errors: [{ messageId: "missingAssertNever" }],
    },
  ],
});
