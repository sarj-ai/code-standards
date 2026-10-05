/**
 * @fileoverview no-redundant-optional-array-default — an outer array default already accepts undefined input.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-redundant-optional-array-default.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, Scope } from "@oxlint/plugins";


import { createRule, type RuleDocumentation } from "./_docs.js";
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

function importedName(specifier: ESTree.ImportSpecifier): string | null {
  return specifier.imported.type === "Identifier"
    ? specifier.imported.name
    : typeof specifier.imported.value === "string"
      ? specifier.imported.value
      : null;
}

function memberName(node: ESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === "Identifier") {
    return node.property.name;
  }
  if (
    node.computed &&
    node.property.type === "Literal" &&
    typeof node.property.value === "string"
  ) {
    return node.property.value;
  }
  return null;
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
      isTestFile(sourceOrigin(context).filename) ||
      isGeneratedFile(sourceOrigin(context).filename, sourceCode.getText())
    ) {
      return {};
    }

    const namespaces = new Set<string>();
    const arrayConstructors = new Set<string>();
    const importBindings = new Map<string, ESTree.BindingIdentifier>();

    function resolvesToTrackedImport(node: ESTree.BindingIdentifier): boolean {
      const binding = importBindings.get(node.name);
      if (binding === undefined) return false;
      let scope: Scope | null = sourceCode.getScope(node);
      while (scope !== null) {
        const variable = scope.variables.find((candidate) => candidate.name === node.name);
        if (variable !== undefined) {
          return variable.defs.some((definition) => definition.name === binding);
        }
        scope = scope.upper;
      }
      return false;
    }

    function isArraySchemaExpression(node: ESTree.Node): boolean {
      if (node.type !== "CallExpression") return false;
      const { callee } = node;
      if (callee.type === "Identifier") {
        return arrayConstructors.has(callee.name) && resolvesToTrackedImport(callee);
      }
      if (callee.type !== "MemberExpression") return false;
      const method = memberName(callee);
      if (
        method === "array" &&
        (callee.object.type === "Identifier"
          ? namespaces.has(callee.object.name) && resolvesToTrackedImport(callee.object)
          : isZodSchemaExpression(callee.object))
      ) {
        return true;
      }
      return isArraySchemaExpression(callee.object);
    }

    function isZodSchemaExpression(node: ESTree.Node): boolean {
      if (node.type !== "CallExpression") return false;
      const { callee } = node;
      if (callee.type === "Identifier") {
        return resolvesToTrackedImport(callee);
      }
      if (callee.type !== "MemberExpression") return false;
      if (
        callee.object.type === "Identifier" &&
        namespaces.has(callee.object.name) &&
        resolvesToTrackedImport(callee.object)
      ) {
        return true;
      }
      return isZodSchemaExpression(callee.object);
    }

    return {
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === "ImportNamespaceSpecifier" ||
            specifier.type === "ImportDefaultSpecifier"
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
      CallExpression(node: ESTree.CallExpression): void {
        const defaultCallee = node.callee;
        if (
          defaultCallee.type !== "MemberExpression" ||
          memberName(defaultCallee) !== "default" ||
          defaultCallee.object.type !== "CallExpression"
        ) {
          return;
        }
        const optionalCall = defaultCallee.object;
        const optionalCallee = optionalCall.callee;
        if (
          optionalCallee.type !== "MemberExpression" ||
          memberName(optionalCallee) !== "optional" ||
          optionalCall.arguments.length !== 0 ||
          !isArraySchemaExpression(optionalCallee.object) ||
          sourceCode.getCommentsInside(optionalCall).length > 0
        ) {
          return;
        }
        context.report({
          node: optionalCall,
          messageId: "redundantOptionalArrayDefault",
          fix: (fixer) =>
            fixer.replaceText(optionalCall, sourceCode.getText(optionalCallee.object)),
        });
      },
    };
  },
});
