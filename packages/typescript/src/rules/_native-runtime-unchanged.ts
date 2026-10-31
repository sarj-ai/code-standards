/** @fileoverview _native-runtime-unchanged — invalidate local native semantics after visible mutation capabilities. */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { forEachAstChild } from "./_for-each-ast-child.js";
import { typeOnlyReference } from "./_stable-value-binding.js";
import { staticPropertyName } from "./_static-string.js";
import { outerExpression } from "./_unwrap-expression.js";

type RuntimeIdentifier = TSESTree.Identifier | TSESTree.JSXIdentifier;

interface RuntimeIndex {
  readonly references: readonly TSESLint.Scope.Reference[];
  readonly nodes: readonly TSESTree.Node[];
  readonly results: Map<string, boolean>;
  readonly fetchAliases: Map<TSESLint.Scope.Variable, "visiting" | "safe" | "unsafe">;
}

const INDEXES = new WeakMap<TSESLint.SourceCode, RuntimeIndex>();
const GLOBAL_OBJECTS: ReadonlySet<string> = new Set(["globalThis", "global", "window", "self"]);

/** Whole-file visible uncertainty vetoes even earlier captures; external monkeypatches are not inferred. */
export function nativeRuntimeUnchanged(sourceCode: Readonly<TSESLint.SourceCode>, name: "Error" | "RegExp" | "fetch"): boolean {
  const index = runtimeIndex(sourceCode);
  const cached = index.results.get(name);
  if (cached !== undefined) return cached;
  const changed = index.nodes.some((node) =>
    (node.type === AST_NODE_TYPES.MemberExpression && staticPropertyName(node, sourceCode) === "constructor") ||
    (name === "fetch" && node.type === AST_NODE_TYPES.Property && node.parent.type === AST_NODE_TYPES.ObjectPattern &&
      staticPropertyName(node, sourceCode) === "constructor") ||
    (name === "RegExp" && node.type === AST_NODE_TYPES.Literal && "regex" in node)) ||
    index.references.some((reference) => (name !== "fetch" || !typeOnlyReference(reference)) &&
      unsafeReference(reference.identifier, sourceCode, name, index));
  index.results.set(name, !changed);
  return !changed;
}

function runtimeIndex(sourceCode: Readonly<TSESLint.SourceCode>): RuntimeIndex {
  const cached = INDEXES.get(sourceCode);
  if (cached !== undefined) return cached;
  const references = sourceCode.scopeManager?.scopes.flatMap((scope) => scope.references
    .filter((reference) => reference.isValueReference !== false)) ?? [];
  const nodes: TSESTree.Node[] = [];
  const pending: TSESTree.Node[] = [sourceCode.ast];
  while (pending.length > 0) {
    const node = pending.pop();
    if (node === undefined) continue;
    nodes.push(node);
    forEachAstChild(node, sourceCode.visitorKeys, (child) => { pending.push(child); });
  }
  const index: RuntimeIndex = { references, nodes, results: new Map(), fetchAliases: new Map() };
  INDEXES.set(sourceCode, index);
  return index;
}

function unsafeReference(node: RuntimeIdentifier, sourceCode: Readonly<TSESLint.SourceCode>, name: string, index: RuntimeIndex): boolean {
  if (!ambient(node, sourceCode)) return false;
  if (node.name === "eval" || node.name === "Function") return true;
  if (node.name === name) return name === "fetch" ? !fetchRead(node, sourceCode, index) : !nativeRead(node, name);
  if (!GLOBAL_OBJECTS.has(node.name)) return false;
  const value = outerExpression(node);
  const property = value.parent;
  if (name === "fetch" && property?.type === AST_NODE_TYPES.UnaryExpression && property.operator === "typeof") return false;
  if (property?.type !== AST_NODE_TYPES.MemberExpression || property.object !== value) {
    return name !== "fetch" || !fetchProjection(value, sourceCode, index);
  }
  const key = staticPropertyName(property, sourceCode);
  if (key === null || key === "eval" || key === "Function" || key === "constructor") return true;
  if (name === "fetch" && GLOBAL_OBJECTS.has(key)) return true;
  return key === name && !(name === "fetch" ? fetchRead(property, sourceCode, index) : nativeRead(property, name));
}

function ambient(node: RuntimeIdentifier, sourceCode: Readonly<TSESLint.SourceCode>): boolean {
  const variable = ASTUtils.findVariable(sourceCode.getScope(node), node.name);
  return variable === null || variable.defs.length === 0;
}

