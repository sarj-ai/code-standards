/**
 * @fileoverview Flag `'use client'` files with no hooks or event handlers.
 *
 * If a file is marked `'use client'` but contains no hook calls
 * (`useState`/`useEffect`/etc.), no JSX event handlers (`onClick`,
 * `onChange`, etc.), no browser globals, no client-only imports, and no
 * other client-side indicators (classes, re-exports), the directive is
 * likely unnecessary and the file could be a React Server Component —
 * improving cold-start, bundle size, and SEO.
 *
 * False-positive watch: components that only use client-side context
 * (e.g. theme providers) without hooks or events still need `'use client'`.
 *
 * TWO MORE CLIENT INDICATORS, ADDED AFTER A CORPUS SWEEP (2220 files across
 * zod / TanStack Query / react-router / swr / zustand, 2026-07 — 12 hits, all
 * false positives):
 *
 *   1. **Rendering a component imported from a THIRD-PARTY package.** React
 *      documents `'use client'` at the top of a wrapper as the way to mark a
 *      dependency's components as client components, and this rule cannot see
 *      into `node_modules` to know whether the dependency needs it.
 *      `CLIENT_ONLY_PACKAGES_REGEX` was a hand-maintained approximation of the
 *      same idea and is necessarily incomplete — it did not know about
 *      `fumadocs-ui` (`zod/packages/docs/components/tabs.tsx:1`, which renders
 *      `<Primitive.Tabs>`), about `swr` itself
 *      (`swr/examples/suspense-global/global-swr-config.tsx:1`, a `<SWRConfig>`
 *      provider), or about `next/image` and `lucide-react`
 *      (`zod/packages/docs/components/themed-image.tsx:1`,
 *      `.../heading.tsx:1`). A component imported by a RELATIVE path lives in
 *      the same repo, is linted by this same rule, and still fires — so the
 *      narrowing costs nothing where the rule can actually see the answer.
 *   2. **Aliasing an import into a public export** —
 *      `import * as Devtools from './ReactQueryDevtools';
 *      export const ReactQueryDevtools = … Devtools.ReactQueryDevtools`
 *      (`query/packages/react-query-devtools/src/index.ts:1`, and `production.ts`).
 *      That is a re-export written the long way, and `export … from` was already
 *      treated as an indicator; the two spellings now agree.
 *
 * ONE MORE INDICATOR FROM A FIRST-PARTY REVIEW REGRESSION:
 *
 *   3. **Importing `next/dynamic`.** In the App Router, `dynamic(…, { ssr: false })`
 *      is a hard BUILD ERROR inside a Server Component — Next.js rejects it with
 *      "`ssr: false` is not allowed with `next/dynamic` in Server Components".
 *      A lazy-wrapper module therefore has NO legal form without the directive,
 *      so the rule was demanding something the framework forbids and the only
 *      available response was a disable comment. These wrappers also look
 *      maximally "unnecessary" to the old predicate: one `dynamic()` call, no
 *      hooks, no handlers, no browser globals.
 *      Two first-party lazy-wrapper modules are the shape: one defers the
 *      recharts bundle off a server-rendered dashboard page, the other defers
 *      the Lexical bundle off two server-rendered admin routes.
 *
 *      HONEST SCOPE: both of those files also happen to be covered by indicator
 *      2, since each EXPORTS a const whose initializer reads the imported
 *      `dynamic`. Indicator 3 is therefore defense-in-depth, not the thing that
 *      currently silences them: it is what covers the same wrapper when the lazy
 *      component is module-internal (`const Editor = dynamic(…); export function
 *      Page() { return <Editor />; }`), where indicator 2 does not reach and the
 *      framework constraint is identical. The test suite pins exactly that shape.
 *
 * All FOUR of that repo's `no-unnecessary-use-client` disables are consequently
 * stale rather than live false positives — including a selector-wrapper module
 * and its twin, which pass a hook adapter as a function prop and are already
 * exempt via indicator 2. The valid-case suite pins all of them so a future narrowing of
 * indicator 2 cannot silently reintroduce the reports.
 *
 * References:
 *   - https://nextjs.org/docs/app/building-your-application/rendering/client-components
 *   - https://react.dev/reference/rsc/use-client (wrapping third-party components)
 *   - https://nextjs.org/docs/app/api-reference/functions/dynamic (`ssr: false`)
 */

import {
  AST_NODE_TYPES,
  ESLintUtils,
  type TSESTree,
} from "@typescript-eslint/utils";
import type { RuleContext, Scope } from "@typescript-eslint/utils/ts-eslint";

type MessageIds = "unnecessaryUseClient";
type Options = readonly [];

