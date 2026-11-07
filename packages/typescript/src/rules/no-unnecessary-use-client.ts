/**
 * @fileoverview no-unnecessary-use-client — flag 'use client' files with no client-only features.
 *
 * Port of the 18.x `no-unnecessary-use-client` rule. The rule is
 * untyped, so the port covers all of it.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-unnecessary-use-client.test.ts
 */

import { defineRule, type ESTree, type Node, type Scope, type SourceCode } from "../types.js";
import { forEachOwnAstChild, parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";

const NAME = "no-unnecessary-use-client";

const HOOK_REGEX = /^use([A-Z]|$)/;
const EVENT_PROP_REGEX = /^on[A-Z]/;
const ERROR_FILE_REGEX = /(?:^|[\\/])(?:global-)?error\.[jt]sx?$/;

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
  "IntersectionObserver",
  "ResizeObserver",
  "WebSocket",
  "matchMedia",
  "alert",
  "confirm",
  "prompt",
  "addEventListener",
  "removeEventListener",
]);

/** Modules whose import requires a client boundary. */
const CLIENT_REQUIRED_MODULES: ReadonlySet<string> = new Set([
  "client-only",
  "next/dynamic",
]);

const CLIENT_ONLY_PACKAGES_REGEX =
  /^(?:@radix-ui\/|framer-motion|react-dom|react-day-picker|@floating-ui\/|react-select|react-toastify|react-hook-form|recharts|react-dropzone|react-slick|react-swipeable|react-resizable|react-draggable|react-beautiful-dnd|@hello-pangea\/dnd|react-virtualized|react-window|@tanstack\/react-table|@tanstack\/react-query|react-redux|recoil|jotai|zustand|@tippyjs\/react|react-color|react-datepicker|next-themes|react-helmet|react-helmet-async|styled-components|@emotion\/)/;

type Identifier = Extract<Node, { type: "Identifier" }>;

/** True for package specifiers whose implementation this rule cannot inspect. */
const isBareSpecifier = (source: string): boolean =>
  !source.startsWith(".") && !source.startsWith("/") && !source.startsWith("@/") && !source.startsWith("~");

/** The leftmost identifier of a JSX element name: `Primitive.Tabs` -> `Primitive`. */
const jsxRootName = (name: ESTree.JSXElementName | ESTree.JSXMemberExpressionObject): string => {
  let current: Node = name;
  while (current.type === "JSXMemberExpression") {
    current = current.object;
  }
  return current.type === "JSXIdentifier" ? current.name : "";
};

/** True when any identifier in `node`'s subtree names an imported binding. */
const subtreeReadsImportedBinding = (
  node: Node,
  imported: ReadonlySet<string>,
): boolean => {
  if (node.type === "Identifier") {
    return imported.has(node.name);
  }
  return forEachOwnAstChild(node, child => subtreeReadsImportedBinding(child, imported));
};

/** The `'use client'` statement in the file's directive prologue. */
const useClientDirective = (program: ESTree.Program): ESTree.ExpressionStatement | null => {
  for (const statement of program.body) {
    if (statement.type !== "ExpressionStatement" || statement.directive == null) return null;
    if (statement.directive === "use client") return statement;
  }
  return null;
};

/** `useX()`, `React.useX()` or `createContext()`. */
const isHookOrContextCall = (callee: Node): boolean => {
  const name = callee.type === "Identifier" ? callee.name
    : callee.type === "MemberExpression" && callee.property.type === "Identifier" ? callee.property.name
    : null;
  return name !== null && (HOOK_REGEX.test(name) || name === "createContext");
};