/** A callable can only be called, inspected with typeof, or captured in another stable const. */
function fetchUse(node: TSESTree.Node, sourceCode: Readonly<TSESLint.SourceCode>): true | TSESLint.Scope.Variable | false {
  const value = outerExpression(node);
  const parent = value.parent;
  if ((parent?.type === AST_NODE_TYPES.CallExpression && parent.callee === value) ||
    (parent?.type === AST_NODE_TYPES.UnaryExpression && parent.operator === "typeof")) return true;
  if (parent?.type !== AST_NODE_TYPES.VariableDeclarator || parent.init !== value ||
    parent.id.type !== AST_NODE_TYPES.Identifier) return false;
  return stableConstBinding(parent.id, sourceCode) ?? false;
}

function stableConstBinding(node: TSESTree.Identifier, sourceCode: Readonly<TSESLint.SourceCode>): TSESLint.Scope.Variable | null {
  const binding = ASTUtils.findVariable(sourceCode.getScope(node), node.name);
  if (binding === null || binding.defs.length !== 1) return null;
  const [definition] = binding.defs;
  return definition?.type === "Variable" && definition.parent.kind === "const" && definition.node.init !== null &&
    definition.parent.parent.type !== AST_NODE_TYPES.ExportNamedDeclaration &&
    !binding.references.some((reference) => reference.isWrite() && reference.init !== true)
    ? binding : null;
}

function fetchRead(node: TSESTree.Node, sourceCode: Readonly<TSESLint.SourceCode>, index: RuntimeIndex): boolean {
  const use = fetchUse(node, sourceCode);
  return use === true || (use !== false && fetchAliasRead(use, sourceCode, index));
}

/** Walk only captured bindings' value references, once per binding in this SourceCode's fetch proof. */
function fetchAliasRead(binding: TSESLint.Scope.Variable, sourceCode: Readonly<TSESLint.SourceCode>, index: RuntimeIndex): boolean {
  const pending = [binding];
  const visited: TSESLint.Scope.Variable[] = [];
  let safe = true;
  while (pending.length > 0 && safe) {
    const current = pending.pop();
    if (current === undefined) continue;
    const cached = index.fetchAliases.get(current);
    if (cached === "safe") continue;
    if (cached !== undefined) { safe = false; break; }
    index.fetchAliases.set(current, "visiting");
    visited.push(current);
    const captures = fetchAliasCaptures(current, sourceCode);
    if (captures === false) { safe = false; break; }
    for (const captured of captures) pending.push(captured);
  }
  for (const current of visited) index.fetchAliases.set(current, safe ? "safe" : "unsafe");
  return safe;
}

/** Classify one captured binding without traversing or caching its captured aliases. */
function fetchAliasCaptures(binding: TSESLint.Scope.Variable, sourceCode: Readonly<TSESLint.SourceCode>): readonly TSESLint.Scope.Variable[] | false {
  const captures: TSESLint.Scope.Variable[] = [];
  for (const reference of binding.references) {
    if (reference.isValueReference === false || reference.init === true || typeOnlyReference(reference)) continue;
    const use = fetchUse(reference.identifier, sourceCode);
    if (use === false) return false;
    if (use !== true) captures.push(use);
  }
  return captures;
}

/** Admit only a single simple fetch projection, never a whole-global alias or rest capture. */
function fetchProjection(node: TSESTree.Node, sourceCode: Readonly<TSESLint.SourceCode>, index: RuntimeIndex): boolean {
  const declaration = node.parent;
  if (declaration?.type !== AST_NODE_TYPES.VariableDeclarator || declaration.init !== node ||
    declaration.id.type !== AST_NODE_TYPES.ObjectPattern || declaration.id.properties.length !== 1) return false;
  const [property] = declaration.id.properties;
  if (property?.type !== AST_NODE_TYPES.Property || staticPropertyName(property, sourceCode) !== "fetch" ||
    property.value.type !== AST_NODE_TYPES.Identifier) return false;
  const binding = stableConstBinding(property.value, sourceCode);
  return binding !== null && fetchAliasRead(binding, sourceCode, index);
}

function nativeRead(node: TSESTree.Node, name: string): boolean {
  const value = outerExpression(node);
  const parent = value.parent;
  if (parent?.type === AST_NODE_TYPES.UnaryExpression && parent.operator === "typeof") return true;
  if (name !== "Error") return false;
  return (parent?.type === AST_NODE_TYPES.NewExpression && parent.callee === value) ||
    (parent?.type === AST_NODE_TYPES.BinaryExpression && parent.operator === "instanceof" && parent.right === value);
}
