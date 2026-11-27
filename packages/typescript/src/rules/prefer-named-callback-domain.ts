/**
 * @fileoverview prefer-named-callback-domain — prefer named literal domains in public callback contracts.
 *
 * Port of the 18.x `prefer-named-callback-domain` rule. Untyped.
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { existingTypeAliasFix } from "../utils/existing-type-alias-fix.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";

const NAME = "prefer-named-callback-domain";

export function ownsCallbackDomain(node: ESTree.TSUnionType): boolean {
  const annotation = parentOf(node);
  const parameter = annotation?.type === "TSTypeAnnotation" ? parentOf(annotation) : null;
  if (parameter === null || parameter.type === "TSParameterProperty") return false;
  const callback = parentOf(parameter);
  return callback?.type === "TSFunctionType" &&
    callback.params.some((candidate) => candidate === parameter) &&
    node.types.length >= 2 && node.types.every((part) => part.type === "TSLiteralType") &&
    exportedContract(callback);
}

function exportedContract(node: Node): boolean {
  let current: Node | null = node;
  while (current !== null) {
    if (current.type === "TSTypeAliasDeclaration" || current.type === "TSInterfaceDeclaration")
      return parentOf(current)?.type === "ExportNamedDeclaration";
    if (current.type === "Program") return false;
    current = parentOf(current);
  }
  return false;
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Name literal-union domains used by callbacks in exported contracts.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      nameCallbackDomain: "Extract this inline callback literal union to a named domain type.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    return {
      before() {
        sourceCode = context.sourceCode;
        const file = { filename: context.filename, cwd: context.cwd };
        return !(isTestFile(file) || isGeneratedFile(file, sourceCode.text));
      },
      TSUnionType(node) {
        if (!ownsCallbackDomain(node)) return;
        const name = existingTypeAliasFix(sourceCode, node);
        if (name === null) {
          context.report({ node, messageId: "nameCallbackDomain" });
          return;
        }
        context.report({
          node,
          messageId: "nameCallbackDomain",
          fix: (fixer) => fixer.replaceText(node, name + sourceCode.getText(node).replace(/[^\r\n]/gu, "")),
        });
      },
    };
  },
});
