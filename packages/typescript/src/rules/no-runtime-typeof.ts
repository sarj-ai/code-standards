/**
 * @fileoverview no-runtime-typeof — prefer Zod boundary schemas or discriminated unions over runtime typeof checks.
 *
 * Port of the 18.x `no-runtime-typeof` rule. Same algorithm; the
 * generated-file gate runs in `before()`.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-runtime-typeof.test.ts
 */

import type { VisitorWithHooks } from "@oxlint/plugins";

import { defineRule } from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { hasLocalValueBinding } from "../utils/has-local-value-binding.js";
import { isGeneratedFile } from "../utils/paths.js";

const NAME = "no-runtime-typeof";
const EQUALITY_OPERATORS: ReadonlySet<string> = new Set(["===", "!==", "==", "!="]);

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Prefer Zod boundary schemas or discriminated unions over runtime typeof checks.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      runtimeTypeof:
        "Replace runtime typeof with a specific Zod schema at the boundary or an explicit discriminated union. Explain required raw-parser, generic-utility or framework primitive checks in a local suppression.",
    },
  },
  createOnce(context): VisitorWithHooks {
    return {
      before(): boolean | void {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
      },
      UnaryExpression(node): void {
        if (node.operator !== "typeof") return;
        const probe = outerExpression(node);
        const parent = parentOf(probe);
        const argument = unwrapExpression(node.argument);
        if (argument.type === "Identifier" && parent?.type === "BinaryExpression" &&
          EQUALITY_OPERATORS.has(parent.operator)) {
          const other = unwrapExpression(parent.left === probe ? parent.right : parent.left);
          if (other.type === "Literal" && other.value === "undefined" &&
            !hasLocalValueBinding(context.sourceCode, argument, context.languageOptions.sourceType)) return;
        }
        context.report({ node, messageId: "runtimeTypeof" });
      },
    };
  },
});
