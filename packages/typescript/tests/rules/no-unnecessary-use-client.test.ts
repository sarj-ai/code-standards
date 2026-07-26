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
    // FP guard 3, bulbul PR #4111:
    // typescript/packages/app/src/app/dashboard/call-volume-chart-lazy.tsx:1 and
    // .../components/rich-text-editor/rich-text-editor-lazy.tsx:1 — `ssr: false`
    // is a BUILD ERROR in a Server Component, so this module has no legal form
    // without the directive. It is also maximally "unnecessary"-looking: one
    // `dynamic()` call, no JSX, no hooks, no handlers.
    {
      code: [
        '"use client";',
        'import dynamic from "next/dynamic";',
        'import { Skeleton } from "@/components/ui/skeleton";',
        "export const CallVolumeChart = dynamic(",
        '  async () => import("./call-volume-chart").then((mod) => mod.CallVolumeChart),',
        '  { loading: () => <Skeleton className="h-[430px] w-full" />, ssr: false },',
        ");",
      ].join("\n"),
      filename: "/repo/app/dashboard/call-volume-chart-lazy.tsx",
    },
    // Same, arranged so the `next/dynamic` import is the ONLY thing keeping it
    // valid: the lazy component is a local const (not an imported local, so the
    // third-party-JSX indicator is out) and the export's subtree references no
    // import (so the re-export indicator is out).
    {
      code: [
        '"use client";',
        'import dynamic from "next/dynamic";',
        'const Editor = dynamic(async () => import("./editor"), { ssr: false });',
        "export function Page() { return <Editor />; }",
      ].join("\n"),
      filename: "/repo/components/editor-lazy.tsx",
    },
    // bulbul PR #4111,
    // typescript/packages/app/src/app/scenarios/organization-selector-wrapper.tsx:1
    // (and the batch-calls twin). The hook is PASSED, not called, so
    // `markIfHookOrContext` never sees it — but indicator 2 already exempts the
    // file because the exported declaration reads imported bindings. Pinned so a
    // future narrowing of indicator 2 cannot silently reintroduce the report;
    // the disable comments in the repo are stale, not live false positives.
    {
      code: [
        '"use client";',
        'import { OrganizationSelector } from "@/components/organization-selector";',
        'import { useScenarioFilters } from "@/hooks/use-scenario-search-filters";',
        'import { createOrganizationFilterAdapter } from "@/utils/organization-filter-adapter";',
        "export function OrganizationSelectorWrapper({ organizations }) {",
        "  return <OrganizationSelector organizations={organizations}",
        "    useFilters={createOrganizationFilterAdapter(useScenarioFilters)} />;",
        "}",
      ].join("\n"),
      filename: "/repo/app/scenarios/organization-selector-wrapper.tsx",
    },
    // An imported hook handed straight to a child as a prop — same shape,
    // likewise already covered by indicator 2.
    {
      code: [
        '"use client";',
        'import { useFilters } from "./use-filters";',
        'import { Selector } from "./selector";',
        "export function Wrapper() { return <Selector useFilters={useFilters} />; }",
      ].join("\n"),
      filename: "/repo/components/wrapper.tsx",
    },
  ],
  invalid: [
    // The guard-3 narrowing is keyed on the EXACT module specifier: another
    // `next/*` import carries no such constraint and must still fire. Arranged
    // like the valid `next/dynamic` case above so the specifier is the only
    // difference between the two.
    {
      code: [
        '"use client";',
        'import { cookies } from "next/headers";',
        "const jar = cookies();",
        "export function Banner() { return <div>hello</div>; }",
      ].join("\n"),
      filename: "/repo/components/banner-3.tsx",
      errors: [{ messageId: "unnecessaryUseClient" }],
    },
    // A local `use*`-shaped variable is not a hook and must not excuse the
    // directive — the boundary of the hook heuristic, pinned.
    {
      code: [
        '"use client";',
        'const useCase = "reporting";',
        "export function Banner() { return <div>{useCase}</div>; }",
      ].join("\n"),
      filename: "/repo/components/banner.tsx",
      errors: [{ messageId: "unnecessaryUseClient" }],
    },
    // A `use*`-named import that is never referenced in an export's subtree does
    // not by itself excuse the directive.
    {
      code: [
        '"use client";',
        'import { useFilters } from "./use-filters";',
        "export function Banner() { return <div>hello</div>; }",
      ].join("\n"),
      filename: "/repo/components/banner-2.tsx",
      errors: [{ messageId: "unnecessaryUseClient" }],
    },
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
