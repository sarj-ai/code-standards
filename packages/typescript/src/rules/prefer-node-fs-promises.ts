/**
 * @fileoverview prefer-node-fs-promises — prefer promise-based Node.js filesystem APIs over synchronous calls in production modules.
 *
 * Port of the 18.x `prefer-node-fs-promises` rule. Same algorithm;
 * excluded files are skipped and recorded namespaces are reset in `before()`.
 */

import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { stableValueBinding } from "../utils/stable-value-binding.js";
import { findVariable } from "../utils/static-string.js";

const NAME = "prefer-node-fs-promises";

type Identifier = Extract<Node, { type: "Identifier" }>;

function memberName(node: ESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === "Identifier") return node.property.name;
  if (node.computed && node.property.type === "Literal" && typeof node.property.value === "string") {
    return node.property.value;
  }
  return null;
}

function unwrapAwait(node: Node): Node {
  return node.type === "AwaitExpression" ? node.argument : node;
}

function isFsLoader(node: Node, isGlobal: (node: Identifier) => boolean): boolean {
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

function isFsSpecifier(node: Node): boolean {
  return node.type === "Literal" && (node.value === "node:fs" || node.value === "fs");
}

function propertyName(node: ESTree.ObjectProperty | ESTree.BindingProperty): string | null {
  if (!node.computed && node.key.type === "Identifier") return node.key.name;
  if (node.key.type === "Literal" && typeof node.key.value === "string") return node.key.value;
  return null;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Prefer promise-based Node.js filesystem APIs over synchronous calls in production modules.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      preferAsyncFs: "Node filesystem API `{{name}}` is synchronous; use the promise API and await it.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    const namespaces = new Set<TsVariable>();
    const bindingOf = (node: Identifier): TsVariable | null =>
      findVariable(sourceCode.getScope(node), node.name);
    const isGlobal = (node: Identifier): boolean => {
      const binding = bindingOf(node);
      return binding === null || binding.defs.length === 0;
    };
    const isNamespace = (node: Identifier): boolean => {
      const binding = bindingOf(node);
      return binding !== null && namespaces.has(binding);
    };
    const recordNamespace = (node: Identifier): void => {
      const binding = bindingOf(node);
      if (binding !== null && stableValueBinding(binding)) namespaces.add(binding);
    };
    return {
      before(): boolean | void {
        const file = { filename: context.filename, cwd: context.cwd };
        const normalizedFilename = context.filename.replaceAll("\\", "/");
        if (
          isTestFile(file) ||
          isGeneratedFile(file, context.sourceCode.text) ||
          normalizedFilename.includes("src/rules/")
        )
          return false;
        sourceCode = context.sourceCode;
        namespaces.clear();
      },
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (node.source.value !== "node:fs" && node.source.value !== "fs") return;
        const synchronousImports: string[] = [];
        for (const specifier of node.specifiers) {
          if (specifier.type === "ImportNamespaceSpecifier" || specifier.type === "ImportDefaultSpecifier") {
            recordNamespace(specifier.local);
            continue;
          }
          if (
            specifier.type === "ImportSpecifier" &&
            importSpecifierName(specifier).endsWith("Sync")
          ) synchronousImports.push(importSpecifierName(specifier));
        }
        if (synchronousImports.length > 0) {
          context.report({
            node,
            messageId: "preferAsyncFs",
            data: { name: synchronousImports.join(", ") },
          });
        }
      },
      VariableDeclarator(node: ESTree.VariableDeclarator): void {
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
      MemberExpression(node: ESTree.MemberExpression): void {
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
