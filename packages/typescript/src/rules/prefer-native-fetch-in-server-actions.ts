/**
 * @fileoverview prefer-native-fetch-in-server-actions — server action modules call native fetch instead of ky.
 *
 * Port of the 18.x `prefer-native-fetch-in-server-actions` rule. The rule
 * is untyped, so the port covers all of it.
 */

import { defineRule, type ESTree } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";

const NAME = "prefer-native-fetch-in-server-actions";

const KY_MODULE = /^ky(?:\/.*)?$/u;

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Server action modules should call native fetch instead of importing ky.",
      url: docsUrl(NAME),
    },
    schema: [],
    defaultOptions: [],
    messages: {
      preferNativeFetchInServerActions:
        "This server action module imports ky. Call native fetch with an explicit AbortSignal timeout instead.",
    },
  },
  createOnce(context) {
    return {
      before() {
        if (!hasUseServerDirective(context.sourceCode.ast)) return false;
        return undefined;
      },
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (KY_MODULE.test(node.source.value) && !isTypeOnly(node)) {
          context.report({ node, messageId: "preferNativeFetchInServerActions" });
        }
      },
    };
  },
});


function hasUseServerDirective(program: ESTree.Program): boolean {
  for (const statement of program.body) {
    if (statement.type !== "ExpressionStatement" || typeof statement.directive !== "string") return false;
    if (statement.directive === "use server") return true;
  }
  return false;
}

function isTypeOnly(node: ESTree.ImportDeclaration): boolean {
  return (
    node.importKind === "type" ||
    (node.specifiers.length > 0 &&
      node.specifiers.every(
        (specifier) => specifier.type === "ImportSpecifier" && specifier.importKind === "type",
      ))
  );
}
