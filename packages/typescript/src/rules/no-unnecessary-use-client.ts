/**
 * @fileoverview no-unnecessary-use-client — a `'use client'` file with no hooks, handlers or browser globals ships to the client for nothing.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-unnecessary-use-client.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
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

/** Modules whose import requires a client boundary. */
const CLIENT_REQUIRED_MODULES: ReadonlySet<string> = new Set(["next/dynamic"]);

const CLIENT_ONLY_PACKAGES_REGEX =
  /^(?:@radix-ui\/|framer-motion|react-dom|react-day-picker|@floating-ui\/|react-select|react-toastify|react-hook-form|recharts|react-dropzone|react-slick|react-swipeable|react-resizable|react-draggable|react-beautiful-dnd|@hello-pangea\/dnd|react-virtualized|react-window|@tanstack\/react-table|@tanstack\/react-query|react-redux|recoil|jotai|zustand|@tippyjs\/react|react-color|react-datepicker|next-themes|react-helmet|react-helmet-async|styled-components|@emotion\/)/;

type Ctx = Readonly<RuleContext<MessageIds, Options>>;

/** True for package specifiers whose implementation this rule cannot inspect. */
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

export default createRule<Options, MessageIds>({
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
    const importedLocals = new Set<string>();
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
