/** @fileoverview native-runtime-unchanged — invalidate local native semantics after visible mutation capabilities. */

import type { ESTree, Node, SourceCode, TsReference, TsVariable } from "../types.js";
import { tsReference } from "../types.js";
import { forEachAstChild, outerExpression, parentOf } from "./ast.js";
import { typeOnlyReference } from "./stable-value-binding.js";
import { findVariable, staticPropertyName } from "./static-string.js";

type RuntimeIdentifier = Node & { readonly name: string };

interface RuntimeIndex {
  readonly references: readonly TsReference[];
  readonly nodes: readonly Node[];
  readonly results: Map<string, boolean>;
  readonly fetchAliases: Map<TsVariable, "visiting" | "safe" | "unsafe">;
}

// Oxlint reuses one SourceCode object for every file, so index per AST.
const INDEXES = new WeakMap<ESTree.Program, RuntimeIndex>();
const GLOBAL_OBJECTS: ReadonlySet<string> = new Set(["globalThis", "global", "window", "self"]);

/** Whole-file visible uncertainty vetoes even earlier captures; external monkeypatches are not inferred. */
export function nativeRuntimeUnchanged(sourceCode: Readonly<SourceCode>, name: "Error" | "RegExp" | "fetch"): boolean {
  const index = runtimeIndex(sourceCode);
  const cached = index.results.get(name);
  if (cached !== undefined) return cached;
  const changed = index.nodes.some((node) =>
    (node.type === "MemberExpression" && staticPropertyName(node, sourceCode) === "constructor") ||
    (name === "fetch" && node.type === "Property" && parentOf(node)?.type === "ObjectPattern" &&
      staticPropertyName(node as ESTree.ObjectProperty, sourceCode) === "constructor") ||
    (name === "RegExp" && node.type === "Literal" && "regex" in node)) ||
    index.references.some((reference) => (name !== "fetch" || !typeOnlyReference(reference)) &&
      unsafeReference(reference.identifier, sourceCode, name, index));
  index.results.set(name, !changed);
  return !changed;
}

function runtimeIndex(sourceCode: Readonly<SourceCode>): RuntimeIndex {
  const cached = INDEXES.get(sourceCode.ast);
  if (cached !== undefined) return cached;
  const references = sourceCode.scopeManager.scopes.flatMap((scope) => scope.references.map(tsReference)
    .filter((reference) => reference.isValueReference !== false));
  const nodes: Node[] = [];
  const pending: Node[] = [sourceCode.ast];
  while (pending.length > 0) {
    const node = pending.pop();
    if (node === undefined) continue;
    nodes.push(node);
    forEachAstChild(node, sourceCode.visitorKeys, (child) => { pending.push(child); });
  }
  const index: RuntimeIndex = { references, nodes, results: new Map(), fetchAliases: new Map() };
  INDEXES.set(sourceCode.ast, index);
  return index;
}

function unsafeReference(node: RuntimeIdentifier, sourceCode: Readonly<SourceCode>, name: string, index: RuntimeIndex): boolean {
  if (!ambient(node, sourceCode)) return false;
  if (node.name === "eval" || node.name === "Function") return true;
  if (node.name === name) return name === "fetch" ? !fetchRead(node, sourceCode, index) : !nativeRead(node, name);
  if (!GLOBAL_OBJECTS.has(node.name)) return false;
  const value = outerExpression(node);
  const property = parentOf(value);
  if (name === "fetch" && property?.type === "UnaryExpression" && property.operator === "typeof") return false;
  if (property?.type !== "MemberExpression" || property.object !== value) {
    return name !== "fetch" || !fetchProjection(value, sourceCode, index);
  }
  const key = staticPropertyName(property, sourceCode);
  if (key === null || key === "eval" || key === "Function" || key === "constructor") return true;
  if (name === "fetch" && GLOBAL_OBJECTS.has(key)) return true;
  return key === name && !(name === "fetch" ? fetchRead(property, sourceCode, index) : nativeRead(property, name));
}

function ambient(node: RuntimeIdentifier, sourceCode: Readonly<SourceCode>): boolean {
  const variable = findVariable(sourceCode.getScope(node), node.name);
  return variable === null || variable.defs.length === 0;
}

/** A callable can only be called, inspected with typeof, or captured in another stable const. */
function fetchUse(node: Node, sourceCode: Readonly<SourceCode>): true | TsVariable | false {
  const value = outerExpression(node);
  const parent = parentOf(value);
  if ((parent?.type === "CallExpression" && parent.callee === value) ||
    (parent?.type === "UnaryExpression" && parent.operator === "typeof")) return true;
  if (parent?.type !== "VariableDeclarator" || parent.init !== value ||
    parent.id.type !== "Identifier") return false;
  return stableConstBinding(parent.id, sourceCode) ?? false;
}

function stableConstBinding(node: RuntimeIdentifier, sourceCode: Readonly<SourceCode>): TsVariable | null {
  const binding = findVariable(sourceCode.getScope(node), node.name);
  if (binding === null || binding.defs.length !== 1) return null;
  const [definition] = binding.defs;
  if (definition?.type !== "Variable") return null;
  const declaration = definition.parent as ESTree.VariableDeclaration;
  return declaration.kind === "const" && (definition.node as ESTree.VariableDeclarator).init !== null &&
    parentOf(declaration)?.type !== "ExportNamedDeclaration" &&
    !binding.references.some((reference) => reference.isWrite() && reference.init !== true)
    ? binding : null;
}

function fetchRead(node: Node, sourceCode: Readonly<SourceCode>, index: RuntimeIndex): boolean {
  const use = fetchUse(node, sourceCode);
  return use === true || (use !== false && fetchAliasRead(use, sourceCode, index));
}

/** Walk only captured bindings' value references, once per binding in this file's fetch proof. */
function fetchAliasRead(binding: TsVariable, sourceCode: Readonly<SourceCode>, index: RuntimeIndex): boolean {
  const pending = [binding];
  const visited: TsVariable[] = [];
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
function fetchAliasCaptures(binding: TsVariable, sourceCode: Readonly<SourceCode>): readonly TsVariable[] | false {
  const captures: TsVariable[] = [];
  for (const reference of binding.references) {
    if (reference.isValueReference === false || reference.init === true || typeOnlyReference(reference)) continue;
    const use = fetchUse(reference.identifier, sourceCode);
    if (use === false) return false;
    if (use !== true) captures.push(use);
  }
  return captures;
}

/** Admit only a single simple fetch projection, never a whole-global alias or rest capture. */
function fetchProjection(node: Node, sourceCode: Readonly<SourceCode>, index: RuntimeIndex): boolean {
  const declaration = parentOf(node);
  if (declaration?.type !== "VariableDeclarator" || declaration.init !== node ||
    declaration.id.type !== "ObjectPattern" || declaration.id.properties.length !== 1) return false;
  const [property] = declaration.id.properties;
  if (property?.type !== "Property" || staticPropertyName(property as ESTree.ObjectProperty, sourceCode) !== "fetch" ||
    property.value.type !== "Identifier") return false;
  const binding = stableConstBinding(property.value, sourceCode);
  return binding !== null && fetchAliasRead(binding, sourceCode, index);
}

function nativeRead(node: Node, name: string): boolean {
  const value = outerExpression(node);
  const parent = parentOf(value);
  if (parent?.type === "UnaryExpression" && parent.operator === "typeof") return true;
  if (name !== "Error") return false;
  return (parent?.type === "NewExpression" && parent.callee === value) ||
    (parent?.type === "BinaryExpression" && parent.operator === "instanceof" && parent.right === value);
}
