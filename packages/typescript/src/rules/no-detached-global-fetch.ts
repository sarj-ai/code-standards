/**
 * @fileoverview no-detached-global-fetch — keep ambient fetch receiver-safe when it is stored or explicitly rebound.
 *
 * Port of the 18.x `no-detached-global-fetch` rule. File gates move to
 * `before()`; the alias set is reset per file.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-detached-global-fetch.test.ts
 */

import { defineRule, type ESTree, type Identifier, type Node, type SourceCode, type TsVariable } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isScriptFile, isTestFile } from "../utils/paths.js";
import { stableValueBinding } from "../utils/stable-value-binding.js";
import { findVariable } from "../utils/static-string.js";
import { ownedFetchFix } from "./_owned-fetch-fix.js";

const GLOBAL_RECEIVERS: ReadonlySet<string> = new Set(["globalThis", "self", "window"]);

const EXPLICIT_RECEIVER_METHODS: ReadonlySet<string> = new Set(["apply", "bind", "call"]);

const STORAGE_ASSIGNMENT_OPERATORS: ReadonlySet<string> = new Set(["=", "&&=", "??=", "||="]);

function unwrapExpression(node: Node): Node {
  let current = node;
  while (
    current.type === "ChainExpression" ||
    current.type === "TSAsExpression" ||
    current.type === "TSNonNullExpression" ||
    current.type === "TSTypeAssertion"
  ) {
    current = current.expression;
  }
  return current;
}

function staticMemberName(node: ESTree.MemberExpression): string | null {
  if (!node.computed) {
    return node.property.type === "Identifier" ? node.property.name : null;
  }
  return node.property.type === "Literal" && typeof node.property.value === "string"
    ? node.property.value
    : null;
}

export default defineRule({
  meta: {
    type: "problem",
    fixable: "code",
    docs: {
      description: "Keep the ambient global fetch receiver-safe when storing or explicitly rebinding it.",
      url: docsUrl("no-detached-global-fetch"),
    },
    schema: [],
    messages: {
      detachedGlobalFetch:
        "Raw ambient `fetch` becomes receiver-unsafe when stored or rebound this way. Store a forwarding wrapper or bind it to a compatible global or undefined receiver.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let aliases = new Set<TsVariable>();

    function bindingOf(identifier: Identifier): TsVariable | null {
      return findVariable(sourceCode.getScope(identifier), identifier.name);
    }

    function resolvesToGlobal(identifier: Identifier): boolean {
      const variable = bindingOf(identifier);
      return variable === null || variable.defs.length === 0;
    }

    function isGlobalReceiver(node: Node): boolean {
      return node.type === "Identifier" && GLOBAL_RECEIVERS.has(node.name) && resolvesToGlobal(node);
    }

    function recordAlias(identifier: Identifier): void {
      const variable = bindingOf(identifier);
      if (variable !== null && stableValueBinding(variable)) aliases.add(variable);
    }

    function mayBeRawFetch(node: Node): boolean {
      const expression = unwrapExpression(node);
      if (expression.type === "Identifier") {
        if (expression.name === "fetch" && resolvesToGlobal(expression)) return true;
        const variable = bindingOf(expression);
        return variable !== null && aliases.has(variable);
      }
      if (expression.type === "MemberExpression") {
        return isGlobalFetchMember(expression);
      }
      if (expression.type === "LogicalExpression") {
        return expression.operator === "&&"
          ? mayBeRawFetch(expression.right)
          : mayBeRawFetch(expression.left) || mayBeRawFetch(expression.right);
      }
      if (expression.type === "ConditionalExpression") {
        return mayBeRawFetch(expression.consequent) || mayBeRawFetch(expression.alternate);
      }
      if (expression.type === "SequenceExpression") {
        const last = expression.expressions.at(-1);
        return last !== undefined && mayBeRawFetch(last);
      }
      return false;
    }

    function isGlobalFetchMember(node: ESTree.MemberExpression): boolean {
      if (!isGlobalReceiver(node.object)) return false;
      if (!node.computed) {
        return node.property.type === "Identifier" && node.property.name === "fetch";
      }
      return node.property.type === "Literal" && node.property.value === "fetch";
    }

    function recordAliasFromValue(identifier: Identifier, value: Node): void {
      if (mayBeRawFetch(value)) recordAlias(identifier);
    }

    function reportStored(node: Node): void {
      if (!mayBeRawFetch(node)) return;
      const fix = ownedFetchFix(sourceCode, node);
      context.report({ node, messageId: "detachedGlobalFetch", ...(fix !== null && { fix }) });
    }

    function isCompatibleReceiver(node: Node | undefined): boolean {
      if (node === undefined || node.type === "SpreadElement") return false;
      if (node.type !== "Identifier" || !resolvesToGlobal(node)) return false;
      return GLOBAL_RECEIVERS.has(node.name) || node.name === "undefined";
    }

    return {
      before() {
        sourceCode = context.sourceCode;
        const file = { filename: context.filename, cwd: context.cwd };
        if (isTestFile(file) || isScriptFile(file) || isGeneratedFile(file, sourceCode.text)) return false;
        aliases = new Set();
        return undefined;
      },
      AssignmentExpression(node: ESTree.AssignmentExpression): void {
        if (STORAGE_ASSIGNMENT_OPERATORS.has(node.operator) && node.left.type === "MemberExpression") {
          reportStored(node.right);
        }
      },
      AssignmentPattern(node: ESTree.AssignmentPattern): void {
        if (node.left.type !== "Identifier") return;
        recordAliasFromValue(node.left, node.right);
        if (parentOf(node)?.type === "TSParameterProperty") reportStored(node.right);
      },
      CallExpression(node: ESTree.CallExpression): void {
        const callee = unwrapExpression(node.callee);
        if (
          callee.type !== "MemberExpression" ||
          !EXPLICIT_RECEIVER_METHODS.has(staticMemberName(callee) ?? "") ||
          !mayBeRawFetch(callee.object) ||
          isCompatibleReceiver(node.arguments[0])
        )
          return;
        context.report({ node: callee.object, messageId: "detachedGlobalFetch" });
      },
      Property(node: ESTree.Node): void {
        if (node.type !== "Property") return;
        if (
          parentOf(node)?.type === "ObjectPattern" ||
          node.method ||
          node.value.type === "AssignmentPattern" ||
          (node.value.type as string) === "TSEmptyBodyFunctionExpression"
        )
          return;
        reportStored(node.value);
      },
      PropertyDefinition(node: ESTree.PropertyDefinition): void {
        if (node.value !== null) reportStored(node.value);
      },
      VariableDeclarator(node: ESTree.VariableDeclarator): void {
        if (node.init === null) return;
        if (node.id.type === "Identifier") {
          recordAliasFromValue(node.id, node.init);
          return;
        }
        if (node.id.type !== "ObjectPattern" || !isGlobalReceiver(unwrapExpression(node.init))) return;
        for (const property of node.id.properties) {
          if (
            property.type !== "Property" ||
            property.computed ||
            property.key.type !== "Identifier" ||
            property.key.name !== "fetch"
          )
            continue;
          const value = property.value.type === "AssignmentPattern" ? property.value.left : property.value;
          if (value.type === "Identifier") recordAlias(value);
        }
      },
    };
  },
});
