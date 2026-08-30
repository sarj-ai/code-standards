/**
 * @fileoverview prefer-multi-value-zod-literal — prefer Zod 4 multi-value literals to unions of literal schemas.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-multi-value-zod-literal.test.ts
 */
import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

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
  limitations: [
    "Bare `zod` imports are analyzed only when the rule option explicitly declares `zodMajorVersion: 4`; `zod/v4` imports are self-declaring.",
  ],
  examples: [
    {
      id: "multi-value",
      title: "Use one multi-value literal",
      outcome: "no-match",
      files: [
        {
          path: "src/schema.ts",
          source:
            "import { z } from 'zod'; export const Version = z.literal([1, 2, 3]);",
        },
      ],
      focusPath: "src/schema.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "literal-union",
      title: "Avoid repeated literal wrappers",
      outcome: "match",
      files: [
        {
          path: "src/schema.ts",
          source:
            "import { z } from 'zod'; export const Version = z.union([z.literal(1), z.literal(2), z.literal(3)]);",
        },
      ],
      focusPath: "src/schema.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function memberCall(
  node: TSESTree.CallExpression,
  object: string,
  method: string,
): boolean {
  return (
    node.callee.type === AST_NODE_TYPES.MemberExpression &&
    !node.callee.computed &&
    node.callee.object.type === AST_NODE_TYPES.Identifier &&
    node.callee.object.name === object &&
    node.callee.property.type === AST_NODE_TYPES.Identifier &&
    node.callee.property.name === method
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
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          zodMajorVersion: { type: "integer", minimum: 4, maximum: 4 },
        },
      },
    ],
    messages: {
      useMultiValueLiteral:
        "Replace this literal-schema union with `{{zod}}.literal([…])`.",
    },
  },
  defaultOptions: [{}],
  create(context, [options]) {
    if (
      isTestFile(context.filename) ||
      isGeneratedFile(context.filename, context.sourceCode.text)
    )
      return {};
    const namespaces = new Set<string>();
    const zod4Namespaces = new Set<string>();
    return {
      ImportDeclaration(node): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier ||
            specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier ||
            (specifier.type === AST_NODE_TYPES.ImportSpecifier &&
              specifier.imported.type === AST_NODE_TYPES.Identifier &&
              specifier.imported.name === "z")
          ) {
            namespaces.add(specifier.local.name);
            if (
              node.source.value === "zod/v4" ||
              node.source.value.startsWith("zod/v4/")
            )
              zod4Namespaces.add(specifier.local.name);
          }
        }
      },
      CallExpression(node): void {
        const namespace = [...namespaces].find((name) =>
          memberCall(node, name, "union"),
        );
        if (
          namespace === undefined ||
          (options?.zodMajorVersion !== 4 && !zod4Namespaces.has(namespace)) ||
          node.arguments.length !== 1
        )
          return;
        const [argument] = node.arguments;
        if (
          argument?.type !== AST_NODE_TYPES.ArrayExpression ||
          argument.elements.length < 3 ||
          argument.elements.some((element) => {
            if (
              element === null ||
              element.type !== AST_NODE_TYPES.CallExpression ||
              !memberCall(element, namespace, "literal") ||
              element.arguments.length !== 1
            )
              return true;
            const [value] = element.arguments;
            return (
              value === undefined ||
              value.type === AST_NODE_TYPES.SpreadElement ||
              ![
                AST_NODE_TYPES.Literal,
                AST_NODE_TYPES.TemplateLiteral,
              ].includes(value.type)
            );
          })
        )
          return;
        context.report({
          node,
          messageId: "useMultiValueLiteral",
          data: { zod: namespace },
        });
      },
    };
  },
});
