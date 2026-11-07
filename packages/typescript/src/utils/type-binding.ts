/** @fileoverview type-binding — resolve type names without value-only shadowing. */

import type { Node, Scope, SourceCode, TsReference, TsVariable } from "../types.js";
import { tsReference, tsVariable } from "../types.js";
import { parentOf } from "./ast.js";

export function typeBinding(source: SourceCode, identifier: Node & { name: string }): TsVariable | null {
  let scope: Scope | null = source.getScope(identifier);
  while (scope !== null) {
    const found = scope.set.get(identifier.name);
    if (found !== undefined) {
      const variable = tsVariable(found);
      if (variable.isTypeVariable || variable.defs.some((definition) => definition.isTypeDefinition)) return variable;
    }
    scope = scope.upper;
  }
  return null;
}

interface ReadExtent {
  readonly minStart: number;
  readonly maxEnd: number;
}

interface PublicReadExtents {
  readonly type: ReadExtent | null;
  readonly value: ReadExtent | null;
  readonly both: ReadExtent | null;
}

interface ReferenceIndex {
  readonly references: readonly TsReference[];
  readonly publicReads: Map<TsVariable, PublicReadExtents>;
}

// Oxlint reuses one SourceCode and one scope-manager object for every file, so
// key per-file facts by the file's AST, which is new for each file.
const REFERENCE_INDEXES = new WeakMap<object, ReferenceIndex>();

/** Erased named reads need an independent public type use that no SAFE fixer removes. */
export function retainsNamedTypeUses(source: SourceCode, removed: Node): boolean {
  const index = referenceIndex(source);
  for (const reference of referencesWithin(index.references, removed)) {
    if (!reference.isRead()) continue;
    const binding = reference.resolved;
    if (!binding || (!reference.isTypeReference && !reference.isValueReference)) return false;
    if (binding.defs.length === 0) continue;
    const reads = publicReadExtents(index, binding);
    const extent = reference.isTypeReference ? (reference.isValueReference ? reads.both : reads.type) : reads.value;
    if (extent === null || (extent.minStart >= removed.range[0] && extent.maxEnd <= removed.range[1])) return false;
  }
  return true;
}

function referenceIndex(source: SourceCode): ReferenceIndex {
  const cached = REFERENCE_INDEXES.get(source.ast);
  if (cached !== undefined) return cached;
  const references = source.scopeManager.scopes.flatMap((scope) => scope.references.map(tsReference));
  references.sort((left, right) => left.identifier.range[0] - right.identifier.range[0]);
  const index: ReferenceIndex = { references, publicReads: new Map() };
  REFERENCE_INDEXES.set(source.ast, index);
  return index;
}

function* referencesWithin(references: readonly TsReference[], removed: Node): Iterable<TsReference> {
  let low = 0;
  let high = references.length;
  while (low < high) {
    const middle = low + Math.floor((high - low) / 2);
    const reference = references[middle];
    if (reference === undefined || reference.identifier.range[0] >= removed.range[0]) high = middle;
    else low = middle + 1;
  }
  for (let index = low; index < references.length; index++) {
    const reference = references[index];
    if (reference === undefined) continue;
    if (reference.identifier.range[0] > removed.range[1]) break;
    if (insideTypeRange(reference.identifier, removed)) yield reference;
  }
}

function publicReadExtents(index: ReferenceIndex, binding: TsVariable): PublicReadExtents {
  const cached = index.publicReads.get(binding);
  if (cached !== undefined) return cached;
  let type: ReadExtent | null = null;
  let value: ReadExtent | null = null;
  let both: ReadExtent | null = null;
  for (const retained of binding.references) {
    if (!retained.isRead() || (!retained.isTypeReference && !retained.isValueReference) ||
      binding.defs.some((definition) => insideTypeRange(retained.identifier, definition.node)) ||
      !publicTypeUse(retained.identifier)) continue;
    if (retained.isTypeReference) type = extendExtent(type, retained.identifier);
    if (retained.isValueReference) value = extendExtent(value, retained.identifier);
    if (retained.isTypeReference && retained.isValueReference) both = extendExtent(both, retained.identifier);
  }
  const result: PublicReadExtents = { type, value, both };
  index.publicReads.set(binding, result);
  return result;
}

function extendExtent(extent: ReadExtent | null, identifier: Node): ReadExtent {
  return {
    minStart: Math.min(extent?.minStart ?? identifier.range[0], identifier.range[0]),
    maxEnd: Math.max(extent?.maxEnd ?? identifier.range[1], identifier.range[1]),
  };
}

/** Private declarations and erasable annotations cannot keep one another live. */
function publicTypeUse(identifier: Node): boolean {
  let node: Node = identifier;
  let parent = parentOf(node);
  while (parent !== null) {
    if (node.type === "TSTypeAnnotation" || node.type === "TSTypePredicate" ||
      node.type === "TSAsExpression" || node.type === "TSTypeAssertion") return false;
    if (node.type === "TSTypeAliasDeclaration") {
      return parent.type === "ExportNamedDeclaration" && parent.declaration === node && parentOf(parent)?.type === "Program";
    }
    if (node.type === "ExportSpecifier") {
      return parent.type === "ExportNamedDeclaration" && parent.source === null && parentOf(parent)?.type === "Program";
    }
    node = parent;
    parent = parentOf(node);
  }
  return false;
}

function insideTypeRange(node: Node, range: Node): boolean {
  return node.range[0] >= range.range[0] && node.range[1] <= range.range[1];
}
