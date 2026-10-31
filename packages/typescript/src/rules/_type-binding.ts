/** @fileoverview _type-binding — resolve type names without value-only shadowing. */
import { AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

export function typeBinding(
  source: Readonly<TSESLint.SourceCode>,
  identifier: TSESTree.Identifier,
): TSESLint.Scope.Variable | null {
  let scope: TSESLint.Scope.Scope | null = source.getScope(identifier);
  while (scope !== null) {
    const variable = scope.set.get(identifier.name);
    if (variable !== undefined &&
      (variable.isTypeVariable || variable.defs.some(definition => definition.isTypeDefinition))) {
      return variable;
    }
    scope = scope.upper;
  }
  return null;
}

/** Extrema identify whether any compatible public read lies outside a removed range. */
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
  readonly manager: NonNullable<TSESLint.SourceCode["scopeManager"]>;
  readonly references: readonly TSESLint.Scope.Reference[];
  readonly publicReads: Map<TSESLint.Scope.Variable, PublicReadExtents>;
}

// Reuse completed parser facts for the lifetime of this SourceCode and scope manager.
const REFERENCE_INDEXES = new WeakMap<Readonly<TSESLint.SourceCode>, ReferenceIndex>();

/** Erased named reads need an independent public type use that no SAFE fixer removes. */
export function retainsNamedTypeUses(
  source: Readonly<TSESLint.SourceCode>,
  removed: TSESTree.Node,
): boolean {
  const manager = source.scopeManager;
  if (manager === null) return false;
  const index = referenceIndex(source, manager);
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

function referenceIndex(source: Readonly<TSESLint.SourceCode>, manager: ReferenceIndex["manager"]): ReferenceIndex {
  const cached = REFERENCE_INDEXES.get(source);
  if (cached?.manager === manager) return cached;
  const references = manager.scopes.flatMap(scope => scope.references);
  references.sort((left, right) => left.identifier.range[0] - right.identifier.range[0]);
  const index: ReferenceIndex = { manager, references, publicReads: new Map() };
  REFERENCE_INDEXES.set(source, index);
  return index;
}

function* referencesWithin(references: readonly TSESLint.Scope.Reference[], removed: TSESTree.Node): Iterable<TSESLint.Scope.Reference> {
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

function publicReadExtents(index: ReferenceIndex, binding: TSESLint.Scope.Variable): PublicReadExtents {
  const cached = index.publicReads.get(binding);
  if (cached !== undefined) return cached;
  let type: ReadExtent | null = null;
  let value: ReadExtent | null = null;
  let both: ReadExtent | null = null;
  for (const retained of binding.references) {
    if (!retained.isRead() || (!retained.isTypeReference && !retained.isValueReference) ||
      binding.defs.some(definition => insideTypeRange(retained.identifier, definition.node)) ||
      !publicTypeUse(retained.identifier)) continue;
    if (retained.isTypeReference) type = extendExtent(type, retained.identifier);
    if (retained.isValueReference) value = extendExtent(value, retained.identifier);
    if (retained.isTypeReference && retained.isValueReference) both = extendExtent(both, retained.identifier);
  }
  const result: PublicReadExtents = { type, value, both };
  index.publicReads.set(binding, result);
  return result;
}

function extendExtent(extent: ReadExtent | null, identifier: TSESTree.Identifier | TSESTree.JSXIdentifier): ReadExtent {
  return {
    minStart: Math.min(extent?.minStart ?? identifier.range[0], identifier.range[0]),
    maxEnd: Math.max(extent?.maxEnd ?? identifier.range[1], identifier.range[1]),
  };
}

/** Private declarations and erasable annotations cannot keep one another live. */
function publicTypeUse(identifier: TSESTree.Identifier | TSESTree.JSXIdentifier): boolean {
  let node: TSESTree.Node = identifier;
  while (node.parent) {
    if (node.type === AST_NODE_TYPES.TSTypeAnnotation || node.type === AST_NODE_TYPES.TSTypePredicate ||
      node.type === AST_NODE_TYPES.TSAsExpression || node.type === AST_NODE_TYPES.TSTypeAssertion) return false;
    if (node.type === AST_NODE_TYPES.TSTypeAliasDeclaration) {
      return node.parent.type === AST_NODE_TYPES.ExportNamedDeclaration &&
        node.parent.declaration === node && node.parent.parent.type === AST_NODE_TYPES.Program;
    }
    if (node.type === AST_NODE_TYPES.ExportSpecifier) {
      return node.parent.type === AST_NODE_TYPES.ExportNamedDeclaration &&
        node.parent.source === null && node.parent.parent.type === AST_NODE_TYPES.Program;
    }
    node = node.parent;
  }
  return false;
}

function insideTypeRange(node: TSESTree.Node, range: TSESTree.Node): boolean {
  return node.range[0] >= range.range[0] && node.range[1] <= range.range[1];
}
