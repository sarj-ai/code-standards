/**
 * @fileoverview no-conditional-empty-object-spread — build conditional properties explicitly instead of spreading an empty-object branch.
 *
 * Port of the 18.x `no-conditional-empty-object-spread` rule. Same
 * algorithm; the generated-file gate runs in `before()`.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-conditional-empty-object-spread.test.ts
 */

import type { VisitorWithHooks } from "@oxlint/plugins";

import { defineRule, type Node } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";

const NAME = "no-conditional-empty-object-spread";

function isEmptyObject(node: Node): boolean {
  return node.type === "ObjectExpression" && node.properties.length === 0;
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Build conditional properties explicitly instead of spreading an empty-object branch.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      avoid:
        "Build conditional fields explicitly instead of spreading an empty object branch. Preserve omission and evaluation order.",
    },
  },
  createOnce(context): VisitorWithHooks {
    return {
      before(): boolean | void {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
      },
      SpreadElement(node): void {
        const conditional = node.argument;
        if (parentOf(node)?.type !== "ObjectExpression" || conditional.type !== "ConditionalExpression") return;
        const emptyConsequent = isEmptyObject(conditional.consequent);
        if (!emptyConsequent && !isEmptyObject(conditional.alternate)) return;
        const { sourceCode } = context;
        const populated = emptyConsequent ? conditional.alternate : conditional.consequent;
        const canFix = populated.type === "ObjectExpression" && populated.properties.length > 0 &&
          sourceCode.getCommentsInside(conditional).length === 0;
        context.report({
          node,
          messageId: "avoid",
          ...(canFix && {
            fix: (fixer) => fixer.replaceText(conditional,
              `${emptyConsequent ? "!" : "!!"}(${sourceCode.getText(conditional.test)}) && (${sourceCode.getText(populated)})`),
          }),
        });
      },
    };
  },
});
