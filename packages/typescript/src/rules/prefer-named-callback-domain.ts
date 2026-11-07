/**
 * @fileoverview prefer-named-callback-domain — prefer named literal domains in public callback contracts.
 *
 * Port of the 18.x `prefer-named-callback-domain` rule. Untyped. Oxlint
 * sets an absent parameter `typeAnnotation` to `null` where TS-ESTree leaves it
 * `undefined`; both mean "no annotation" here.
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { existingTypeAliasFix } from "../utils/existing-type-alias-fix.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";

const NAME = "prefer-named-callback-domain";

function isLiteralUnion(node: ESTree.TSType): boolean {
  return (
    node.type === "TSUnionType" && node.types.length >= 2 && node.types.every((part) => part.type === "TSLiteralType")
  );
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
      TSFunctionType(node) {
        if (!exportedContract(node)) return;
        for (const parameter of node.params) {
          const typeAnnotation = (parameter as { typeAnnotation?: ESTree.TSTypeAnnotation | null }).typeAnnotation;
          if (parameter.type === "TSParameterProperty" || typeAnnotation == null) continue;
          const annotation = typeAnnotation.typeAnnotation;
          if (!isLiteralUnion(annotation)) continue;
          const name = existingTypeAliasFix(sourceCode, annotation);
          if (name === null) {
            context.report({ node: annotation, messageId: "nameCallbackDomain" });
            continue;
          }
          context.report({
            node: annotation,
            messageId: "nameCallbackDomain",
            fix: (fixer) =>
              fixer.replaceText(annotation, name + sourceCode.getText(annotation).replace(/[^\r\n]/gu, "")),
          });
        }
      },
    };
  },
});
