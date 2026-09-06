/**
 * @fileoverview no-enum — prefer literal unions or explicit constant objects for finite domains.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-enum.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

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
  limitations: ["This is an explicit style policy for regular and const enums, not a claim that every enum emits an object. Generated files and configured exclusions are preserved; migration is manual."],
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
  ],
} as const satisfies RuleDocumentation;

function matchesAnyPattern(
  filename: string,
  patterns: readonly string[],
): boolean {
  for (const pattern of patterns) {
    // Convert minimatch-ish globs to regex: ** -> .*, * -> [^/\\]*
    const regexSource = pattern
      .replace(/[.+^${}()|[\]\\]/g, "\\$&")
      .replace(/\*\*/g, "::DOUBLESTAR::")
      .replace(/\*/g, "[^/\\\\]*")
      .replace(/::DOUBLESTAR::/g, ".*");
    if (new RegExp(`^${regexSource}$`).test(filename)) {
      return true;
    }
  }
  return false;
}

export default createRule<Options, MessageIds>({
  name: "no-enum",
  documentation: NO_ENUM_DOCUMENTATION,
  meta: {
    type: "suggestion",
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

    if (isIgnoredByOption || isGeneratedFile(filename, sourceText)) {
      return {};
    }

    return {
      TSEnumDeclaration(node: TSESTree.TSEnumDeclaration): void {
        context.report({
          node,
          messageId: "noEnum",
        });
      },
    };
  },
});
