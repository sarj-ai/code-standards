/**
 * @fileoverview require-use-form-default-values — react-hook-form forms need a stable initial value shape.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-use-form-default-values.test.ts
 */

import { ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "requireUseFormDefaultValues";
type Options = readonly [];
type ScopeVariable = NonNullable<ReturnType<typeof ASTUtils.findVariable>>;

export const REQUIRE_USE_FORM_DEFAULT_VALUES_DOCUMENTATION = {
  summary: "react-hook-form useForm call without defaultValues",
  rationale:
    "Without an explicit initial value, fields can change from uncontrolled to controlled as data arrives, reset behavior becomes ambiguous, and the form's initial shape no longer documents the values users can edit.",
  remediation:
    "Pass an object with a defaultValues property to useForm; use empty strings, nulls, or schema-appropriate values deliberately for every controlled field.",
  category: "correctness",
  limitations: [
    "Only direct calls to a scope-resolved useForm value imported from react-hook-form are checked; wrapper hooks and computed option objects are intentionally not inferred.",
  ],
  examples: [
    {
      id: "form-with-initial-values",
      title: "Give the form an explicit initial shape",
      outcome: "no-match",
      files: [{ path: "profile-form.tsx", source: "import { useForm } from 'react-hook-form';\nconst form = useForm({ defaultValues: { name: '' } });\n" }],
      focusPath: "profile-form.tsx",
      expectedCount: 0,
      public: true,
    },
    {
      id: "form-without-initial-values",
      title: "Do not leave form initialization implicit",
      outcome: "match",
      files: [{ path: "profile-form.tsx", source: "import { useForm } from 'react-hook-form';\nconst form = useForm({ mode: 'onChange' });\n" }],
      focusPath: "profile-form.tsx",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function hasDefaultValues(options: TSESTree.CallExpressionArgument | undefined): boolean {
  return (
    options?.type === "ObjectExpression" &&
    options.properties.some(
      (property) =>
        property.type === "Property" &&
        !property.computed &&
        ((property.key.type === "Identifier" && property.key.name === "defaultValues") ||
          (property.key.type === "Literal" && property.key.value === "defaultValues")),
    )
  );
}

export default createRule<Options, MessageIds>({
  name: "require-use-form-default-values",
  documentation: REQUIRE_USE_FORM_DEFAULT_VALUES_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: REQUIRE_USE_FORM_DEFAULT_VALUES_DOCUMENTATION.summary },
    schema: [],
    messages: {
      requireUseFormDefaultValues:
        "Pass explicit defaultValues to useForm so fields have a stable initial shape and reset behavior.",
    },
  },
  defaultOptions: [],
  create(context) {
    const importedHooks = new Set<ScopeVariable>();
    return {
      ImportDeclaration(node): void {
        if (node.source.value !== "react-hook-form") return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type !== "ImportSpecifier" ||
            (specifier.imported.type === "Identifier" ? specifier.imported.name : specifier.imported.value) !== "useForm"
          ) continue;
          const variable = ASTUtils.findVariable(context.sourceCode.getScope(specifier.local), specifier.local.name);
          if (variable) importedHooks.add(variable);
        }
      },
      CallExpression(node): void {
        if (node.callee.type !== "Identifier") return;
        const variable = ASTUtils.findVariable(context.sourceCode.getScope(node.callee), node.callee.name);
        const options = node.arguments[0];
        if (
          !variable ||
          !importedHooks.has(variable) ||
          (options !== undefined && options.type !== "ObjectExpression") ||
          hasDefaultValues(options)
        ) return;
        context.report({ node, messageId: "requireUseFormDefaultValues" });
      },
    } satisfies TSESLint.RuleListener;
  },
});
