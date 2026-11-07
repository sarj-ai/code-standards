/** @fileoverview _empty-assertion-fix — reuse an authored no-op never guard. */

import type { FixFn } from "@oxlint/plugins";

import type { ESTree, Node, SourceCode } from "../types.js";
import { findVariable } from "../utils/static-string.js";
import { plainFunctionBody } from "./_closed-module.js";

type OrdinaryFunction = ESTree.Function;

/** Reuse an authored no-op never guard without changing unexpected-value behavior. */
export function emptyAssertionFix(sourceCode: SourceCode, node: ESTree.SwitchStatement, defaultCase: ESTree.SwitchCase): FixFn | null {
  if (sourceCode.ast.body.length !== 2 || sourceCode.getAllComments().length > 0) return null;
  const [helper, statement] = sourceCode.ast.body;
  if (
    helper?.type !== "FunctionDeclaration" || !isEmptyAssertion(helper) ||
    statement?.type !== "ExportNamedDeclaration" || statement.declaration?.type !== "FunctionDeclaration"
  ) {
    return null;
  }
  const owner = statement.declaration;
  if (!isLiteralDispatch(owner, node, defaultCase)) return null;
  const parameter = owner.params[0];
  if (parameter?.type !== "Identifier" || helper.id === null) return null;
  const helperName = helper.id.name;
  const binding = findVariable(sourceCode.getScope(defaultCase), helperName);
  if (binding?.defs.length !== 1 || binding.defs[0]?.node !== helper) return null;
  const first = sourceCode.getFirstToken(defaultCase);
  const colon = first === null ? null : sourceCode.getTokenAfter(first);
  if (colon?.value !== ":") return null;
  return (fixer) => fixer.insertTextAfter(colon, ` ${helperName}(${parameter.name});`);
}

function isEmptyAssertion(node: OrdinaryFunction): boolean {
  const parameter = node.params[0];
  return plainFunctionBody(node)?.length === 0 && node.id?.name === "assertNever" && node.params.length === 1 &&
    parameter?.type === "Identifier" && !parameter.optional &&
    parameter.typeAnnotation?.typeAnnotation.type === "TSNeverKeyword" &&
    node.returnType?.typeAnnotation.type === "TSVoidKeyword";
}

function isLiteralDispatch(owner: OrdinaryFunction, node: ESTree.SwitchStatement, defaultCase: ESTree.SwitchCase): boolean {
  const parameter = owner.params[0];
  const domain = literalDomain(parameter);
  const body = plainFunctionBody(owner) ?? [];
  if (
    owner.params.length !== 1 || parameter?.type !== "Identifier" || parameter.optional ||
    domain === null || body.length !== 2 || body[0] !== node || node.discriminant.type !== "Identifier" ||
    node.discriminant.name !== parameter.name || node.cases.at(-1) !== defaultCase || !isEmptyDefault(defaultCase)
  ) {
    return false;
  }
  if (!isPrimitiveReturn(body[1], owner.returnType)) return false;
  const handled = new Set<string>();
  for (const branch of node.cases.slice(0, -1)) {
    const value = branch.test?.type === "Literal" ? (branch.test as { value: unknown }).value : undefined;
    if (
      typeof value !== "string" || handled.has(value) || !domain.has(value) || branch.consequent.length !== 1 ||
      !isPrimitiveReturn(branch.consequent[0], owner.returnType)
    ) {
      return false;
    }
    handled.add(value);
  }
  return handled.size === domain.size;
}

function literalDomain(node: Node | undefined): Set<string> | null {
  if (node?.type !== "Identifier") return null;
  const annotation = node.typeAnnotation?.typeAnnotation;
  if (annotation?.type !== "TSUnionType") return null;
  const values = new Set<string>();
  for (const type of annotation.types) {
    const value = type.type === "TSLiteralType" && type.literal.type === "Literal" ? (type.literal as { value: unknown }).value : undefined;
    if (typeof value !== "string" || values.has(value)) return null;
    values.add(value);
  }
  return values.size >= 2 ? values : null;
}

function isEmptyDefault(node: ESTree.SwitchCase): boolean {
  const only = node.consequent[0];
  return node.test === null &&
    (node.consequent.length === 0 || (node.consequent.length === 1 && only?.type === "BreakStatement" && only.label === null));
}

function isPrimitiveReturn(node: Node | undefined, annotation: ESTree.TSTypeAnnotation | null | undefined): boolean {
  if (node?.type !== "ReturnStatement" || node.argument?.type !== "Literal") return false;
  const value = (node.argument as { value: unknown }).value;
  switch (annotation?.typeAnnotation.type) {
    case "TSNumberKeyword":
      return typeof value === "number" && Number.isFinite(value);
    case "TSStringKeyword":
      return typeof value === "string";
    case "TSBooleanKeyword":
      return typeof value === "boolean";
    default:
      return false;
  }
}
