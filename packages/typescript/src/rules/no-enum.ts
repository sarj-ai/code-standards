/**
 * @fileoverview Disallow TypeScript `enum` declarations. Use string-literal
 * union types (e.g. `type Status = "active" | "inactive"`) or `as const`
 * objects instead — enums generate runtime code, have unintuitive numeric
 * defaults, and don't tree-shake cleanly.
 *
 * Generated files can opt out either by living under a path matched by
 * `ignoreFiles` (default: `**\/generated/**`, `**\/*.gen.ts`, `**\/*.generated.ts`)
 * or by including a `@generated` marker comment near the top of the file.
 */

import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isGeneratedFile } from "./_paths.js";

type MessageIds = "noEnum";
type Options = readonly [
  {
    ignoreFiles?: readonly string[];
  }?,
];

const DEFAULT_IGNORE_PATTERNS: readonly RegExp[] = [
  /[\\/]generated[\\/]/,
  /[\\/]openapi-gen[\\/]/,
  /\.gen\.tsx?$/,
  /\.generated\.tsx?$/,
];

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

function hasGeneratedMarker(sourceText: string): boolean {
  // Look only in the first 1KB to keep this cheap.
  const head = sourceText.slice(0, 1024);
  return /@generated\b/.test(head);
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-enum",
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

    const isIgnoredByDefault = DEFAULT_IGNORE_PATTERNS.some((re) =>
      re.test(filename),
    );
    const isIgnoredByOption =
      ignoreFiles.length > 0 && matchesAnyPattern(filename, ignoreFiles);
    const isGenerated = hasGeneratedMarker(sourceText) || isGeneratedFile(filename, sourceText);

    if (isIgnoredByDefault || isIgnoredByOption || isGenerated) {
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
