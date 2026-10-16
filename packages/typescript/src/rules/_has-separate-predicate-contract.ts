/** @fileoverview _has-separate-predicate-contract — preserve callable domains established outside an implementation. */
import ts from "typescript";

/** Overloads and contextual callbacks can expose a narrower input domain than the implementation annotation. */
export function hasSeparatePredicateContract(node: ts.Node, checker: ts.TypeChecker): boolean {
  if (ts.isFunctionExpression(node) || ts.isArrowFunction(node)) return checker.getContextualType(node) !== undefined;
  if (!ts.isFunctionDeclaration(node) && !ts.isMethodDeclaration(node)) return true;
  if (node.name !== undefined && (checker.getSymbolAtLocation(node.name)?.getDeclarations()?.length ?? 0) > 1) return true;
  if (!ts.isMethodDeclaration(node)) return false;
  const owner = node.parent;
  if (ts.isObjectLiteralExpression(owner)) return checker.getContextualType(owner) !== undefined;
  return (ts.isClassDeclaration(owner) || ts.isClassExpression(owner)) && (owner.heritageClauses?.length ?? 0) > 0;
}
