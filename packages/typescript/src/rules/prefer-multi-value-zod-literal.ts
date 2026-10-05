/**
 * @fileoverview prefer-multi-value-zod-literal — prefer Zod 4 multi-value literals to unions of literal schemas.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-multi-value-zod-literal.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, Context, Variable, Visitor } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { isZodModule } from "./_zod.js";

type MessageIds = "useMultiValueLiteral";
type Options = readonly [{ zodMajorVersion?: 4 }];

export const PREFER_MULTI_VALUE_ZOD_LITERAL_DOCUMENTATION = {
  defaultLevel: "warning",
  summary:
    "Use the Zod 4 multi-value literal API instead of a union of literal schemas.",
  rationale:
    "One multi-value literal expresses the same closed value domain without repeated schema wrappers.",
  remediation: "Replace the union with z.literal([value1, value2, ...]).",
  category: "maintainability",
  autofix: "none",
  limitations: [
    "Bare zod imports are analyzed only when the rule option explicitly declares zodMajorVersion: 4; explicit zod/v4 entrypoints are self-declaring.",
    "All-string domains are left to zod/prefer-enum-over-literal-union.",
    "Migration is manual: ZodLiteral and ZodUnion expose different introspection APIs and validation error shapes even when they accept the same values.",
  ],
  examples: [
    {
      id: "multi-value",
      title: "Use one multi-value literal",
      outcome: "no-match",
      files: [{
        path: "src/schema.ts",
        source:
          "import { z } from 'zod/v4'; export const Version = z.literal([1, 2, 3]);",
      }],
      focusPath: "src/schema.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "literal-union",
      title: "Avoid repeated literal wrappers",
      outcome: "match",
      files: [{
        path: "src/schema.ts",
        source:
          "import { z } from 'zod/v4'; export const Version = z.union([z.literal(1), z.literal(2), z.literal(3)]);",
      }],
      focusPath: "src/schema.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function isStaticPrimitive(
  node: ESTree.Argument,
  context: Context,
): boolean {
  if (node.type === "Literal") {
    return (
      node.value === null ||
      ["bigint", "boolean", "number", "string"].includes(typeof node.value)
    );
  }
  if (
    node.type === "TemplateLiteral" &&
    node.expressions.length === 0
  )
    return true;
  if (node.type === "Identifier" && node.name === "undefined") {
    const binding = findVariable(
      context.sourceCode.getScope(node),
      node.name,
    );
    return binding === null || binding.defs.length === 0;
  }
  return (
    node.type === "UnaryExpression" &&
    node.operator === "-" &&
    node.argument.type === "Literal" &&
    ["bigint", "number"].includes(typeof node.argument.value)
  );
}

function isStaticString(node: ESTree.Argument): boolean {
  return (
    (node.type === "Literal" &&
      typeof node.value === "string") ||
    (node.type === "TemplateLiteral" &&
      node.expressions.length === 0)
  );
}

export default createRule<Options, MessageIds>({
  name: "prefer-multi-value-zod-literal",
  documentation: PREFER_MULTI_VALUE_ZOD_LITERAL_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Use the Zod 4 multi-value literal API instead of a union of literal schemas.",
    },
    schema: [{
      type: "object",
      additionalProperties: false,
      properties: {
        zodMajorVersion: { type: "integer", minimum: 4, maximum: 4 },
      },
    }],
    messages: {
      useMultiValueLiteral:
        "Replace this literal-schema union with {{zod}}.literal([…]).",
    },
  },
  defaultOptions: [{}],
  create(context, [options]) {
    if (
      isTestFile(sourceOrigin(context).filename) ||
      isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)
    )
      return {};

    const zodBindings = new Set<Variable>();
    const zod4Bindings = new Set<Variable>();

    function resolvedBinding(
      identifier: ESTree.BindingIdentifier,
    ): Variable | null {
      return findVariable(
        context.sourceCode.getScope(identifier),
        identifier.name,
      );
    }

    function directMemberCall(
      node: ESTree.CallExpression,
      binding: Variable,
      method: string,
    ): boolean {
      if (
        node.callee.type !== "MemberExpression" ||
        node.callee.computed ||
        node.callee.object.type !== "Identifier" ||
        node.callee.property.type !== "Identifier" ||
        node.callee.property.name !== method
      )
        return false;
      return resolvedBinding(node.callee.object) === binding;
    }

    return {
      ImportDeclaration(node): void {
        if (!isZodModule(node.source.value)) return;
        const isExplicitV4 = /^zod\/v4(?:$|[-/])/.test(node.source.value);
        for (const specifier of node.specifiers) {
          if (
            specifier.type === "ImportDefaultSpecifier" ||
            specifier.type === "ImportNamespaceSpecifier" ||
            (specifier.type === "ImportSpecifier" &&
              (specifier.imported.type === "Identifier"
                ? specifier.imported.name === "z"
                : specifier.imported.value === "z"))
          ) {
            const binding = resolvedBinding(specifier.local);
            if (binding === null) continue;
            zodBindings.add(binding);
            if (isExplicitV4) zod4Bindings.add(binding);
          }
        }
      },
      CallExpression(node): void {
        if (
          node.callee.type !== "MemberExpression" ||
          node.callee.object.type !== "Identifier"
        )
          return;
        const binding = resolvedBinding(node.callee.object);
        if (
          binding === null ||
          !zodBindings.has(binding) ||
          !directMemberCall(node, binding, "union") ||
          (options?.zodMajorVersion !== 4 && !zod4Bindings.has(binding)) ||
          node.arguments.length !== 1
        )
          return;
        const [argument] = node.arguments;
        if (
          argument?.type !== "ArrayExpression" ||
          argument.elements.length < 2
        )
          return;

        const values: ESTree.Argument[] = [];
        for (const element of argument.elements) {
          if (
            element === null ||
            element.type !== "CallExpression" ||
            !directMemberCall(element, binding, "literal") ||
            element.arguments.length !== 1
          )
            return;
          const [value] = element.arguments;
          if (value === undefined || !isStaticPrimitive(value, context)) return;
          values.push(value);
        }
        if (values.every(isStaticString)) return;

        const namespace = node.callee.object.name;
        context.report({
          node,
          messageId: "useMultiValueLiteral",
          data: { zod: namespace },
        });
      },
    } satisfies Visitor;
  },
});
