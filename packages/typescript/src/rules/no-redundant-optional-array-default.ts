/**
 * @fileoverview no-redundant-optional-array-default — an outer array default already accepts undefined input.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-redundant-optional-array-default.test.ts
 */

import { ASTUtils,
  AST_NODE_TYPES,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { unwrapExpression } from "./_unwrap-expression.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { isZodModule } from "./_zod.js";

type MessageIds = "redundantOptionalArrayDefault";
type Options = readonly [];

export const NO_REDUNDANT_OPTIONAL_ARRAY_DEFAULT_DOCUMENTATION = {
  summary: "Remove `.optional()` immediately inside a Zod array default.",
  rationale: "An outer default already accepts undefined array input, so the inner optional wrapper adds no state or fallback behavior.",
  remediation: "Keep the array default and remove the immediately preceding `.optional()` call.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Only syntactically local Zod array chains with adjacent `.optional().default(...)` calls are checked.",
    "String, scalar, tuple, set, record, aliased, composed, and dynamically constructed schemas are excluded.",
    "The reversed `.default(...).optional()` order is preserved because its outer optional can return undefined instead of the default.",
    "Calls containing comments are excluded so the fix never deletes authored context.",
    "Test and generated files are excluded.",
  ],
  examples: [
    {
      id: "array-default",
      title: "Default an omitted list directly",
      outcome: "no-match",
      files: [
        {
          path: "src/schema.ts",
          source: 'import { z } from "zod"; const Items = z.array(z.string()).default([]);',
        },
      ],
      focusPath: "src/schema.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "optional-array-default",
      title: "Do not wrap a defaulted list in a redundant optional",
      outcome: "match",
      files: [
        {
          path: "src/schema.ts",
          source: 'import { z } from "zod"; const Items = z.array(z.string()).optional().default([]);',
        },
      ],
      fixedFiles: [
        {
          path: "src/schema.ts",
          source: 'import { z } from "zod"; const Items = z.array(z.string()).default([]);',
        },
      ],
      focusPath: "src/schema.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function importedName(specifier: TSESTree.ImportSpecifier): string | null {
  return specifier.imported.type === AST_NODE_TYPES.Identifier
    ? specifier.imported.name
    : typeof specifier.imported.value === "string"
      ? specifier.imported.value
      : null;
}

export default createRule<Options, MessageIds>({
  name: "no-redundant-optional-array-default",
  documentation: NO_REDUNDANT_OPTIONAL_ARRAY_DEFAULT_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description: "Remove `.optional()` immediately inside a Zod array default.",
    },
    fixable: "code",
    schema: [],
    messages: {
      redundantOptionalArrayDefault:
        "This array's outer `.default()` already handles undefined input. Remove the redundant inner `.optional()`.",
    },
  },
  defaultOptions: [],
  create(context) {
    const sourceCode = context.sourceCode;
    if (
      isTestFile(context.filename) ||
      isGeneratedFile(context.filename, sourceCode.getText())
    ) {
      return {};
    }

    const namespaces = new Set<string>();
    const arrayConstructors = new Set<string>();
    const importBindings = new Map<string, TSESTree.Identifier>();

    function resolvesToTrackedImport(node: TSESTree.Identifier): boolean {
      const binding = importBindings.get(node.name);
      if (binding === undefined) return false;
      let scope: TSESLint.Scope.Scope | null = sourceCode.getScope(node);
      while (scope !== null) {
        const variable = scope.variables.find((candidate) => candidate.name === node.name);
        if (variable !== undefined) {
          return variable.defs.some((definition) => definition.name === binding);
        }
        scope = scope.upper;
      }
      return false;
    }

    function isArraySchemaExpression(node: TSESTree.Node): boolean {
      if (node.type !== AST_NODE_TYPES.CallExpression) return false;
      const { callee } = node;
      const calleeReceiver = callee.type === AST_NODE_TYPES.MemberExpression ? unwrapExpression(callee.object) : callee;
      if (callee.type === AST_NODE_TYPES.Identifier) {
        return arrayConstructors.has(callee.name) && resolvesToTrackedImport(callee);
      }
      if (callee.type !== AST_NODE_TYPES.MemberExpression) return false;
      const method = ASTUtils.getPropertyName(callee);
      if (
        method === "array" &&
        (calleeReceiver.type === AST_NODE_TYPES.Identifier
          ? namespaces.has(calleeReceiver.name) && resolvesToTrackedImport(calleeReceiver)
          : isZodSchemaExpression(calleeReceiver))
      ) {
        return true;
      }
      return isArraySchemaExpression(calleeReceiver);
    }

    function isZodSchemaExpression(node: TSESTree.Node): boolean {
      if (node.type !== AST_NODE_TYPES.CallExpression) return false;
      const { callee } = node;
      const calleeReceiver = callee.type === AST_NODE_TYPES.MemberExpression ? unwrapExpression(callee.object) : callee;
      if (callee.type === AST_NODE_TYPES.Identifier) {
        return resolvesToTrackedImport(callee);
      }
      if (callee.type !== AST_NODE_TYPES.MemberExpression) return false;
      if (
        calleeReceiver.type === AST_NODE_TYPES.Identifier &&
        namespaces.has(calleeReceiver.name) &&
        resolvesToTrackedImport(calleeReceiver)
      ) {
        return true;
      }
      return isZodSchemaExpression(calleeReceiver);
    }

    return {
      ImportDeclaration(node: TSESTree.ImportDeclaration): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier ||
            specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier
          ) {
            namespaces.add(specifier.local.name);
            importBindings.set(specifier.local.name, specifier.local);
            continue;
          }
          const imported = importedName(specifier);
          if (imported === "z") {
            namespaces.add(specifier.local.name);
            importBindings.set(specifier.local.name, specifier.local);
          } else if (imported === "array") {
            arrayConstructors.add(specifier.local.name);
            importBindings.set(specifier.local.name, specifier.local);
          } else if (imported !== null) {
            importBindings.set(specifier.local.name, specifier.local);
          }
        }
      },
      CallExpression(node: TSESTree.CallExpression): void {
        const defaultCallee = node.callee;
        const defaultCalleeReceiver = defaultCallee.type === AST_NODE_TYPES.MemberExpression ? unwrapExpression(defaultCallee.object) : defaultCallee;
        if (
          defaultCallee.type !== AST_NODE_TYPES.MemberExpression ||
          ASTUtils.getPropertyName(defaultCallee) !== "default" ||
          defaultCalleeReceiver.type !== AST_NODE_TYPES.CallExpression
        ) {
          return;
        }
        const optionalCall = defaultCalleeReceiver;
        const optionalCallee = optionalCall.callee;
        const optionalCalleeReceiver = optionalCallee.type === AST_NODE_TYPES.MemberExpression ? unwrapExpression(optionalCallee.object) : optionalCallee;
        if (
          optionalCallee.type !== AST_NODE_TYPES.MemberExpression ||
          ASTUtils.getPropertyName(optionalCallee) !== "optional" ||
          optionalCall.arguments.length !== 0 ||
          !isArraySchemaExpression(optionalCalleeReceiver) ||
          sourceCode.getCommentsInside(optionalCall).length > 0
        ) {
          return;
        }
        context.report({
          node: optionalCall,
          messageId: "redundantOptionalArrayDefault",
          fix: (fixer) =>
            fixer.replaceText(optionalCall, sourceCode.getText(optionalCalleeReceiver)),
        });
      },
    };
  },
});
