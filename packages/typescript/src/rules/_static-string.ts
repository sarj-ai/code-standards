/** @fileoverview _static-string — static values exclude interpolation and opaque expressions. */
import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";
import { unwrapExpression } from "./_unwrap-expression.js";

export function staticString(node: TSESTree.Node | undefined): string | null {
  if (node === undefined) return null;
  const value = unwrapExpression(node);
  if (value.type === AST_NODE_TYPES.Literal && typeof value.value === "string") return value.value;
  return value.type === AST_NODE_TYPES.TemplateLiteral && value.expressions.length === 0
    ? value.quasis[0]?.value.cooked ?? null : null;
}

const SCOPED_STRING_VALUES = new WeakMap<Readonly<TSESLint.SourceCode>, WeakMap<TSESLint.Scope.Variable, string | null>>();

/** Follow stable local aliases without evaluating function or object-derived values. */
export function scopedStaticString(
  node: TSESTree.Node,
  sourceCode: Readonly<TSESLint.SourceCode>,
): string | null {
  let value = unwrapExpression(node);
  if (value.type !== AST_NODE_TYPES.Identifier) return staticString(value);
  let values = SCOPED_STRING_VALUES.get(sourceCode);
  if (values === undefined) {
    values = new WeakMap<TSESLint.Scope.Variable, string | null>();
    SCOPED_STRING_VALUES.set(sourceCode, values);
  }
  const seen = new Set<TSESLint.Scope.Variable>();
  const pending: TSESLint.Scope.Variable[] = [];
  let result: string | null = null;
  while (value.type === AST_NODE_TYPES.Identifier) {
    const binding = ASTUtils.findVariable(sourceCode.getScope(value), value.name);
    if (binding === null || seen.has(binding)) break;
    if (values.has(binding)) {
      result = values.get(binding) ?? null;
      break;
    }
    seen.add(binding);
    pending.push(binding);
    const definition = binding.defs.length === 1 ? binding.defs[0] : undefined;
    if (definition?.type !== "Variable" || definition.node.id.type !== AST_NODE_TYPES.Identifier ||
      definition.node.init === null || binding.references.some((reference) => reference.isWrite() && reference.init !== true)) break;
    value = unwrapExpression(definition.node.init);
    if (value.type !== AST_NODE_TYPES.Identifier) result = staticString(value);
  }
  for (const binding of pending) values.set(binding, result);
  return result;
}

/** Preserve literal property decoding and additionally resolve stable local string keys. */
export function staticPropertyName(
  node: TSESTree.MemberExpression | TSESTree.Property,
  sourceCode: Readonly<TSESLint.SourceCode>,
): string | null {
  const direct = ASTUtils.getPropertyName(node);
  if (direct !== null || !node.computed) return direct;
  const key = node.type === AST_NODE_TYPES.MemberExpression ? node.property : node.key;
  return key.type === AST_NODE_TYPES.Identifier ? scopedStaticString(key, sourceCode) : null;
}
