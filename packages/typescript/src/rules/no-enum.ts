/**
 * @fileoverview no-enum — a TypeScript `enum` emits runtime code, defaults to numbers, and does not tree-shake.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-enum.test.ts
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/no-enum.md
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "noEnum";
type Options = readonly [
  {
    ignoreFiles?: readonly string[];
  }?,
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

export default createRule<Options, MessageIds>({
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

    // Generated code opts out through the SHARED `isGeneratedFile` predicate.
    // This rule used to carry its own narrower copy of all three of its signals
    // — a four-pattern path list and a 1KB `@generated` sniff — and every one of
    // them could be neutered with the suite green, because the shared predicate
    // already answered true for the same files. `ignoreFiles` stays: it names
    // paths a repo knows about and the shared predicate cannot.
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