const HOOK_REGEX = /^use([A-Z]|$)/;
const EVENT_PROP_REGEX = /^on[A-Z]/;
const ERROR_FILE_REGEX = /\b(?:global-)?error\.[jt]sx?$/;

const BROWSER_GLOBALS: ReadonlySet<string> = new Set([
  "window",
  "document",
  "navigator",
  "localStorage",
  "sessionStorage",
  "location",
  "history",
  "screen",
  "requestAnimationFrame",
  "cancelAnimationFrame",
  "CustomEvent",
  "Event",
  "MouseEvent",
  "KeyboardEvent",
  "TouchEvent",
]);

/**
 * Modules whose very import forces a client boundary, independent of what the
 * file then does with them. `next/dynamic` is the case that matters: in the App
 * Router, `dynamic(..., { ssr: false })` is a BUILD ERROR in a Server Component
 * ("`ssr: false` is not allowed with `next/dynamic` in Server Components"), so a
 * lazy-wrapper module has no legal form without `'use client'`. See @fileoverview.
 */
const CLIENT_REQUIRED_MODULES: ReadonlySet<string> = new Set(["next/dynamic"]);

const CLIENT_ONLY_PACKAGES_REGEX =
  /^(?:@radix-ui\/|framer-motion|react-dom|react-day-picker|@floating-ui\/|react-select|react-toastify|react-hook-form|recharts|react-dropzone|react-slick|react-swipeable|react-resizable|react-draggable|react-beautiful-dnd|@hello-pangea\/dnd|react-virtualized|react-window|@tanstack\/react-table|@tanstack\/react-query|react-redux|recoil|jotai|zustand|@tippyjs\/react|react-color|react-datepicker|next-themes|react-helmet|react-helmet-async|styled-components|@emotion\/)/;

type Ctx = Readonly<RuleContext<MessageIds, Options>>;

/**
 * True for a package specifier — anything that is not a relative path or one of
 * the usual in-repo alias prefixes. A relative/aliased import points at code in
 * this repo, which this same rule already lints, so the "cannot see into the
 * dependency" argument does not apply to it.
 */
const isBareSpecifier = (source: string): boolean =>
  !source.startsWith(".") && !source.startsWith("/") && !source.startsWith("@/") && !source.startsWith("~");

/** The leftmost identifier of a JSX element name: `Primitive.Tabs` -> `Primitive`. */
const jsxRootName = (name: TSESTree.JSXTagNameExpression): string => {
  let current: TSESTree.JSXTagNameExpression = name;
  while (current.type === AST_NODE_TYPES.JSXMemberExpression) {
    current = current.object;
  }
  return current.type === AST_NODE_TYPES.JSXIdentifier ? current.name : "";
};

/** True when any identifier in `node`'s subtree names an imported binding. */
const subtreeReadsImportedBinding = (
  node: TSESTree.Node,
  imported: ReadonlySet<string>,
): boolean => {
  if (node.type === AST_NODE_TYPES.Identifier) {
    return imported.has(node.name);
  }
  for (const key of Object.keys(node) as (keyof TSESTree.Node)[]) {
    if (key === "parent") continue;
    const value = node[key];
    for (const child of (Array.isArray(value) ? value : [value]) as unknown[]) {
      if (
        child !== null &&
        typeof child === "object" &&
        typeof (child as { type?: unknown }).type === "string" &&
        subtreeReadsImportedBinding(child as TSESTree.Node, imported)
      ) {
        return true;
      }
    }
  }
  return false;
};

const isUseClientDirective = (
  node: TSESTree.Statement,
): node is TSESTree.ExpressionStatement => {
  return (
    node.type === AST_NODE_TYPES.ExpressionStatement &&
    node.expression.type === AST_NODE_TYPES.Literal &&
    node.expression.value === "use client"
  );
};

