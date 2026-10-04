/**
 * @fileoverview no-detached-global-fetch — keep ambient fetch receiver-safe when it is stored or explicitly rebound.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-detached-global-fetch.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, Variable, Visitor } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isScriptFile, isTestFile } from "./_paths.js";

type MessageIds = "detachedGlobalFetch";
type Options = readonly [];

export const NO_DETACHED_GLOBAL_FETCH_DOCUMENTATION = {
  summary: "Keep the ambient global fetch receiver-safe when storing or explicitly rebinding it.",
  rationale: "Calling a raw ambient fetch through a class or object property supplies that object as `this`; receiver-sensitive hosts can reject that invocation only after deployment.",
  remediation: "Store a forwarding wrapper such as `(input, init) => fetch(input, init)`, or bind the callable to a compatible global or undefined receiver before storing it.",
  category: "correctness",
  autofix: "none",
  limitations: [
    "The rule follows stable local variables and defaulted parameters from an unshadowed ambient fetch or globalThis/self/window fetch into direct class, object, or member storage.",
    "Bare local aliases, callback arguments, returns, direct calls, compatible global or undefined bind/call/apply receivers, tests, scripts, generated files, and locally defined fetch implementations are excluded.",
    "Interprocedural aliases, mutable aliases, collection storage, and host identity remain manual review boundaries.",
  ],
  examples: [
    {
      id: "forwarded-global-fetch",
      title: "Store a receiver-safe forwarding wrapper",
      outcome: "no-match",
      files: [{ path: "src/client.ts", source: "class Client { readonly request = (input: RequestInfo | URL, init?: RequestInit) => fetch(input, init); }" }],
      focusPath: "src/client.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "receiver-unsafe-global-fetch",
      title: "Do not store raw ambient fetch as an object method",
      outcome: "match",
      files: [{ path: "src/client.ts", source: "class Client { readonly request = fetch; }" }],
      focusPath: "src/client.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

const GLOBAL_RECEIVERS: ReadonlySet<string> = new Set(["globalThis", "self", "window"]);
const EXPLICIT_RECEIVER_METHODS: ReadonlySet<string> = new Set(["apply", "bind", "call"]);
const STORAGE_ASSIGNMENT_OPERATORS: ReadonlySet<ESTree.AssignmentExpression["operator"]> =
  new Set(["=", "&&=", "??=", "||="]);

function unwrapExpression(node: ESTree.Node): ESTree.Node {
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

export default createRule<Options, MessageIds>({
  name: "no-detached-global-fetch",
  documentation: NO_DETACHED_GLOBAL_FETCH_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: NO_DETACHED_GLOBAL_FETCH_DOCUMENTATION.summary },
    schema: [],
    messages: {
      detachedGlobalFetch:
        "Raw ambient `fetch` becomes receiver-unsafe when stored or rebound this way. Store a forwarding wrapper or bind it to a compatible global or undefined receiver.",
    },
  },
  defaultOptions: [],
  create(context) {
    const sourceCode = context.sourceCode;
    if (
      isTestFile(sourceOrigin(context).filename) ||
      isScriptFile(sourceOrigin(context).filename) ||
      isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)
    ) return {};

    const aliases = new Set<Variable>();

    function bindingOf(identifier: ESTree.BindingIdentifier): Variable | null {
      return findVariable(sourceCode.getScope(identifier), identifier.name);
    }

    function resolvesToGlobal(identifier: ESTree.BindingIdentifier): boolean {
      const variable = bindingOf(identifier);
      return variable === null || variable.defs.length === 0;
    }

    function isGlobalReceiver(node: ESTree.Node): node is ESTree.BindingIdentifier {
      return node.type === "Identifier" &&
        GLOBAL_RECEIVERS.has(node.name) && resolvesToGlobal(node);
    }

    function isStableAlias(variable: Variable): boolean {
      return !variable.references.some(
        (reference) => reference.isWrite() && reference.init !== true,
      );
    }

    function recordAlias(identifier: ESTree.BindingIdentifier): void {
      const variable = bindingOf(identifier);
      if (variable !== null && isStableAlias(variable)) aliases.add(variable);
    }

    function staticMemberName(node: ESTree.MemberExpression): string | null {
      if (!node.computed) {
        return node.property.type === "Identifier" ? node.property.name : null;
      }
      return node.property.type === "Literal" && typeof node.property.value === "string"
        ? node.property.value
        : null;
    }

    function mayBeRawFetch(node: ESTree.Node): boolean {
      const expression = unwrapExpression(node);
      if (expression.type === "Identifier") {
        if (expression.name === "fetch" && resolvesToGlobal(expression)) return true;
        const variable = bindingOf(expression);
        return variable !== null && aliases.has(variable) && isStableAlias(variable);
      }
      if (expression.type === "MemberExpression") {
        return isGlobalFetchMember(expression);
      }
      if (expression.type === "LogicalExpression") {
        // A raw fetch operand is always truthy, so `fetch && fallback` cannot
        // produce fetch. The right side of `&&`, and either side of `||`/`??`,
        // can still be the stored result.
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

    function recordAliasFromValue(identifier: ESTree.BindingIdentifier, value: ESTree.Expression): void {
      if (mayBeRawFetch(value)) recordAlias(identifier);
    }

    function reportStored(node: ESTree.Node): void {
      if (mayBeRawFetch(node)) context.report({ node, messageId: "detachedGlobalFetch" });
    }

    function isCompatibleReceiver(node: ESTree.Argument | undefined): boolean {
      if (node == null || node.type === "SpreadElement") return false;
      if (node.type !== "Identifier" || !resolvesToGlobal(node)) return false;
      return GLOBAL_RECEIVERS.has(node.name) || node.name === "undefined";
    }

    return {
      AssignmentExpression(node): void {
        if (
          STORAGE_ASSIGNMENT_OPERATORS.has(node.operator) &&
          node.left.type === "MemberExpression"
        ) {
          reportStored(node.right);
        }
      },
      AssignmentPattern(node): void {
        if (node.left.type !== "Identifier") return;
        recordAliasFromValue(node.left, node.right);
        if (node.parent?.type === "TSParameterProperty") reportStored(node.right);
      },
      CallExpression(node): void {
        const callee = unwrapExpression(node.callee);
        if (
          callee.type !== "MemberExpression" ||
          !EXPLICIT_RECEIVER_METHODS.has(staticMemberName(callee) ?? "") ||
          !mayBeRawFetch(callee.object) ||
          isCompatibleReceiver(node.arguments[0])
        ) return;
        context.report({ node: callee.object, messageId: "detachedGlobalFetch" });
      },
      Property(node): void {
        if (!("method" in node)) return;
        if (
          node.parent?.type === "ObjectPattern" ||
          node.method ||
          node.value.type === "AssignmentPattern" ||
          node.value.type === "ObjectPattern" || node.value.type === "ArrayPattern" ||
          node.value.type === "TSEmptyBodyFunctionExpression"
        ) return;
        reportStored(node.value);
      },
      PropertyDefinition(node): void {
        if (node.value !== null) reportStored(node.value);
      },
      VariableDeclarator(node): void {
        if (node.init === null) return;
        if (node.id.type === "Identifier") {
          recordAliasFromValue(node.id, node.init);
          return;
        }
        if (
          node.id.type !== "ObjectPattern" ||
          !isGlobalReceiver(unwrapExpression(node.init))
        ) return;
        for (const property of node.id.properties) {
          if (
            property.type !== "Property" ||
            property.computed ||
            property.key.type !== "Identifier" ||
            property.key.name !== "fetch"
          ) continue;
          const value = property.value.type === "AssignmentPattern"
            ? property.value.left
            : property.value;
          if (value.type === "Identifier") recordAlias(value);
        }
      },
    } satisfies Visitor;
  },
});
