/**
 * @fileoverview _native-fetch-reference — prove bounded native fetch references without evaluating wrappers.
 */
import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";
import { unwrapExpression } from "./_unwrap-expression.js";

const GLOBAL_RECEIVERS: ReadonlySet<string> = new Set(["globalThis", "self", "window"]);

/** Follow only unshadowed native references and stable const aliases without defaults. */
export function nativeFetchReference(
  node: TSESTree.Node,
  sourceCode: Readonly<TSESLint.SourceCode>,
  seen = new Set<TSESLint.Scope.Variable>(),
): boolean {
  const expression = unwrapExpression(node);
  if (expression.type === AST_NODE_TYPES.MemberExpression) {
    return ASTUtils.getPropertyName(expression) === "fetch" && globalReceiver(expression.object, sourceCode);
  }
  if (expression.type !== AST_NODE_TYPES.Identifier) return false;
  const binding = ASTUtils.findVariable(sourceCode.getScope(expression), expression.name);
  if (binding === null || binding.defs.length === 0) return expression.name === "fetch";
  if (seen.has(binding) || seen.size >= 8 || binding.defs.length !== 1 ||
    binding.references.some(reference => reference.isWrite() && reference.init !== true)) return false;
  seen.add(binding);
  const [definition] = binding.defs;
  if (definition?.type !== "Variable" || definition.parent.kind !== "const" || definition.node.init === null) return false;
  if (definition.node.id.type === AST_NODE_TYPES.Identifier) {
    return nativeFetchReference(definition.node.init, sourceCode, seen);
  }
  return definition.node.id.type === AST_NODE_TYPES.ObjectPattern && globalReceiver(definition.node.init, sourceCode) &&
    definition.node.id.properties.some(property => property.type === AST_NODE_TYPES.Property &&
      ASTUtils.getPropertyName(property) === "fetch" && property.value.type === AST_NODE_TYPES.Identifier &&
      ASTUtils.findVariable(sourceCode.getScope(property.value), property.value.name) === binding);
}

function globalReceiver(node: TSESTree.Node, sourceCode: Readonly<TSESLint.SourceCode>): boolean {
  const receiver = unwrapExpression(node);
  return receiver.type === AST_NODE_TYPES.Identifier && GLOBAL_RECEIVERS.has(receiver.name) &&
    !ASTUtils.findVariable(sourceCode.getScope(receiver), receiver.name)?.defs.length;
}
