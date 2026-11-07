/**
 * @fileoverview _existing-string-constant-fix — reuse an authored primitive string constant.
 *
 * The plan cache is keyed by `sourceCode.ast`: Oxlint reuses one `SourceCode` object for every file.
 */

import type { FixFn } from "@oxlint/plugins";

import type { ESTree, Node, SourceCode, TsVariable } from "../types.js";
import { tsVariable } from "../types.js";
import { isPresent } from "../utils/is-present.js";
import { findVariable } from "../utils/static-string.js";
import { plainFunctionBody, soleConstDeclarator } from "./_closed-module.js";

interface StringConstantPlan {
  readonly value: string;
  readonly name: string;
  readonly binding: TsVariable;
  readonly literals: ReadonlySet<Node>;
}

const PLANS = new WeakMap<object, StringConstantPlan | null>();

/** Reuse an existing primitive constant in a complete declaration-only module. */
export function existingStringConstantFix(
  sourceCode: Readonly<SourceCode>,
  node: Node,
  value: string,
): FixFn | null {
  if (node.type !== "Literal" || node.value !== value) return null;
  const plan = stringConstantPlan(sourceCode);
  if (
    plan === null ||
    plan.value !== value ||
    !plan.literals.has(node) ||
    findVariable(sourceCode.getScope(node), plan.binding.name) !== plan.binding
  )
    return null;
  return (fixer) => fixer.replaceText(node, plan.name);
}

function stringConstantPlan(sourceCode: Readonly<SourceCode>): StringConstantPlan | null {
  const key = sourceCode.ast;
  const cached = PLANS.get(key);
  if (cached !== undefined) return cached;
  const plan = ownedPrimitiveReturns(sourceCode);
  PLANS.set(key, plan);
  return plan;
}

function ownedPrimitiveReturns(sourceCode: Readonly<SourceCode>): StringConstantPlan | null {
  if (sourceCode.getAllComments().length > 0) return null;
  const [statement, ...statements] = sourceCode.ast.body;
  if (statement?.type !== "VariableDeclaration" || !statements.some((entry) => entry.type === "ExportNamedDeclaration"))
    return null;
  const declaration = soleConstDeclarator(statement);
  if (
    declaration?.id.type !== "Identifier" ||
    isPresent(declaration.id.typeAnnotation) ||
    declaration.init?.type !== "Literal" ||
    typeof declaration.init.value !== "string"
  )
    return null;
  const value = declaration.init.value;
  const identifier = declaration.id;
  const binding = declaredBinding(sourceCode, statement, declaration, identifier.name);
  if (binding === null) return null;
  const reads = new Set<Node>();
  const literals = new Set<Node>();
  for (const entry of statements) {
    const argument = ownedStringReturn(sourceCode, entry, binding, value);
    if (argument === null) return null;
    if (argument.type === "Literal") literals.add(argument);
    else reads.add(argument);
  }
  if (
    reads.size === 0 ||
    binding.references.some(
      (reference) => reference.identifier !== identifier && !reads.has(reference.identifier),
    )
  )
    return null;
  return { value, name: sourceCode.getText(identifier), binding, literals };
}

/** The variable `name` that `declaration` alone declares. */
function declaredBinding(
  sourceCode: Readonly<SourceCode>,
  statement: ESTree.VariableDeclaration,
  declaration: ESTree.VariableDeclarator,
  name: string,
): TsVariable | null {
  const found = sourceCode.getDeclaredVariables(statement).find((variable) => variable.name === name);
  return found !== undefined && found.defs.length === 1 && found.defs[0]?.node === declaration ? tsVariable(found) : null;
}

function ownedStringReturn(
  sourceCode: Readonly<SourceCode>,
  entry: Node,
  binding: TsVariable,
  value: string,
): ESTree.IdentifierReference | ESTree.StringLiteral | null {
  const owner = entry.type === "ExportNamedDeclaration" ? entry.declaration : entry;
  if (owner?.type !== "FunctionDeclaration") return null;
  const body = plainFunctionBody(owner);
  if (
    owner.id === null ||
    owner.id.name === binding.name ||
    owner.params.length !== 0 ||
    body?.length !== 1 ||
    (isPresent(owner.returnType) && owner.returnType.typeAnnotation.type !== "TSStringKeyword")
  )
    return null;
  const returned = body[0];
  if (returned?.type !== "ReturnStatement") return null;
  const argument = returned.argument;
  if (argument?.type === "Literal" && argument.value === value) return argument;
  if (
    argument?.type === "Identifier" &&
    argument.name === binding.name &&
    findVariable(sourceCode.getScope(argument), argument.name) === binding
  )
    return argument;
  return null;
}