const isGlobalReference = (
  node: TSESTree.Identifier,
  context: Ctx,
): boolean => {
  if (!BROWSER_GLOBALS.has(node.name)) return false;

  const parent = node.parent;
  if (parent !== undefined) {
    // `obj.window` — `window` is a property name, not a global reference.
    if (
      parent.type === AST_NODE_TYPES.MemberExpression &&
      parent.property === node &&
      !parent.computed
    ) {
      return false;
    }
    // `{ window: ... }` — property key, not a global reference.
    if (
      parent.type === AST_NODE_TYPES.Property &&
      parent.key === node &&
      !parent.computed
    ) {
      return false;
    }
    // Type annotations / type-only positions are not runtime references.
    if (parent.type.startsWith("TS")) {
      return false;
    }
  }

  // If there's a local binding for this name anywhere up the chain, it's not
  // a reference to the browser global.
  let scope: Scope.Scope | null = context.sourceCode.getScope(node);
  while (scope !== null) {
    const variable = scope.set.get(node.name);
    if (variable !== undefined && variable.defs.length > 0) {
      return false;
    }
    scope = scope.upper;
  }

  return true;
};

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-unnecessary-use-client",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Flag `'use client'` files with no hooks or event handlers — they could be RSC.",
    },
    schema: [],
    messages: {
      unnecessaryUseClient:
        "'use client' directive but no hooks (use*), JSX event handlers (on*), browser globals, or client-only imports found. Consider removing the directive and serving as a React Server Component.",
    },
  },
  defaultOptions: [],
  create(context) {
    const filename = context.filename;
    if (ERROR_FILE_REGEX.test(filename)) {
      return {};
    }

    let directiveNode: TSESTree.ExpressionStatement | null = null;
    let hasClientIndicator = false;
    /** Every local name bound by an import, whatever the module. */
    const importedLocals = new Set<string>();
    /** Locals bound from a BARE (third-party) specifier — see @fileoverview. */
    const externalLocals = new Set<string>();

    const markIfHookOrContext = (
      callee: TSESTree.CallExpression["callee"],
    ): void => {
      if (callee.type === AST_NODE_TYPES.Identifier) {
        if (HOOK_REGEX.test(callee.name) || callee.name === "createContext") {
          hasClientIndicator = true;
        }
        return;
      }
      if (
        callee.type === AST_NODE_TYPES.MemberExpression &&
        callee.property.type === AST_NODE_TYPES.Identifier
      ) {
        const name = callee.property.name;
        if (HOOK_REGEX.test(name) || name === "createContext") {
          hasClientIndicator = true;
        }
      }
    };

    return {
      Program(node): void {
        for (const stmt of node.body) {
          // Directives must be the first statements; once we see a non-
          // ExpressionStatement, stop scanning.
          if (stmt.type !== AST_NODE_TYPES.ExpressionStatement) break;
          if (isUseClientDirective(stmt)) {
            directiveNode = stmt;
            break;
          }
        }
      },
      CallExpression(node): void {
        // The `Program` visitor (entered first) has already determined whether
        // this file has a `'use client'` directive. If it doesn't, the result
        // can't change — skip all of the per-node indicator work, including the
        // hot scope-resolution in the `Identifier` visitor below.
        if (directiveNode === null) return;
        markIfHookOrContext(node.callee);
      },
      JSXAttribute(node): void {
        if (directiveNode === null) return;
        if (
          node.name.type === AST_NODE_TYPES.JSXIdentifier &&
          EVENT_PROP_REGEX.test(node.name.name)
        ) {
          hasClientIndicator = true;
        }
      },
      ImportDeclaration(node): void {
        if (directiveNode === null) return;
        if (typeof node.source.value !== "string") return;
        const source = node.source.value;
        if (
          CLIENT_ONLY_PACKAGES_REGEX.test(source) ||
          CLIENT_REQUIRED_MODULES.has(source)
        ) {
          hasClientIndicator = true;
        }
        for (const specifier of node.specifiers) {
          importedLocals.add(specifier.local.name);
          if (isBareSpecifier(source)) {
            externalLocals.add(specifier.local.name);
          }
        }
      },
      JSXOpeningElement(node): void {
        if (directiveNode === null) return;
        // Indicator 1: rendering a third-party component — this rule cannot see
        // whether the dependency itself needs a client boundary.
        if (externalLocals.has(jsxRootName(node.name))) {
          hasClientIndicator = true;
        }
      },
      ExportNamedDeclaration(node): void {
        if (directiveNode === null) return;
        if (node.source !== null) {
          hasClientIndicator = true;
          return;
        }
        // Indicator 2: `export const X = SomeImport.X` — a re-export written
        // the long way, so it must agree with the `export … from` branch above.
        if (
          node.declaration !== null &&
          subtreeReadsImportedBinding(node.declaration, importedLocals)
        ) {
          hasClientIndicator = true;
        }
      },
      ExportAllDeclaration(node): void {
        if (directiveNode === null) return;
        if (node.source !== null) {
          hasClientIndicator = true;
        }
      },
      ClassDeclaration(): void {
        if (directiveNode === null) return;
        hasClientIndicator = true;
      },
      ClassExpression(): void {
        if (directiveNode === null) return;
        hasClientIndicator = true;
      },
      Identifier(node): void {
        if (directiveNode === null) return;
        if (isGlobalReference(node, context)) {
          hasClientIndicator = true;
        }
      },
      "Program:exit"(): void {
        if (directiveNode !== null && !hasClientIndicator) {
          context.report({
            node: directiveNode,
            messageId: "unnecessaryUseClient",
          });
        }
      },
    };
  },
});