const isGlobalReference = (node: Identifier, sourceCode: SourceCode): boolean => {
  if (!BROWSER_GLOBALS.has(node.name)) return false;

  const parent = parentOf(node);
  if (parent !== null) {
    // `obj.window` — `window` is a property name, not a global reference.
    if (
      parent.type === "MemberExpression" &&
      parent.property === node &&
      !parent.computed
    ) {
      return false;
    }
    // `{ window: ... }` — property key, not a global reference.
    if (
      parent.type === "Property" &&
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
  let scope: Scope | null = sourceCode.getScope(node);
  while (scope !== null) {
    const variable = scope.set.get(node.name);
    if (variable !== undefined && variable.defs.length > 0) {
      return false;
    }
    scope = scope.upper;
  }

  return true;
};

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Flag `'use client'` files with no hooks or event handlers — they could be RSC.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      unnecessaryUseClient:
        "'use client' directive but no hooks (use*), JSX event handlers (on*), browser globals, or client-only imports found. Consider removing the directive and serving as a React Server Component.",
    },
  },
  createOnce(context) {
    let directiveNode: ESTree.ExpressionStatement | null = null;
    // Once any indicator is found the file needs its boundary, so every visitor stops early.
    let hasClientIndicator = false;
    let importedLocals = new Set<string>();
    let externalLocals = new Set<string>();

    return {
      before() {
        if (ERROR_FILE_REGEX.test(context.filename)) return false;
        directiveNode = useClientDirective(context.sourceCode.ast);
        if (directiveNode === null) return false;
        hasClientIndicator = false;
        importedLocals = new Set();
        externalLocals = new Set();
        return undefined;
      },
      CallExpression(node: ESTree.CallExpression): void {
        if (!hasClientIndicator && isHookOrContextCall(node.callee)) hasClientIndicator = true;
      },
      JSXAttribute(node: ESTree.JSXAttribute): void {
        if (hasClientIndicator) return;
        const owner = parentOf(node) as ESTree.JSXOpeningElement;
        if (
          node.name.type === "JSXIdentifier" &&
          (EVENT_PROP_REGEX.test(node.name.name) ||
            node.name.name === "ref" ||
            (node.name.name === "jsx" &&
              owner.name.type === "JSXIdentifier" &&
              owner.name.name === "style"))
        ) {
          hasClientIndicator = true;
        }
      },
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (hasClientIndicator) return;
        const source = node.source.value;
        if (
          (node.importKind !== "type" && node.specifiers.length === 0) ||
          CLIENT_ONLY_PACKAGES_REGEX.test(source) ||
          CLIENT_REQUIRED_MODULES.has(source)
        ) {
          hasClientIndicator = true;
          return;
        }
        const external = isBareSpecifier(source);
        for (const specifier of node.specifiers) {
          importedLocals.add(specifier.local.name);
          if (external) externalLocals.add(specifier.local.name);
        }
      },
      JSXOpeningElement(node: ESTree.JSXOpeningElement): void {
        if (hasClientIndicator) return;
        // Indicator 1: rendering a third-party component — this rule cannot see
        // whether the dependency itself needs a client boundary.
        if (externalLocals.has(jsxRootName(node.name))) {
          hasClientIndicator = true;
        }
        if (
          node.name.type === "JSXMemberExpression" &&
          importedLocals.has(jsxRootName(node.name)) &&
          node.name.property.type === "JSXIdentifier" &&
          (node.name.property.name === "Provider" ||
            node.name.property.name === "Consumer")
        ) {
          hasClientIndicator = true;
        }
      },
      ExportNamedDeclaration(node: ESTree.ExportNamedDeclaration): void {
        if (hasClientIndicator) return;
        // Indicator 2: `export const X = SomeImport.X` — a re-export written
        // the long way, so it must agree with the `export … from` branch.
        if (
          node.source !== null ||
          (node.declaration !== null && subtreeReadsImportedBinding(node.declaration, importedLocals))
        ) {
          hasClientIndicator = true;
        }
      },
      ExportAllDeclaration(): void {
        hasClientIndicator = true;
      },
      ExportDefaultDeclaration(node: ESTree.ExportDefaultDeclaration): void {
        if (!hasClientIndicator && subtreeReadsImportedBinding(node.declaration, importedLocals)) {
          hasClientIndicator = true;
        }
      },
      ClassDeclaration(): void {
        hasClientIndicator = true;
      },
      ClassExpression(): void {
        hasClientIndicator = true;
      },
      Identifier(node: Identifier): void {
        if (!hasClientIndicator && isGlobalReference(node, context.sourceCode)) {
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
