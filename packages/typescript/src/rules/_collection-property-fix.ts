/**
 * @fileoverview _collection-property-fix — preserve authored property-check behavior.
 */

import type { FixFn } from "@oxlint/plugins";

import type { ESTree, SourceCode } from "../types.js";
import { findVariable } from "../utils/static-string.js";
import { soleExportedFunction } from "./_closed-module.js";

/** Make an existing property check explicit without changing its Proxy has-trap or type narrowing. */
export function collectionPropertyFix(sourceCode: SourceCode, node: ESTree.BinaryExpression): FixFn | null {
  if (node.left.type !== "Literal" || typeof node.left.value !== "string" || node.right.type !== "Identifier") return null;
  const entry = soleExportedFunction(sourceCode);
  if (entry === null || entry.owner.params.length !== 1 || entry.body.length !== 1) return null;
  const [parameter] = entry.owner.params;
  const [returned] = entry.body;
  if (parameter?.type !== "Identifier" || parameter.optional || parameter.name !== node.right.name ||
    returned?.type !== "ReturnStatement" || returned.argument !== node ||
    entry.owner.returnType?.typeAnnotation.type !== "TSBooleanKeyword") return null;
  if ((findVariable(sourceCode.getScope(node), "Reflect")?.defs.length ?? 0) !== 0) return null;
  const replacement = `Reflect.has(${sourceCode.getText(node.right)}, ${sourceCode.getText(node.left)})`;
  return (fixer) => fixer.replaceText(node, replacement);
}
