/**
 * @fileoverview prefer-monotonic-for-elapsed-time — Measure elapsed time with a monotonic clock rather than wall-clock timestamps.
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { nativeRuntimeUnchanged } from "../utils/native-runtime-unchanged.js";
import { isGeneratedFile } from "../utils/paths.js";
import { stableValueBinding, typeOnlyReference } from "../utils/stable-value-binding.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";

const NAME = "prefer-monotonic-for-elapsed-time";

function wallClock(input: Node, source: SourceCode): boolean {
  const node = unwrapExpression(input);
  if (node.type !== "CallExpression" || node.optional || node.arguments.length !== 0) return false;
  const callee = unwrapExpression(node.callee);
  if (callee.type !== "MemberExpression" || callee.optional || getPropertyName(callee) !== "now") return false;
  const owner = unwrapExpression(callee.object);
  return owner.type === "Identifier" && owner.name === "Date" &&
    !findVariable(source.getScope(owner), owner.name)?.defs.length;
}

export default defineRule({
  meta: {
    type: "problem",
    docs: { description: 'Measure elapsed time with a monotonic clock rather than wall-clock timestamps.', url: docsUrl(NAME) },
    schema: [],
    messages: { preferMonotonicForElapsedTime: 'Measure elapsed time with a monotonic clock rather than wall-clock timestamps.' },
  },
  createOnce(context) {
    return {
      before() {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        return undefined;
      },
      VariableDeclarator(node: ESTree.VariableDeclarator) {
        const declaration = parentOf(node);
        if (node.id.type !== "Identifier" || node.init === null || declaration?.type !== "VariableDeclaration" ||
          declaration.kind !== "const" || parentOf(declaration)?.type === "ExportNamedDeclaration" ||
          !wallClock(node.init, context.sourceCode)) return;
        const binding = findVariable(context.sourceCode.getScope(node.id), node.id.name);
        if (binding === null || binding.defs.length !== 1 || !stableValueBinding(binding)) return;
        const reads = binding.references.filter(reference => reference.isRead() && !typeOnlyReference(reference));
        if (reads.length === 0 || !reads.every(reference => {
          const value = outerExpression(reference.identifier);
          const parent = parentOf(value);
          return parent?.type === "BinaryExpression" && parent.operator === "-" && parent.right === value &&
            wallClock(parent.left, context.sourceCode);
        }) || !nativeRuntimeUnchanged(context.sourceCode, "Date")) return;
        context.report({ node: node.init, messageId: "preferMonotonicForElapsedTime" });
      },
    };
  },
});
