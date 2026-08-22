import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  NO_UNNECESSARY_USE_CLIENT_DOCUMENTATION,
} from "../../src/rules/no-unnecessary-use-client.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parserOptions: {
      ecmaFeatures: { jsx: true },
    },
  },
});

RULE_TESTER.run("no-unnecessary-use-client", rule, {
  valid: [
    {
      name: "allows wrappers that render named third-party components",
      code: [
        '"use client";',
        'import { Primitive } from "fumadocs-ui/components/tabs";',
        'export function Tabs({ items }) { return <Primitive.Tabs items={items} />; }',
      ].join("\n"),
      filename: "/repo/components/tabs.tsx",
    },
    {
      name: "allows wrappers that render third-party context providers",
      code: [
        '"use client";',
        'import { SWRConfig } from "swr";',
        'export function GlobalSWRConfig({ children }) { return <SWRConfig value={{}}>{children}</SWRConfig>; }',
      ].join("\n"),
      filename: "/repo/components/global-swr-config.tsx",
    },
    {
      name: "allows exported aliases that read imported bindings",
      code: [
        '"use client";',
        'import * as Devtools from "./ReactQueryDevtools";',
        'export const ReactQueryDevtools = Devtools.ReactQueryDevtools;',
      ].join("\n"),
      filename: "/repo/src/index.ts",
    },
    {
      name: "ignores files without the directive",
      code: "export default function X() { return <div />; }",
    },
    {
      name: "allows hook calls",
      code: NO_UNNECESSARY_USE_CLIENT_DOCUMENTATION.examples[0].files[0].source,
    },
    {
      name: "allows JSX event handlers",
      code: "'use client'; export default function X() { return <button onClick={() => {}}>x</button>; }",
    },
    {
      name: "allows namespaced hook calls",
      code: "'use client'; export default function X() { const [n] = React.useState(0); return <div>{n}</div>; }",
    },
    {
      name: "allows browser global references",
      code: "'use client'; export default function X() { return <div>{typeof window}</div>; }",
    },
    {
      name: "allows known client-only imports",
      code: "'use client'; import * as Dialog from '@radix-ui/react-dialog'; export default function X() { return <Dialog.Root />; }",
    },
    {
      name: "allows class declarations",
      code: "'use client'; class Thing {} export default function X() { return <div />; }",
    },
    {
      name: "allows createContext without hooks or handlers",
      code: [
        '"use client";',
        'import { createContext } from "react";',
        "export const ThemeContext = createContext(null);",
      ].join("\n"),
    },
    {
      name: "allows direct named re-exports",
      code: ['"use client";', 'export { Provider } from "./provider";'].join("\n"),
    },
    {
      name: "allows export-all declarations",
      code: ['"use client";', 'export * from "./provider";'].join("\n"),
    },
    {
      name: "allows exported next/dynamic wrappers",
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
    {
      name: "allows internal next/dynamic wrappers",
      code: [
        '"use client";',
        'import dynamic from "next/dynamic";',
        'const Editor = dynamic(async () => import("./editor"), { ssr: false });',
        "export function Page() { return <Editor />; }",
      ].join("\n"),
      filename: "/repo/components/editor-lazy.tsx",
    },
    {
      name: "allows exported wrappers that pass imported hook adapters",
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
    {
      name: "allows exported wrappers that pass imported hooks",
      code: [
        '"use client";',
        'import { useFilters } from "./use-filters";',
        'import { Selector } from "./selector";',
        "export function Wrapper() { return <Selector useFilters={useFilters} />; }",
      ].join("\n"),
      filename: "/repo/components/wrapper.tsx",
    },
    {
      name: "keeps styled-jsx client boundaries",
      code: `'use client'; export function X() { return <style jsx>{\`div { color: red; }\`}</style>; }`,
    },
    {
      name: "keeps ref-bearing components",
      code: `'use client'; export function X({ inputRef }) { return <input ref={inputRef} />; }`,
    },
    {
      name: "keeps explicit client-only modules",
      code: `'use client'; import 'client-only'; export const value = 1;`,
    },
    {
      name: "keeps default exports of imported client boundaries",
      code: `'use client'; import Provider from './provider'; export default Provider;`,
    },
    {
      name: "keeps imported context consumers",
      code: `'use client'; import { ThemeContext } from './theme'; export const X = () => <ThemeContext.Consumer>{x => x}</ThemeContext.Consumer>;`,
    },
  ],
  invalid: [
    {
      name: "reports unrelated next imports",
      code: [
        '"use client";',
        'import { cookies } from "next/headers";',
        "const jar = cookies();",
        "export function Banner() { return <div>hello</div>; }",
      ].join("\n"),
      filename: "/repo/components/banner-3.tsx",
      errors: [{ messageId: "unnecessaryUseClient" }],
    },
    {
      name: "reports use-prefixed variables that are not called",
      code: [
        '"use client";',
        'const useCase = "reporting";',
        "export function Banner() { return <div>{useCase}</div>; }",
      ].join("\n"),
      filename: "/repo/components/banner.tsx",
      errors: [{ messageId: "unnecessaryUseClient" }],
    },
    {
      name: "reports unused use-prefixed imports",
      code: [
        '"use client";',
        'import { useFilters } from "./use-filters";',
        "export function Banner() { return <div>hello</div>; }",
      ].join("\n"),
      filename: "/repo/components/banner-2.tsx",
      errors: [{ messageId: "unnecessaryUseClient" }],
    },
    {
      name: "reports wrappers that only render relative imports",
      code: [
        '"use client";',
        'import { Row } from "./row";',
        'export function List() { return <ul><Row /></ul>; }',
      ].join("\n"),
      filename: "/repo/components/list.tsx",
      errors: [{ messageId: "unnecessaryUseClient" }],
    },
    {
      name: "reports static components",
      code: NO_UNNECESSARY_USE_CLIENT_DOCUMENTATION.examples[1].files[0].source,
      errors: [{ messageId: "unnecessaryUseClient" }],
    },
    {
      name: "reports components that only render props",
      code: "'use client'; export default function X({ name }) { return <div>{name}</div>; }",
      errors: [{ messageId: "unnecessaryUseClient" }],
    },
  ],
});
