/** @fileoverview _native-runtime-unchanged — invalidate local native semantics after visible mutation capabilities. */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { forEachAstChild } from "./_for-each-ast-child.js";
import { staticPropertyName } from "./_static-string.js";
import { outerExpression } from "./_unwrap-expression.js";

type RuntimeIdentifier = TSESTree.Identifier | TSESTree.JSXIdentifier;

interface RuntimeIndex {
  readonly references: readonly RuntimeIdentifier[];
  readonly nodes: readonly TSESTree.Node[];
  readonly results: Map<string, boolean>;
}

const INDEXES = new WeakMap<TSESLint.SourceCode, RuntimeIndex>();
const GLOBAL_OBJECTS: ReadonlySet<string> = new Set(["globalThis", "global", "window", "self"]);

/** This proves only absence of visible mutation/escape; external monkeypatches are not inferred. */
export function nativeRuntimeUnchanged(sourceCode: TSESLint.SourceCode, name: "Error" | "RegExp"): boolean {
  const index = runtimeIndex(sourceCode);
  const cached = index.results.get(name);
  if (cached !== undefined) return cached;
  const changed = index.nodes.some((node) =>
    (node.type === AST_NODE_TYPES.MemberExpression && staticPropertyName(node, sourceCode) === "constructor") ||
    (name === "RegExp" && node.type === AST_NODE_TYPES.Literal && "regex" in node)) ||
    index.references.some((node) => unsafeReference(node, sourceCode, name));
  index.results.set(name, !changed);
  return !changed;
}

function runtimeIndex(sourceCode: TSESLint.SourceCode): RuntimeIndex {
  const cached = INDEXES.get(sourceCode);
  if (cached !== undefined) return cached;
  const references = sourceCode.scopeManager?.scopes.flatMap((scope) => scope.references
    .filter((reference) => reference.isValueReference !== false).map((reference) => reference.identifier)) ?? [];
  const nodes: TSESTree.Node[] = [];
  const pending: TSESTree.Node[] = [sourceCode.ast];
  while (pending.length > 0) {
    const node = pending.pop();
    if (node === undefined) continue;
    nodes.push(node);
    forEachAstChild(node, sourceCode.visitorKeys, (child) => { pending.push(child); });
  }
  const index = { references, nodes, results: new Map<string, boolean>() };
  INDEXES.set(sourceCode, index);
  return index;
}

function unsafeReference(node: RuntimeIdentifier, sourceCode: TSESLint.SourceCode, name: string): boolean {
  if (!ambient(node, sourceCode)) return false;
  if (node.name === "eval" || node.name === "Function") return true;
  if (node.name === name) return !nativeRead(node, name);
  if (!GLOBAL_OBJECTS.has(node.name)) return false;
  const value = outerExpression(node);
  const property = value.parent;
  if (property?.type !== AST_NODE_TYPES.MemberExpression || property.object !== value) return true;
  const key = staticPropertyName(property, sourceCode);
  if (key === null || key === "eval" || key === "Function" || key === "constructor") return true;
  return key === name && !nativeRead(property, name);
}

function ambient(node: RuntimeIdentifier, sourceCode: TSESLint.SourceCode): boolean {
  const variable = ASTUtils.findVariable(sourceCode.getScope(node), node.name);
  return variable === null || variable.defs.length === 0;
}

function nativeRead(node: TSESTree.Node, name: string): boolean {
  const value = outerExpression(node);
  const parent = value.parent;
  if (parent?.type === AST_NODE_TYPES.UnaryExpression && parent.operator === "typeof") return true;
  if (name !== "Error") return false;
  return (parent?.type === AST_NODE_TYPES.NewExpression && parent.callee === value) ||
    (parent?.type === AST_NODE_TYPES.BinaryExpression && parent.operator === "instanceof" && parent.right === value);
}
