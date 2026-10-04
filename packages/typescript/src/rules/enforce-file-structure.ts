/**
 * @fileoverview enforce-file-structure — imports come first, then step-down order; a `use server` directive that is not the first statement is inert.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/enforce-file-structure.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree } from "@oxlint/plugins";


import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "importsFirst" | "useServerDirective";
type Options = readonly [];

export const ENFORCE_FILE_STRUCTURE_DOCUMENTATION = {
  summary: "Require imports before body statements and require `use server` to be the first statement.",
  rationale:
    "Interleaved imports obscure module dependencies, while a displaced `use server` string is not an active directive.",
  remediation:
    "Move `use server` to the first statement when present, then place imports before declarations and executable statements.",
  category: "correctness",
  limitations: [
    "The rule skips tests and generated files, treats re-exports as neutral, and does not order body declarations.",
  ],
  examples: [
    {
      id: "imports-first",
      title: "Imports precede module declarations",
      outcome: "no-match",
      files: [{ path: "src/component.ts", source: "import { z } from 'zod';\nexport const schema = z.string();" }],
      focusPath: "src/component.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "import-after-declaration",
      title: "An import follows a module declaration",
      outcome: "match",
      files: [{ path: "src/component.ts", source: "export const x = 1;\nimport { z } from 'zod';" }],
      focusPath: "src/component.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

type StatementKind = "import" | "reexport" | "body";

/** Classify declarations by what they introduce; re-exports are neutral. */
const classifyStatement = (
  statement: ESTree.Statement,
): StatementKind => {
  switch (statement.type) {
    case "ImportDeclaration":
      return "import";
    case "ExportAllDeclaration":
      return "reexport";
    case "ExportNamedDeclaration":
      // Only `export <declaration>` introduces a body statement.
      return statement.declaration === null ? "reexport" : "body";
    default:
      return "body";
  }
};

const isStringDirective = (statement: ESTree.Statement): boolean =>
  statement.type === "ExpressionStatement" &&
  statement.expression.type === "Literal" &&
  typeof statement.expression.value === "string" &&
  statement.expression.value.startsWith("use ");

const isUseServerDirective = (
  statement: ESTree.Statement,
): boolean => {
  if (statement.type !== "ExpressionStatement") return false;
  const expr = statement.expression;
  if (expr.type !== "Literal") return false;
  return expr.value === "use server";
};

export default createRule<Options, MessageIds>({
  name: "enforce-file-structure",
  documentation: ENFORCE_FILE_STRUCTURE_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description: "Require imports before body statements and require `use server` to be the first statement.",
    },
    schema: [],
    messages: {
      importsFirst:
        "File structure violation: import statements must come before other declarations",
      useServerDirective:
        "A 'use server' directive must be the first statement in the file",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(sourceOrigin(context).filename) || isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)) {
      return {};
    }

    return {
      Program(node: ESTree.Program): void {
        const body = node.body;

        const misplacedUseServer = body.find(
          (statement, index) => index > 0 && isUseServerDirective(statement),
        );
        if (misplacedUseServer !== undefined) {
          context.report({
            node: misplacedUseServer,
            messageId: "useServerDirective",
          });
        }

        let seenBody = false;
        let inMisplacedRun = false;

        for (const statement of body) {
          if (isStringDirective(statement)) continue;

          switch (classifyStatement(statement)) {
            case "reexport":
              continue;
            case "body":
              seenBody = true;
              inMisplacedRun = false;
              continue;
            case "import":
              if (seenBody && !inMisplacedRun) {
                inMisplacedRun = true;
                context.report({
                  node: statement,
                  messageId: "importsFirst",
                });
              }
              continue;
          }
        }
      },
    };
  },
});
