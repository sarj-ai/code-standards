/**
 * @fileoverview prefer-node-fs-promises — synchronous filesystem calls block the Node.js event loop.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-node-fs-promises.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, Variable } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "preferAsyncFs";
type Options = [];

export const PREFER_NODE_FS_PROMISES_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Prefer promise-based Node.js filesystem APIs over synchronous calls in production modules.",
  rationale: "Synchronous filesystem work blocks the event loop and can stall unrelated daemon, server, and worker tasks.",
  remediation: "Import the promise API from node:fs/promises and await it; use FileHandle.sync only where a documented durability boundary requires it.",
  category: "performance",
  limitations: [
    "Tests and generated files are excluded.",
    "This recommendation applies to Node-compatible runtimes. Changing a synchronous API to a promise changes its caller contract; review startup-only work and APIs that require synchronous execution rather than mechanically adding await.",
    "ESLint rule implementations under src/rules are excluded because visitor creation and execution are synchronous by contract.",
    "Only statically identifiable node:fs loads are inspected; filesystem objects passed through arbitrary functions or assignments require type-aware analysis.",
  ],
  examples: [
    { id: "async-read", title: "Use the promise API", outcome: "no-match", files: [{ path: "src/store.ts", source: "import { readFile } from 'node:fs/promises'; export async function load(path: string) { return readFile(path, 'utf8'); }" }], focusPath: "src/store.ts", expectedCount: 0, public: true },
    { id: "sync-read", title: "Do not block on a synchronous read", outcome: "match", files: [{ path: "src/store.ts", source: "import { readFileSync } from 'node:fs'; export function load(path: string) { return readFileSync(path, 'utf8'); }" }], focusPath: "src/store.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

function memberName(node: ESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === "Identifier") return node.property.name;
  if (node.computed && node.property.type === "Literal" && typeof node.property.value === "string") {
    return node.property.value;
  }
  return null;
}

function unwrapAwait(node: ESTree.Expression): ESTree.Expression {
  return node.type === "AwaitExpression" ? node.argument : node;
}

function isFsLoader(node: ESTree.Expression, isGlobal: (node: ESTree.BindingIdentifier) => boolean): boolean {
  const expression = unwrapAwait(node);
  if (expression.type === "ImportExpression") return isFsSpecifier(expression.source);
  if (expression.type !== "CallExpression" || expression.arguments.length !== 1) return false;
  const [argument] = expression.arguments;
  if (argument === undefined || argument.type === "SpreadElement" || !isFsSpecifier(argument)) return false;
  if (expression.callee.type === "Identifier") return expression.callee.name === "require" && isGlobal(expression.callee);
  return (
    expression.callee.type === "MemberExpression" &&
    expression.callee.object.type === "Identifier" &&
    expression.callee.object.name === "process" &&
    isGlobal(expression.callee.object) &&
    memberName(expression.callee) === "getBuiltinModule"
  );
}

function isFsSpecifier(node: ESTree.Expression): boolean {
  return node.type === "Literal" && (node.value === "node:fs" || node.value === "fs");
}

function propertyName(node: ESTree.ObjectProperty | ESTree.BindingProperty): string | null {
  if (!node.computed && node.key.type === "Identifier") return node.key.name;
  if (node.key.type === "Literal" && typeof node.key.value === "string") return node.key.value;
  return null;
}

export default createRule<Options, MessageIds>({
  name: "prefer-node-fs-promises",
  documentation: PREFER_NODE_FS_PROMISES_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: "Prefer promise-based Node.js filesystem APIs over synchronous calls in production modules." },
    schema: [],
    messages: {
      preferAsyncFs: "Node filesystem API `{{name}}` is synchronous; use the promise API and await it.",
    },
  },
  defaultOptions: [],
  create(context) {
    const normalizedFilename = sourceOrigin(context).filename.replaceAll("\\", "/");
    if (
      isTestFile(sourceOrigin(context).filename) ||
      isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text) ||
      normalizedFilename.includes("src/rules/")
    )
      return {};
    const namespaces = new Set<Variable>();
    const bindingOf = (node: ESTree.BindingIdentifier): Variable | null =>
      findVariable(context.sourceCode.getScope(node), node.name);
    const isGlobal = (node: ESTree.BindingIdentifier): boolean => {
      const binding = bindingOf(node);
      return binding === null || binding.defs.length === 0;
    };
    const isNamespace = (node: ESTree.BindingIdentifier): boolean => {
      const binding = bindingOf(node);
      return binding !== null && namespaces.has(binding) && !binding.references.some((reference) => reference.isWrite() && reference.init !== true);
    };
    const recordNamespace = (node: ESTree.BindingIdentifier): void => {
      const binding = bindingOf(node);
      if (binding !== null) namespaces.add(binding);
    };
    return {
      ImportDeclaration(node): void {
        if (node.source.value !== "node:fs" && node.source.value !== "fs") return;
        const synchronousImports: string[] = [];
        for (const specifier of node.specifiers) {
          if (specifier.type === "ImportNamespaceSpecifier" || specifier.type === "ImportDefaultSpecifier") {
            recordNamespace(specifier.local);
            continue;
          }
          if (
            specifier.type === "ImportSpecifier" &&
            specifier.imported.type === "Identifier" &&
            specifier.imported.name.endsWith("Sync")
          ) synchronousImports.push(specifier.imported.name);
        }
        if (synchronousImports.length > 0) {
          context.report({
            node,
            messageId: "preferAsyncFs",
            data: { name: synchronousImports.join(", ") },
          });
        }
      },
      VariableDeclarator(node): void {
        if (
          node.init === null ||
          (!isFsLoader(node.init, isGlobal) &&
            (node.init.type !== "Identifier" || !isNamespace(node.init)))
        )
          return;
        if (node.id.type === "Identifier") {
          recordNamespace(node.id);
          return;
        }
        if (node.id.type !== "ObjectPattern") return;
        const synchronousImports = node.id.properties.flatMap((property) => {
          if (property.type !== "Property") return [];
          const name = propertyName(property);
          return name?.endsWith("Sync") === true ? [name] : [];
        });
        if (synchronousImports.length > 0) {
          context.report({
            node,
            messageId: "preferAsyncFs",
            data: { name: synchronousImports.join(", ") },
          });
        }
      },
      MemberExpression(node): void {
        const name = memberName(node);
        if (name?.endsWith("Sync") !== true) return;
        const object = unwrapAwait(node.object);
        if (
          (object.type === "Identifier" && isNamespace(object)) ||
          isFsLoader(object, isGlobal)
        ) {
          context.report({ node, messageId: "preferAsyncFs", data: { name } });
        }
      },
    };
  },
});
