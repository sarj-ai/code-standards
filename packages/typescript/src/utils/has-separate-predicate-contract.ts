/**
 * @fileoverview has-separate-predicate-contract — preserve callable domains established outside an implementation.
 *
 * Port of the 18.x `_has-separate-predicate-contract.ts` helper on tsrs: the
 * same checks over tsrs nodes, with `ts.is*` from `tsrs/ast`.
 */

import type * as TsrsAst from "tsrs/ast";

import type { NativeTypes } from "./checked-native-source.js";

/** Overloads and contextual callbacks can expose a narrower input domain than the implementation annotation. */
export function hasSeparatePredicateContract(node: TsrsAst.Node, native: NativeTypes): boolean {
  const { ast, checker } = native;
  if (ast.isFunctionExpression(node) || ast.isArrowFunction(node)) return checker.getContextualType(node) !== undefined;
  if (!ast.isFunctionDeclaration(node) && !ast.isMethodDeclaration(node)) return true;
  if (node.name !== undefined && (checker.getSymbolAtLocation(node.name)?.declarations.length ?? 0) > 1) return true;
  if (!ast.isMethodDeclaration(node)) return false;
  const owner = node.parent;
  if (ast.isObjectLiteralExpression(owner)) return checker.getContextualType(owner) !== undefined;
  return (ast.isClassDeclaration(owner) || ast.isClassExpression(owner)) && (owner.heritageClauses?.length ?? 0) > 0;
}
