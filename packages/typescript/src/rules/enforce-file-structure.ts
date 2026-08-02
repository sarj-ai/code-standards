/**
 * @fileoverview enforce-file-structure — imports come first, then step-down order; a `use server` directive that is not the first statement is inert.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/enforce-file-structure.test.ts
 */

import { type TSESTree, AST_NODE_TYPES } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "importsFirst" | "useServerDirective";
type Options = readonly [];

type StatementKind = "import" | "reexport" | "body";

/**
 * Classify a top-level statement by WHAT it introduces, not by the presence of
 * the `export` keyword.
 *
 * - `import ...`                        → "import"
 * - `export ... from`, `export * from`, → "reexport"
 *   `export { a, b }` (local names)
 * - everything else, INCLUDING every    → "body"
 *   exported declaration/function
 *
 * Bucketing exported statements as "body" is the whole point: an exported
 * `interface`/`type`/`enum`/`class`/value-`const` is a declaration and an
 * exported `function` (or `export default <fn>`) is a function — both live in
 * the same body as their non-exported equivalents. That lets the dominant
 * step-down layout (public API first, private helpers below) pass instead of
 * forcing every `export`-prefixed statement into a terminal "exports" section.
 *
 * Re-exports are their own neutral group: a generated `_namespaces` barrel that
 * interleaves `import * as X` / `export { X }` must not be flagged, so
 * re-exports never trigger and are allowed anywhere in the file.
 */
const classifyStatement = (
  statement: TSESTree.ProgramStatement,
): StatementKind => {
  switch (statement.type) {
    case AST_NODE_TYPES.ImportDeclaration:
      return "import";
    case AST_NODE_TYPES.ExportAllDeclaration:
      return "reexport";
    case AST_NODE_TYPES.ExportNamedDeclaration:
      // `export { a } from './x'` / `export { a, b }` re-export names without
      // declaring anything; only `export <decl>` introduces a body statement.
      return statement.declaration === null ? "reexport" : "body";
    default:
      return "body";
  }
};

const isStringDirective = (statement: TSESTree.ProgramStatement): boolean =>
  statement.type === AST_NODE_TYPES.ExpressionStatement &&
  statement.expression.type === AST_NODE_TYPES.Literal &&
  typeof statement.expression.value === "string" &&
  statement.expression.value.startsWith("use ");

const isUseServerDirective = (
  statement: TSESTree.ProgramStatement,
): boolean => {
  if (statement.type !== AST_NODE_TYPES.ExpressionStatement) return false;
  const expr = statement.expression;
  if (expr.type !== AST_NODE_TYPES.Literal) return false;
  return expr.value === "use server";
};

export default createRule<Options, MessageIds>({
  name: "enforce-file-structure",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Require `import` statements to come first, then allow step-down ordering (public API first, private helpers below) for the rest of the file. Exported statements are classified by WHAT they export — an exported interface is a declaration, an exported function is a function — so a public exported function followed by a private helper, or an exported interface among declarations, is allowed. Re-exports (`export { … } from`, `export *`, `export { … }`) are a neutral group, so generated namespace barrels pass. When a module contains a `use server` directive, it must be the first statement in the file.",
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
    if (isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }

    return {
      Program(node: TSESTree.Program): void {
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
