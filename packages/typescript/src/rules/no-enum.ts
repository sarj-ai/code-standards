/**
 * @fileoverview no-enum — prefer literal unions or explicit constant objects for finite domains.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-enum.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, matchesAnyPattern } from "./_paths.js";
import { isUnusedPrivateBinding } from "./_unused-private-binding.js";

type MessageIds = "noEnum";
type Options = readonly [
  {
    ignoreFiles?: readonly string[];
  }?,
];

export const NO_ENUM_DOCUMENTATION = {
  summary: "Disallow TypeScript `enum`; use string-literal unions or `as const` objects instead.",
  rationale:
    "Literal unions keep type-only domains explicit, while constant objects make runtime values deliberate. This policy also avoids compiler-dependent const-enum inlining contracts.",
  remediation:
    "Use a literal union or an `as const` object after checking runtime member access, numeric reverse mappings, serialized values, and public consumers.",
  category: "maintainability",
  autofix: "safe",
  limitations: ["This is an explicit style policy for regular and const enums, not a claim that every enum emits an object. Generated files and configured exclusions are preserved. Automatic conversion is limited to unused private ambient enums with literal string values; runtime enums and observed nominal contracts remain manual."],
  references: ["https://www.typescriptlang.org/docs/handbook/enums.html"],
  examples: [
    {
      id: "string-literal-union",
      title: "A string-literal union has no emitted runtime enum",
      outcome: "no-match",
      files: [{ path: "src/status.ts", source: 'type Status = "active" | "inactive";' }],
      focusPath: "src/status.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "numeric-enum",
      title: "A numeric enum emits a mutable runtime object",
      outcome: "match",
      files: [{ path: "src/status.ts", source: "enum Status { Active, Inactive }" }],
      focusPath: "src/status.ts",
      expectedCount: 1,
      public: true,
    },
    { id: "authored-after-comment", scenarioId: "native-header-boundary", title: "Keep executable authored code in scope", outcome: "match", files: [{ path: "src/status.ts", source: "// ordinary header\u2028const marker=\"auto-generated file\"; enum Mode {Start} console.log(Mode.Start, marker);" }], focusPath: "src/status.ts", expectedCount: 1, public: true },
    { id: "generated-header", scenarioId: "native-header-boundary", title: "Respect a native generated banner", outcome: "no-match", files: [{ path: "src/status.ts", source: "// auto-generated file\u2028const marker=\"auto-generated file\"; enum Mode {Start} console.log(Mode.Start, marker);" }], focusPath: "src/status.ts", expectedCount: 0, public: true },
    {
      id: "safe-autofix",
      title: "Replace an unused ambient string enum with an erased union",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; declare enum Status { Active = 'active', Inactive = 'inactive' }" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; type Status = 'active' | 'inactive';" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;


export default createRule<Options, MessageIds>({
  name: "no-enum",
  documentation: NO_ENUM_DOCUMENTATION,
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description:
        "Disallow TypeScript `enum`; use string-literal unions or `as const` objects instead.",
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          ignoreFiles: {
            type: "array",
            description:
              "Additional generated-file globs to ignore; shared generated paths and header markers are always ignored.",
            items: { type: "string" },
          },
        },
      },
    ],
    messages: {
      noEnum:
        'Enums are discouraged. Use a string-literal union (e.g. `type Status = "active" | "inactive"`) or an `as const` object instead.',
    },
  },
  defaultOptions: [{}],
  create(context, [optionsArg]) {
    const options = optionsArg ?? {};
    const ignoreFiles = options.ignoreFiles ?? [];
    const filename = context.filename;
    const sourceText = context.sourceCode.getText();

    // `ignoreFiles` adds repository-specific paths to shared generated-file detection.
    const isIgnoredByOption =
      ignoreFiles.length > 0 && matchesAnyPattern(filename, ignoreFiles);

    if (isIgnoredByOption || isGeneratedFile(context, sourceText)) {
      return {};
    }

    return {
      TSEnumDeclaration(node: TSESTree.TSEnumDeclaration): void {
        const members = node.body.members;
        const values = members.map((member) => member.initializer);
        const canFix = node.declare && members.length > 0 && !node.const &&
          values.every((value) => value?.type === AST_NODE_TYPES.Literal && typeof value.value === "string") &&
          context.sourceCode.getCommentsInside(node).length === 0 &&
          isUnusedPrivateBinding(context.sourceCode, node, node.id, context.filename);
        context.report({
          node,
          messageId: "noEnum",
          fix: canFix ? (fixer) => fixer.replaceText(node, `type ${context.sourceCode.getText(node.id)} = ${values.map((value) => value === undefined ? "" : context.sourceCode.getText(value)).join(" | ")};`) : null,
        });
      },
    };
  },
});
