/**
 * @fileoverview no-enum — prefer literal unions or explicit constant objects for finite domains.
 *
 * Port of the 18.x `no-enum` rule. The rule is untyped, so the port
 * covers all of it.
 */

import type { Fixer } from "@oxlint/plugins";

import { defineRule, type ESTree } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, matchesAnyPattern } from "../utils/paths.js";
import { isUnusedPrivateBinding } from "../utils/unused-private-binding.js";

const NAME = "no-enum";

interface Options {
  readonly ignoreFiles?: readonly string[];
}

export default defineRule({
  meta: {
    defaultOptions: [{}],
    type: "suggestion",
    fixable: "code",
    docs: {
      description:
        "Disallow TypeScript `enum`; use string-literal unions or `as const` objects instead.",
      url: docsUrl(NAME),
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
  createOnce(context) {
    return {
      before() {
        const ignoreFiles = (context.options[0] as Options | undefined)?.ignoreFiles ?? [];
        const filename = context.filename;
        // `ignoreFiles` adds repository-specific paths to shared generated-file detection.
        if (ignoreFiles.length > 0 && matchesAnyPattern(filename, ignoreFiles)) return false;
        if (isGeneratedFile({ filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        return undefined;
      },
      TSEnumDeclaration(node: ESTree.TSEnumDeclaration): void {
        const sourceCode = context.sourceCode;
        const members = node.body.members;
        const values = members.flatMap(({ initializer }) =>
          initializer?.type === "Literal" && typeof initializer.value === "string" ? [initializer] : []);
        const canFix = node.declare && members.length > 0 && !node.const && values.length === members.length &&
          sourceCode.getCommentsInside(node).length === 0 &&
          isUnusedPrivateBinding(sourceCode, node, node.id, context.filename);
        context.report({
          node,
          messageId: "noEnum",
          ...(canFix && { fix: (fixer: Fixer) => fixer.replaceText(node, `type ${sourceCode.getText(node.id)} = ${values.map((value) => sourceCode.getText(value)).join(" | ")};`) }),
        });
      },
    };
  },
});
