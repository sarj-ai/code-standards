/**
 * @fileoverview no-explicit-type-predicate — narrow owned unions without handwritten type promises.
 *
 * Port of the 18.x `no-explicit-type-predicate` rule. The rule is untyped, so the port
 * covers all of it.
 */

import { defineRule, type ESTree } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";

const NAME = "no-explicit-type-predicate";

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Use compiler-checked narrowing instead of handwritten type predicates.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: { noExplicitTypePredicate: "Replace this handwritten type predicate with a direct discriminator check or compiler-inferred narrowing. Parse unknown data with a schema and consume the validated result; preserve required external callable contracts." },
  },
  createOnce(context) {
    return {
      before() {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        return undefined;
      },
      TSTypePredicate(node: ESTree.TSTypePredicate): void {
        if (node.typeAnnotation !== null) context.report({ node, messageId: "noExplicitTypePredicate" });
      },
    };
  },
});
