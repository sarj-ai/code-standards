/**
 * @fileoverview no-detached-global-fetch — keep ambient fetch receiver-safe when it is stored or explicitly rebound.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-detached-global-fetch.test.ts
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

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
const STORAGE_ASSIGNMENT_OPERATORS: ReadonlySet<TSESTree.AssignmentExpression["operator"]> =
  new Set(["=", "&&=", "??=", "||="]);

function unwrapExpression(node: TSESTree.Expression): TSESTree.Expression {
  let current = node;
  while (
    current.type === AST_NODE_TYPES.ChainExpression ||
    current.type === AST_NODE_TYPES.TSAsExpression ||
    current.type === AST_NODE_TYPES.TSNonNullExpression ||
    current.type === AST_NODE_TYPES.TSTypeAssertion
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
      isTestFile(context.filename) ||
      isScriptFile(context.filename) ||
      isGeneratedFile(context.filename, sourceCode.text)
    ) return {};

    const aliases = new Set<TSESLint.Scope.Variable>();

    function bindingOf(identifier: TSESTree.Identifier): TSESLint.Scope.Variable | null {
      return ASTUtils.findVariable(sourceCode.getScope(identifier), identifier.name);
    }

    function resolvesToGlobal(identifier: TSESTree.Identifier): boolean {
      const variable = bindingOf(identifier);
      return variable === null || variable.defs.length === 0;
    }

    function isGlobalReceiver(node: TSESTree.Node): node is TSESTree.Identifier {
      return node.type === AST_NODE_TYPES.Identifier &&
        GLOBAL_RECEIVERS.has(node.name) && resolvesToGlobal(node);
    }

    function isStableAlias(variable: TSESLint.Scope.Variable): boolean {
      return !variable.references.some(
        (reference) => reference.isWrite() && reference.init !== true,
      );
    }

    function recordAlias(identifier: TSESTree.Identifier): void {
      const variable = bindingOf(identifier);
      if (variable !== null && isStableAlias(variable)) aliases.add(variable);
    }

    function isGlobalFetchMember(node: TSESTree.MemberExpression): boolean {
      if (!isGlobalReceiver(node.object)) return false;
      if (!node.computed) {
        return node.property.type === AST_NODE_TYPES.Identifier && node.property.name === "fetch";
      }
      return node.property.type === AST_NODE_TYPES.Literal && node.property.value === "fetch";
    }

    function staticMemberName(node: TSESTree.MemberExpression): string | null {
      if (!node.computed) {
        return node.property.type === AST_NODE_TYPES.Identifier ? node.property.name : null;
      }
      return node.property.type === AST_NODE_TYPES.Literal && typeof node.property.value === "string"
        ? node.property.value
        : null;
    }

    function mayBeRawFetch(node: TSESTree.Expression): boolean {
      const expression = unwrapExpression(node);
      if (expression.type === AST_NODE_TYPES.Identifier) {
        if (expression.name === "fetch" && resolvesToGlobal(expression)) return true;
        const variable = bindingOf(expression);
        return variable !== null && aliases.has(variable) && isStableAlias(variable);
      }
      if (expression.type === AST_NODE_TYPES.MemberExpression) {
        return isGlobalFetchMember(expression);
      }
      if (expression.type === AST_NODE_TYPES.LogicalExpression) {
        // A raw fetch operand is always truthy, so `fetch && fallback` cannot
        // produce fetch. The right side of `&&`, and either side of `||`/`??`,
        // can still be the stored result.
        return expression.operator === "&&"
          ? mayBeRawFetch(expression.right)
          : mayBeRawFetch(expression.left) || mayBeRawFetch(expression.right);
      }
      if (expression.type === AST_NODE_TYPES.ConditionalExpression) {
        return mayBeRawFetch(expression.consequent) || mayBeRawFetch(expression.alternate);
      }
      if (expression.type === AST_NODE_TYPES.SequenceExpression) {
        const last = expression.expressions.at(-1);
        return last !== undefined && mayBeRawFetch(last);
      }
      return false;
    }

    function recordAliasFromValue(identifier: TSESTree.Identifier, value: TSESTree.Expression): void {
      if (mayBeRawFetch(value)) recordAlias(identifier);
    }

    function reportStored(node: TSESTree.Expression): void {
      if (mayBeRawFetch(node)) context.report({ node, messageId: "detachedGlobalFetch" });
    }

    function isCompatibleReceiver(node: TSESTree.CallExpressionArgument | undefined): boolean {
      if (node === undefined || node.type === AST_NODE_TYPES.SpreadElement) return false;
      if (node.type !== AST_NODE_TYPES.Identifier || !resolvesToGlobal(node)) return false;
      return GLOBAL_RECEIVERS.has(node.name) || node.name === "undefined";
    }

    return {
      AssignmentExpression(node): void {
        if (
          STORAGE_ASSIGNMENT_OPERATORS.has(node.operator) &&
          node.left.type === AST_NODE_TYPES.MemberExpression
        ) {
          reportStored(node.right);
        }
      },
      AssignmentPattern(node): void {
        if (node.left.type !== AST_NODE_TYPES.Identifier) return;
        recordAliasFromValue(node.left, node.right);
        if (node.parent.type === AST_NODE_TYPES.TSParameterProperty) reportStored(node.right);
      },
      CallExpression(node): void {
        const callee = unwrapExpression(node.callee);
        if (
          callee.type !== AST_NODE_TYPES.MemberExpression ||
          !EXPLICIT_RECEIVER_METHODS.has(staticMemberName(callee) ?? "") ||
          !mayBeRawFetch(callee.object) ||
          isCompatibleReceiver(node.arguments[0])
        ) return;
        context.report({ node: callee.object, messageId: "detachedGlobalFetch" });
      },
      Property(node): void {
        if (
          node.parent.type === AST_NODE_TYPES.ObjectPattern ||
          node.method ||
          node.value.type === AST_NODE_TYPES.AssignmentPattern ||
          node.value.type === AST_NODE_TYPES.TSEmptyBodyFunctionExpression
        ) return;
        reportStored(node.value);
      },
      PropertyDefinition(node): void {
        if (node.value !== null) reportStored(node.value);
      },
      VariableDeclarator(node): void {
        if (node.init === null) return;
        if (node.id.type === AST_NODE_TYPES.Identifier) {
          recordAliasFromValue(node.id, node.init);
          return;
        }
        if (
          node.id.type !== AST_NODE_TYPES.ObjectPattern ||
          !isGlobalReceiver(unwrapExpression(node.init))
        ) return;
        for (const property of node.id.properties) {
          if (
            property.type !== AST_NODE_TYPES.Property ||
            property.computed ||
            property.key.type !== AST_NODE_TYPES.Identifier ||
            property.key.name !== "fetch"
          ) continue;
          const value = property.value.type === AST_NODE_TYPES.AssignmentPattern
            ? property.value.left
            : property.value;
          if (value.type === AST_NODE_TYPES.Identifier) recordAlias(value);
        }
      },
    } satisfies TSESLint.RuleListener;
  },
});
