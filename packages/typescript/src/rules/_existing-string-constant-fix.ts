/**
 * @fileoverview _existing-string-constant-fix — reuse an authored primitive string constant.
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

interface StringConstantPlan {
  readonly value: string;
  readonly name: string;
  readonly binding: TSESLint.Scope.Variable;
  readonly literals: ReadonlySet<TSESTree.Node>;
}

const PLANS = new WeakMap<
  Readonly<TSESLint.SourceCode>,
  StringConstantPlan | null
>();

/** Reuse an existing primitive constant in a complete declaration-only module. */
export function existingStringConstantFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.Node,
  value: string,
): TSESLint.ReportFixFunction | null {
  if (node.type !== AST_NODE_TYPES.Literal || node.value !== value) return null;
  const plan = stringConstantPlan(sourceCode);
  if (
    plan === null ||
    plan.value !== value ||
    !plan.literals.has(node) ||
    ASTUtils.findVariable(sourceCode.getScope(node), plan.binding.name) !==
      plan.binding
  )
    return null;
  return (fixer) => fixer.replaceText(node, plan.name);
}

function stringConstantPlan(
  sourceCode: Readonly<TSESLint.SourceCode>,
): StringConstantPlan | null {
  const cached = PLANS.get(sourceCode);
  if (cached !== undefined) return cached;
  const plan = ownedPrimitiveReturns(sourceCode);
  PLANS.set(sourceCode, plan);
  return plan;
}

function ownedPrimitiveReturns(
  sourceCode: Readonly<TSESLint.SourceCode>,
): StringConstantPlan | null {
  if (sourceCode.getAllComments().length > 0) return null;
  const [statement, ...statements] = sourceCode.ast.body;
  if (
    statement?.type !== AST_NODE_TYPES.VariableDeclaration ||
    statement.kind !== "const" ||
    statement.declare ||
    statement.declarations.length !== 1 ||
    !statements.some(
      (entry) => entry.type === AST_NODE_TYPES.ExportNamedDeclaration,
    )
  )
    return null;
  const declaration = statement.declarations[0];
  if (
    declaration?.id.type !== AST_NODE_TYPES.Identifier ||
    declaration.id.typeAnnotation !== undefined ||
    declaration.init?.type !== AST_NODE_TYPES.Literal ||
    typeof declaration.init.value !== "string"
  )
    return null;
  const value = declaration.init.value;
  const identifier = declaration.id;
  const binding = sourceCode
    .getDeclaredVariables(statement)
    .find((variable) => variable.name === identifier.name);
  if (
    binding === undefined ||
    binding.defs.length !== 1 ||
    binding.defs[0]?.node !== declaration
  )
    return null;
  const reads = new Set<TSESTree.Node>();
  const literals = new Set<TSESTree.Node>();
  for (const entry of statements) {
    const argument = ownedStringReturn(sourceCode, entry, binding, value);
    if (argument === null) return null;
    if (argument.type === AST_NODE_TYPES.Literal) literals.add(argument);
    else reads.add(argument);
  }
  if (
    reads.size === 0 ||
    binding.references.some(
      (reference) =>
        reference.identifier !== identifier && !reads.has(reference.identifier),
    )
  )
    return null;
  return { value, name: sourceCode.getText(identifier), binding, literals };
}

function ownedStringReturn(
  sourceCode: Readonly<TSESLint.SourceCode>,
  entry: TSESTree.Node,
  binding: TSESLint.Scope.Variable,
  value: string,
): TSESTree.Identifier | TSESTree.Literal | null {
  const owner =
    entry.type === AST_NODE_TYPES.ExportNamedDeclaration
      ? entry.declaration
      : entry;
  if (
    owner?.type !== AST_NODE_TYPES.FunctionDeclaration ||
    owner.id === null ||
    owner.id.name === binding.name ||
    owner.async ||
    owner.generator ||
    owner.declare ||
    owner.typeParameters !== undefined ||
    owner.params.length !== 0 ||
    owner.body.body.length !== 1 ||
    (owner.returnType !== undefined &&
      owner.returnType.typeAnnotation.type !== AST_NODE_TYPES.TSStringKeyword)
  )
    return null;
  const returned = owner.body.body[0];
  if (returned?.type !== AST_NODE_TYPES.ReturnStatement) return null;
  const argument = returned.argument;
  if (argument?.type === AST_NODE_TYPES.Literal && argument.value === value)
    return argument;
  if (
    argument?.type === AST_NODE_TYPES.Identifier &&
    argument.name === binding.name &&
    ASTUtils.findVariable(sourceCode.getScope(argument), argument.name) ===
      binding
  )
    return argument;
  return null;
}
