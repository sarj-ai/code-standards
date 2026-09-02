/**
 * @fileoverview prefer-multi-value-zod-literal — prefer Zod 4 multi-value literals to unions of literal schemas.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-multi-value-zod-literal.test.ts
 */
import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { isZodModule } from "./_zod.js";

type MessageIds = "useMultiValueLiteral";
type Options = readonly [{ zodMajorVersion?: 4 }];

export const PREFER_MULTI_VALUE_ZOD_LITERAL_DOCUMENTATION = {
  summary:
    "Use the Zod 4 multi-value literal API instead of a union of literal schemas.",
  rationale:
    "One multi-value literal expresses the same closed value domain without repeated schema wrappers.",
  remediation: "Replace the union with z.literal([value1, value2, ...]).",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Bare zod imports are analyzed only when the rule option explicitly declares zodMajorVersion: 4; explicit zod/v4 entrypoints are self-declaring.",
    "All-string domains are left to zod/prefer-enum-over-literal-union.",
    "A finding containing comments is not autofixed because moving its trivia is ambiguous.",
  ],
  examples: [
    {
      id: "multi-value",
      title: "Use one multi-value literal",
      outcome: "no-match",
      files: [{
        path: "src/schema.ts",
        source:
          "import { z } from 'zod'; export const Version = z.literal([1, 2, 3]);",
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
          "import { z } from 'zod'; export const Version = z.union([z.literal(1), z.literal(2), z.literal(3)]);",
      }],
      fixedFiles: [{
        path: "src/schema.ts",
        source:
          "import { z } from 'zod'; export const Version = z.literal([1, 2, 3]);",
      }],
      focusPath: "src/schema.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function isStaticPrimitive(
  node: TSESTree.CallExpressionArgument,
  context: TSESLint.RuleContext<MessageIds, Options>,
): boolean {
  if (node.type === AST_NODE_TYPES.Literal) {
    return (
      node.value === null ||
      ["bigint", "boolean", "number", "string"].includes(typeof node.value)
    );
  }
  if (
    node.type === AST_NODE_TYPES.TemplateLiteral &&
    node.expressions.length === 0
  )
    return true;
  if (node.type === AST_NODE_TYPES.Identifier && node.name === "undefined") {
    const binding = ASTUtils.findVariable(
      context.sourceCode.getScope(node),
      node.name,
    );
    return binding === null || binding.defs.length === 0;
  }
  return (
    node.type === AST_NODE_TYPES.UnaryExpression &&
    node.operator === "-" &&
    node.argument.type === AST_NODE_TYPES.Literal &&
    ["bigint", "number"].includes(typeof node.argument.value)
  );
}

function isStaticString(node: TSESTree.CallExpressionArgument): boolean {
  return (
    (node.type === AST_NODE_TYPES.Literal &&
      typeof node.value === "string") ||
    (node.type === AST_NODE_TYPES.TemplateLiteral &&
      node.expressions.length === 0)
  );
}

export default createRule<Options, MessageIds>({
  name: "prefer-multi-value-zod-literal",
  documentation: PREFER_MULTI_VALUE_ZOD_LITERAL_DOCUMENTATION,
  meta: {
    type: "suggestion",
    fixable: "code",
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
      isTestFile(context.filename) ||
      isGeneratedFile(context.filename, context.sourceCode.text)
    )
      return {};

    const zodBindings = new Set<TSESLint.Scope.Variable>();
    const zod4Bindings = new Set<TSESLint.Scope.Variable>();

    function resolvedBinding(
      identifier: TSESTree.Identifier,
    ): TSESLint.Scope.Variable | null {
      return ASTUtils.findVariable(
        context.sourceCode.getScope(identifier),
        identifier.name,
      );
    }

    function directMemberCall(
      node: TSESTree.CallExpression,
      binding: TSESLint.Scope.Variable,
      method: string,
    ): boolean {
      if (
        node.callee.type !== AST_NODE_TYPES.MemberExpression ||
        node.callee.computed ||
        node.callee.object.type !== AST_NODE_TYPES.Identifier ||
        node.callee.property.type !== AST_NODE_TYPES.Identifier ||
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
            specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier ||
            specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier ||
            (specifier.type === AST_NODE_TYPES.ImportSpecifier &&
              (specifier.imported.type === AST_NODE_TYPES.Identifier
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
          node.callee.type !== AST_NODE_TYPES.MemberExpression ||
          node.callee.object.type !== AST_NODE_TYPES.Identifier
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
          argument?.type !== AST_NODE_TYPES.ArrayExpression ||
          argument.elements.length < 2
        )
          return;

        const values: TSESTree.CallExpressionArgument[] = [];
        for (const element of argument.elements) {
          if (
            element === null ||
            element.type !== AST_NODE_TYPES.CallExpression ||
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
        const hasComments =
          context.sourceCode.getCommentsInside(node).length > 0;
        context.report({
          node,
          messageId: "useMultiValueLiteral",
          data: { zod: namespace },
          fix: hasComments
            ? null
            : (fixer) =>
                fixer.replaceText(
                  node,
                  `${namespace}.literal([${values
                    .map((value) => context.sourceCode.getText(value))
                    .join(", ")}])`,
                ),
        });
      },
    } satisfies TSESLint.RuleListener;
  },
});
