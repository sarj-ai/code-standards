import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-unnecessary-use-client.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parserOptions: {
      ecmaFeatures: { jsx: true },
    },
  },
});

ruleTester.run("no-unnecessary-use-client", rule, {
  valid: [
    // FP guard 1, corpus: zod/packages/docs/components/tabs.tsx:1 and
    // swr/examples/suspense-global/global-swr-config.tsx:1 — wrapping a
    // third-party component is the documented reason for the directive.
    {
      code: [
        '"use client";',
        'import { Primitive } from "fumadocs-ui/components/tabs";',
        'export function Tabs({ items }) { return <Primitive.Tabs items={items} />; }',
      ].join("\n"),
      filename: "/repo/components/tabs.tsx",
    },
    {
      code: [
        '"use client";',
        'import { SWRConfig } from "swr";',
        'export function GlobalSWRConfig({ children }) { return <SWRConfig value={{}}>{children}</SWRConfig>; }',
      ].join("\n"),
      filename: "/repo/components/global-swr-config.tsx",
    },
    // FP guard 2, corpus: query/packages/react-query-devtools/src/index.ts:1 —
    // a re-export written the long way.
    {
      code: [
        '"use client";',
        'import * as Devtools from "./ReactQueryDevtools";',
        'export const ReactQueryDevtools = Devtools.ReactQueryDevtools;',
      ].join("\n"),
      filename: "/repo/src/index.ts",
    },
    // No directive.
    { code: "export default function X() { return <div />; }" },
    // Directive + hook.
    {
      code: "'use client'; import { useState } from 'react'; export default function X() { const [n] = useState(0); return <div>{n}</div>; }",
    },
    // Directive + event handler.
    {
      code: "'use client'; export default function X() { return <button onClick={() => {}}>x</button>; }",
    },
    // Directive + React.useState (namespaced hook).
    {
      code: "'use client'; export default function X() { const [n] = React.useState(0); return <div>{n}</div>; }",
    },
    // Directive + browser global.
    {
      code: "'use client'; export default function X() { return <div>{typeof window}</div>; }",
    },
    // Directive + client-only import.
    {
      code: "'use client'; import * as Dialog from '@radix-ui/react-dialog'; export default function X() { return <Dialog.Root />; }",
    },
    // Directive + class declaration (client-side only).
    {
      code: "'use client'; class Thing {} export default function X() { return <div />; }",
    },
  ],
  invalid: [
    // The guards must not over-fire: a locally-defined, server-safe component.
    {
      code: [
        '"use client";',
        'import { Row } from "./row";',
        'export function List() { return <ul><Row /></ul>; }',
      ].join("\n"),
      filename: "/repo/components/list.tsx",
      errors: [{ messageId: "unnecessaryUseClient" }],
    },
    {
      code: "'use client'; export default function X() { return <div>hello</div>; }",
      errors: [{ messageId: "unnecessaryUseClient" }],
    },
    {
      code: "'use client'; export default function X({ name }) { return <div>{name}</div>; }",
      errors: [{ messageId: "unnecessaryUseClient" }],
    },
  ],
});
