/**
 * @fileoverview prefer-zod-enum — a union of `z.literal` strings infers exactly what `z.enum` does, in more syntax that hides the permitted values.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-zod-enum.test.ts
 */

import { AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isZodModule } from "./_zod.js";

type MessageIds = "preferEnum";
type Options = readonly [];

export default createRule<Options, MessageIds>({
  name: "prefer-zod-enum",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Prefer z.enum([...]) over z.union([z.literal(...), ...]) for string choices",
    },
    fixable: "code",
    schema: [],
    messages: {
      preferEnum:
        "Use `z.enum([...])` instead of a union of string-literal schemas.",
    },
  },
  defaultOptions: [],
  create(context) {
    const sourceCode = context.sourceCode;
    const zodNamespaces = new Set<string>();

    function enumValues(
      node: TSESTree.CallExpression,
    ): readonly TSESTree.StringLiteral[] | null {
      const callee = node.callee;
      if (
        callee.type !== AST_NODE_TYPES.MemberExpression ||
        callee.computed ||
        callee.object.type !== AST_NODE_TYPES.Identifier ||
        !zodNamespaces.has(callee.object.name) ||
        callee.property.type !== AST_NODE_TYPES.Identifier ||
        callee.property.name !== "union" ||
        node.arguments.length !== 1
      ) {
        return null;
      }
      const argument = node.arguments[0];
      if (
        argument === undefined ||
        argument.type !== AST_NODE_TYPES.ArrayExpression ||
        argument.elements.length === 0
      ) {
        return null;
      }

      const values: TSESTree.StringLiteral[] = [];
      for (const element of argument.elements) {
        if (
          element === null ||
          element.type !== AST_NODE_TYPES.CallExpression ||
          element.arguments.length !== 1 ||
          element.callee.type !== AST_NODE_TYPES.MemberExpression ||
          element.callee.computed ||
          element.callee.object.type !== AST_NODE_TYPES.Identifier ||
          !zodNamespaces.has(element.callee.object.name) ||
          element.callee.property.type !== AST_NODE_TYPES.Identifier ||
          element.callee.property.name !== "literal"
        ) {
          return null;
        }
        const value = element.arguments[0];
        if (
          value === undefined ||
          value.type !== AST_NODE_TYPES.Literal ||
          typeof value.value !== "string"
        ) {
          return null;
        }
        values.push(value);
      }
      return values;
    }

    function buildFix(
      node: TSESTree.CallExpression,
      values: readonly TSESTree.StringLiteral[],
    ): TSESLint.ReportFixFunction | undefined {
      const argument = node.arguments[0];
      if (
        argument === undefined ||
        argument.type !== AST_NODE_TYPES.ArrayExpression ||
        sourceCode.getCommentsInside(argument).length > 0
      ) {
        return undefined;
      }
      const callee = node.callee;
      if (
        callee.type !== AST_NODE_TYPES.MemberExpression ||
        callee.property.type !== AST_NODE_TYPES.Identifier
      ) {
        return undefined;
      }
      return (fixer) => [
        fixer.replaceText(callee.property, "enum"),
        fixer.replaceText(
          argument,
          `[${values.map((value) => sourceCode.getText(value)).join(", ")}]`,
        ),
      ];
    }

    return {
      ImportDeclaration(node): void {
        if (!isZodModule(node.source.value)) {
          return;
        }
        for (const specifier of node.specifiers) {
          if (
            specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier ||
            specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier ||
            (specifier.type === AST_NODE_TYPES.ImportSpecifier &&
              specifier.imported.type === AST_NODE_TYPES.Identifier &&
              specifier.imported.name === "z")
          ) {
            zodNamespaces.add(specifier.local.name);
          }
        }
      },
      CallExpression(node): void {
        const values = enumValues(node);
        if (values === null) {
          return;
        }
        const fix = buildFix(node, values);
        context.report({
          node,
          messageId: "preferEnum",
          ...(fix === undefined ? {} : { fix }),
        });
      },
    };
  },
});
