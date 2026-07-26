import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/enforce-file-structure.js";

// Bind vitest to RuleTester for proper test reporting
RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester();

const NON_ACTION_FILENAME = "src/components/some-component.ts";
const ACTION_FILENAME = "src/actions/create-user.ts";

ruleTester.run("enforce-file-structure", rule, {
  valid: [
    // Canonical ordering: imports → types → constants → functions → exports
    {
      filename: NON_ACTION_FILENAME,
      code: `
        import { z } from 'zod';
        type User = { name: string };
        const MAX_USERS = 10;
        function makeUser(name: string) { return { name }; }
        export { makeUser };
      `,
    },
    // Only imports
    {
      filename: NON_ACTION_FILENAME,
      code: `import { z } from 'zod';`,
    },
    // Functions then exports — no earlier sections
    {
      filename: NON_ACTION_FILENAME,
      code: `
        function add(a: number, b: number) { return a + b; }
        export { add };
      `,
    },
    // Server action file with 'use server' at top
    {
      filename: ACTION_FILENAME,
      code: `
        'use server';
        import { z } from 'zod';
        export async function createUser() {}
      `,
    },
    // A component living under an `actions/` directory that is NOT a Next.js
    // server action (a UI dropdown, a Zustand store, a `*ActionService` class).
    // Without a `use server` directive present, the path must NOT force one.
    // Mirrors cal.com's `components/booking/actions/BookingActionsDropdown.tsx`.
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
    // A domain `*ActionService` under `lib/actions/` — a plain class, not an RSC
    // server action. No directive present → not flagged.
    {
      filename: "packages/features/booking-audit/lib/actions/CreatedAuditActionService.ts",
      code: `
        export class CreatedAuditActionService {
          run() { return true; }
        }
      `,
    },
    // A bare `actions.ts` file with no `use server` directive — the filename
    // alone must not force the directive.
    {
      filename: "app/dashboard/actions.ts",
      code: `
        import { z } from 'zod';
        export const schema = z.string();
      `,
    },
    // Multiple imports in a row
    {
      filename: NON_ACTION_FILENAME,
      code: `
        import { z } from 'zod';
        import { useState } from 'react';
        export const x = 1;
      `,
    },
    // Constants before functions
    {
      filename: NON_ACTION_FILENAME,
      code: `
        const MAX = 5;
        const helper = () => 1;
      `,
    },
    // A value const before a type — ordering among body statements is not
    // enforced (step-down: only imports-first is required).
    {
      filename: NON_ACTION_FILENAME,
      code: `
        const x = 1;
        type T = { a: number };
      `,
    },
    // Step-down: a public exported function followed by a private helper
    // function must NOT fire — this is the dominant TS layout. Mirrors the
    // VS Code false-positive site (13k hits): `pauseCSSAnimationsWhenHidden`
    // exported, `disposeVisibilityObserverIfEmpty` a private helper below it.
    {
      filename: NON_ACTION_FILENAME,
      code: `
        export function pauseCSSAnimationsWhenHidden() {
          return disposeVisibilityObserverIfEmpty();
        }
        function disposeVisibilityObserverIfEmpty() { return true; }
      `,
    },
    // Step-down with a private *value* helper below the public function — an
    // exported function is a function, the const below it is a declaration,
    // and both share the same body, so ordering between them is free.
    {
      filename: NON_ACTION_FILENAME,
      code: `
        export function render() { return TEMPLATE; }
        const TEMPLATE = '<div></div>';
      `,
    },
    // An exported interface among declarations must NOT fire: an exported
    // interface IS a declaration, so a private const below it is fine.
    {
      filename: NON_ACTION_FILENAME,
      code: `
        export interface VisibilityState { hidden: boolean }
        const DEFAULT_STATE = { hidden: false };
      `,
    },
    // Exported declaration followed by a private helper function — the
    // exported `type`/`enum`/`class` are declarations, not terminal exports.
    {
      filename: NON_ACTION_FILENAME,
      code: `
        export type Point = { x: number; y: number };
        export enum Axis { X, Y }
        function origin(): Point { return { x: 0, y: 0 }; }
      `,
    },
    // Generated `_namespaces` re-export barrel: interleaved `import * as X` /
    // `export { X }`. Re-exports are neutral, so this passes.
    {
      filename: "src/_namespaces/ts.ts",
      code: `
        import * as ts from '../ts';
        export { ts };
        import * as server from '../server';
        export { server };
      `,
    },
    // Pure re-export barrel with `export * from` / `export { … } from`.
    {
      filename: "src/index.ts",
      code: `
        export * from './parser';
        export { scan } from './scanner';
        export { emit } from './emitter';
      `,
    },
    // `transaction.ts` is NOT a server action (substring "action" must not match).
    {
      filename: "src/lib/transaction.ts",
      code: `
        const TAX_RATE = 0.2;
        type Transaction = { amount: number };
        export function total(t: Transaction) { return t.amount * (1 + TAX_RATE); }
      `,
    },
    // `redaction.ts` is NOT a server action either.
    {
      filename: "src/lib/redaction.ts",
      code: `export function redact(s: string) { return s; }`,
    },
    // Test files often register Vitest mocks before importing the subject under
    // test. That textual order is intentional setup, not module structure debt.
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
    // One misplacement is one message, however many imports trail it. Real
    // corpus: react-router/packages/react-router-dev/vite/plugin.ts:41, where a
    // single `const nodeRequire = createRequire(...)` between two import blocks
    // used to emit 18 diagnostics.
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
    // Two independent interleavings are two defects and stay two messages.
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
    // Import after a body statement (an exported const) — imports must be first.
    {
      filename: NON_ACTION_FILENAME,
      code: `
        export const x = 1;
        import { z } from 'zod';
      `,
      errors: [{ messageId: "importsFirst" }],
    },
    // Import after a type declaration — still imports-first.
    {
      filename: NON_ACTION_FILENAME,
      code: `
        type User = { name: string };
        import { z } from 'zod';
      `,
      errors: [{ messageId: "importsFirst" }],
    },
    // Import after a function — imports-first.
    {
      filename: NON_ACTION_FILENAME,
      code: `
        function foo() {}
        import { z } from 'zod';
      `,
      errors: [{ messageId: "importsFirst" }],
    },
    // Genuinely misplaced `use server`: the directive is present but sits after
    // an import instead of being the first statement, so it is inert at runtime.
    {
      filename: ACTION_FILENAME,
      code: `
        import { z } from 'zod';
        'use server';
        export async function createUser() { z.string(); }
      `,
      errors: [{ messageId: "useServerDirective" }],
    },
    // Misplaced `use server` below a body statement, in a non-action filename —
    // the trigger is the directive itself, not the path.
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
