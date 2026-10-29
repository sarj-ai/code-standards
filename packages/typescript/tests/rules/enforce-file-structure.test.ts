import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { ENFORCE_FILE_STRUCTURE_DOCUMENTATION } from "../../src/rules/enforce-file-structure.js";


RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester();

const NON_ACTION_FILENAME = "src/components/some-component.ts";
const ACTION_FILENAME = "src/actions/create-user.ts";

RULE_TESTER.run("enforce-file-structure", rule, {
  valid: [

    {
      filename: NON_ACTION_FILENAME,
      code: ENFORCE_FILE_STRUCTURE_DOCUMENTATION.examples[0].files[0].source,
    },

    {
      filename: NON_ACTION_FILENAME,
      code: `import { z } from 'zod';`,
    },

    {
      filename: NON_ACTION_FILENAME,
      code: `
        function add(a: number, b: number) { return a + b; }
        export { add };
      `,
    },

    {
      filename: ACTION_FILENAME,
      code: `
        'use server';
        import { z } from 'zod';
        export async function createUser() {}
      `,
    },




    {
      filename: "apps/web/components/booking/actions/BookingActionsDropdown.tsx",
      code: `
        import { useState } from 'react';
        export function BookingActionsDropdown() {
          const [open, setOpen] = useState(false);
          return open;
        }
      `,
    },


    {
      filename: "packages/features/booking-audit/lib/actions/CreatedAuditActionService.ts",
      code: `
        export class CreatedAuditActionService {
          run() { return true; }
        }
      `,
    },


    {
      filename: "app/dashboard/actions.ts",
      code: `
        import { z } from 'zod';
        export const schema = z.string();
      `,
    },

    {
      filename: NON_ACTION_FILENAME,
      code: `
        import { z } from 'zod';
        import { useState } from 'react';
        export const x = 1;
      `,
    },

    {
      filename: NON_ACTION_FILENAME,
      code: `
        const MAX = 5;
        const helper = () => 1;
      `,
    },


    {
      filename: NON_ACTION_FILENAME,
      code: `
        const x = 1;
        type T = { a: number };
      `,
    },




    {
      filename: NON_ACTION_FILENAME,
      code: `
        export function pauseCSSAnimationsWhenHidden() {
          return disposeVisibilityObserverIfEmpty();
        }
        function disposeVisibilityObserverIfEmpty() { return true; }
      `,
    },



    {
      filename: NON_ACTION_FILENAME,
      code: `
        export function render() { return TEMPLATE; }
        const TEMPLATE = '<div></div>';
      `,
    },


    {
      filename: NON_ACTION_FILENAME,
      code: `
        export interface VisibilityState { hidden: boolean }
        const DEFAULT_STATE = { hidden: false };
      `,
    },


    {
      filename: NON_ACTION_FILENAME,
      code: `
        export type Point = { x: number; y: number };
        export enum Axis { X, Y }
        function origin(): Point { return { x: 0, y: 0 }; }
      `,
    },


    {
      filename: "src/_namespaces/ts.ts",
      code: `
        import * as ts from '../ts';
        export { ts };
        import * as server from '../server';
        export { server };
      `,
    },

    {
      filename: "src/index.ts",
      code: `
        export * from './parser';
        export { scan } from './scanner';
        export { emit } from './emitter';
      `,
    },

    {
      filename: "src/lib/transaction.ts",
      code: `
        const TAX_RATE = 0.2;
        type Transaction = { amount: number };
        export function total(t: Transaction) { return t.amount * (1 + TAX_RATE); }
      `,
    },

    {
      filename: "src/lib/redaction.ts",
      code: `export function redact(s: string) { return s; }`,
    },


    {
      filename: "/repo/src/lib/integration/__tests__/token-validation.test.ts",
      code: `
        import { vi } from "vitest";
        const { forRequest } = vi.hoisted(() => ({ forRequest: vi.fn() }));
        vi.mock("@/services", () => ({ Services: { forRequest } }));
        import { checkTokenValidity } from "../token-validation";
      `,
    },
  ],
  invalid: [
    {
      name: "moves only erased imports while preserving the directive prologue",
      code: '"use client"; const value = 1; import type { Foo } from "foo"; type Bar = Foo; import type { Baz } from "baz";',
      output: '"use client"; import type { Foo } from "foo";\nimport type { Baz } from "baz";\nconst value = 1;  type Bar = Foo; ',
      errors: [{ messageId: "importsFirst" }, { messageId: "importsFirst" }],
    },
    {
      name: "does not move comments or line-sensitive directives",
      code: 'const value = 1;\n// @ts-ignore -- The type-only module belongs to the host.\nimport type { Foo } from "foo";',
      output: null,
      errors: [{ messageId: "importsFirst" }],
    },

    {
      filename: "/repo/src/workspace/types/GraphRoot.types.ts",
      code: `
        /** Internal type. DO NOT USE DIRECTLY. */
        type Exact<T> = T;
        // Generated GraphQL types, do not edit manually.
        import * as Types from "../../graphql/types";
      `,
      errors: [{ messageId: "importsFirst" }],
    },

    {
      filename: NON_ACTION_FILENAME,
      code: `
        import a from 'a';
        const nodeRequire = createRequire(import.meta.url);
        import b from 'b';
        import c from 'c';
        import d from 'd';
      `,
      errors: [{ messageId: "importsFirst" }],
    },

    {
      filename: NON_ACTION_FILENAME,
      code: `
        import a from 'a';
        const one = 1;
        import b from 'b';
        import c from 'c';
        const two = 2;
        import d from 'd';
      `,
      errors: [{ messageId: "importsFirst" }, { messageId: "importsFirst" }],
    },

    {
      filename: NON_ACTION_FILENAME,
      code: ENFORCE_FILE_STRUCTURE_DOCUMENTATION.examples[1].files[0].source,
      errors: [{ messageId: "importsFirst" }],
    },

    {
      filename: NON_ACTION_FILENAME,
      code: `
        type User = { name: string };
        import { z } from 'zod';
      `,
      errors: [{ messageId: "importsFirst" }],
    },

    {
      filename: NON_ACTION_FILENAME,
      code: `
        function foo() {}
        import { z } from 'zod';
      `,
      errors: [{ messageId: "importsFirst" }],
    },


    {
      filename: ACTION_FILENAME,
      code: `
        import { z } from 'zod';
        'use server';
        export async function createUser() { z.string(); }
      `,
      errors: [{ messageId: "useServerDirective" }],
    },


    {
      filename: NON_ACTION_FILENAME,
      code: `
        export const x = 1;
        'use server';
      `,
      errors: [{ messageId: "useServerDirective" }],
    },
  ],
});
