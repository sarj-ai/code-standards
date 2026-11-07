/**
 * @fileoverview enforce-file-structure — imports before body statements, and `use server` first.
 *
 * Port of the 18.x `enforce-file-structure` rule. The rule is untyped,
 * so the port covers all of it. Oxlint gives non-directive expression
 * statements `directive: null` where TS-ESTree leaves it undefined.
 */

import type { Fix, Fixer } from "@oxlint/plugins";

import { defineRule, type ESTree, type SourceCode } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { isPresent } from "../utils/is-present.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";

const NAME = "enforce-file-structure";

type Statement = ESTree.Program["body"][number];

type StatementKind = "import" | "reexport" | "body";

/** Classify declarations by what they introduce; re-exports are neutral. */
const classifyStatement = (
  statement: Statement,
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

const isStringDirective = (statement: Statement): boolean =>
  statement.type === "ExpressionStatement" &&
  statement.expression.type === "Literal" &&
  typeof statement.expression.value === "string" &&
  statement.expression.value.startsWith("use ");

const isUseServerDirective = (
  statement: Statement,
): boolean => {
  if (statement.type !== "ExpressionStatement") return false;
  const expr = statement.expression;
  if (expr.type !== "Literal") return false;
  return expr.value === "use server";
};

/** Move type imports that follow the first body statement above it, in a file without comments. */
function typeImportsFix(
  body: readonly Statement[],
  sourceCode: SourceCode,
): { readonly first: Statement; readonly fix: (fixer: Fixer) => Fix[] } | null {
  const firstBody = body.find((statement) => classifyStatement(statement) === "body" && !(statement.type === "ExpressionStatement" && isPresent(statement.directive)));
  if (firstBody === undefined || sourceCode.getAllComments().length > 0) return null;
  const misplacedTypeImports = body.filter(
    (statement) => statement.type === "ImportDeclaration" &&
      statement.importKind === "type" && statement.range[0] > firstBody.range[0],
  );
  const first = misplacedTypeImports[0];
  if (first === undefined) return null;
  return {
    first,
    fix: (fixer) => [
      fixer.insertTextBefore(firstBody, misplacedTypeImports.map((statement) => sourceCode.getText(statement)).join("\n") + "\n"),
      ...misplacedTypeImports.map((statement) => fixer.remove(statement)),
    ],
  };
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Require imports before body statements and require `use server` to be the first statement.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      importsFirst:
        "File structure violation: import statements must come before other declarations",
      useServerDirective:
        "A 'use server' directive must be the first statement in the file",
    },
  },
  createOnce(context) {
    return {
      before() {
        const file = { filename: context.filename, cwd: context.cwd };
        if (isTestFile(file) || isGeneratedFile(file, context.sourceCode.text)) return false;
        return undefined;
      },
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

        const typeImports = typeImportsFix(body, context.sourceCode);
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
                  ...(typeImports?.first === statement && { fix: typeImports.fix }),
                });
              }
              continue;
          }
        }
      },
    };
  },
});
