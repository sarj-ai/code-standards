/**
 * @fileoverview _contradictory-array-predicate — native array membership does not validate a primitive element contract.
 *
 * Port of the 18.x `_contradictory-array-predicate.ts` helper. The scope
 * checks run on Oxlint's scopes; the two type checks (a plain primitive
 * element array target, a default-library `Array.isArray` signature) ask
 * tsrs, so `matches` runs in `Program:exit`. Computed names resolve through
 * `staticPropertyName`, which follows stable local string constants as
 * eslint-utils `getPropertyName(node, scope)` does for these shapes.
 */

import type { Type } from "tsrs/sync";

import type { ESTree, Node, SourceCode, TsReference } from "../types.js";
import { tsReference, tsVariable } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import type { NativeTypes } from "../utils/checked-native-source.js";
import { findVariable, getPropertyName, staticPropertyName } from "../utils/static-string.js";

type Identifier = Node & { readonly type: "Identifier"; readonly name: string };

export interface ArrayPredicateProof {
  matches(native: NativeTypes, expression: Node, parameter: Identifier, input: Type, target: Type): boolean;
  readonly observeConstructor: (member: ESTree.MemberExpression | ESTree.ObjectProperty) => void;
  readonly stable: () => boolean;
}

const HOST_GLOBALS = ["globalThis", "window", "self", "global"] as const;
const OBJECT_REFLECTION: ReadonlySet<string> = new Set(["getPrototypeOf", "getOwnPropertyDescriptor", "getOwnPropertyDescriptors", "prototype", "constructor", "__proto__"]);

/** One proof per file, created in `before()`: its cache holds this file's answer only. */
export function contradictoryArrayPredicate(sourceCode: SourceCode): ArrayPredicateProof {
  const stable = new Map<string, boolean>();
  let constructorCapability = false;
  function matches(native: NativeTypes, expression: Node, parameter: Identifier, input: Type, target: Type): boolean {
    if ((input.flags & native.sync.TypeFlags.Unknown) === 0 || !plainPrimitiveArray(target, native)) return false;
    const call = unwrapExpression(expression);
    if (call.type !== "CallExpression" || call.optional || call.arguments.length !== 1) return false;
    const argument = call.arguments[0];
    const callee = unwrapExpression(call.callee);
    if (argument?.type !== "Identifier" || callee.type !== "MemberExpression" || callee.optional ||
      getPropertyName(callee) !== "isArray" || callee.object.type !== "Identifier" || callee.object.name !== "Array") return false;
    const declared = findVariable(sourceCode.getScope(parameter), parameter.name);
    if (declared === null || declared !== findVariable(sourceCode.getScope(argument), argument.name)) return false;
    const binding = nativeBinding(callee.object, sourceCode);
    if (binding === undefined || !stableArray(binding, sourceCode, stable)) return false;
    const location = native.node(call);
    if (location === undefined) return false;
    const declaration = native.checker.getResolvedSignature(location).declaration;
    return declaration !== undefined && native.program.getSourceFileMetadataByPath(declaration.path)?.isDefaultLibrary === true;
  }
  return {
    matches,
    observeConstructor(member): void {
      const name = staticPropertyName(member, sourceCode);
      if (name === "constructor" || name === null && member.computed) constructorCapability = true;
    },
    stable(): boolean {
      // A structural receiver type cannot prove which runtime constructor escapes.
      return !constructorCapability;
    },
  };
}

function plainPrimitiveArray(target: Type, native: NativeTypes): boolean {
  const flags = native.sync.TypeFlags;
  if (!native.checker.isArrayType(target) || !target.isTypeReference()) return false;
  const [element] = native.checker.getTypeArguments(target);
  const primitive = flags.String | flags.Number | flags.Boolean | flags.BigInt | flags.ESSymbol;
  return element !== undefined && (element.flags & primitive) !== 0 &&
    (element.flags & (flags.Enum | flags.EnumLiteral | flags.Intersection)) === 0;
}

/** The references of an unshadowed global. */
interface NativeBinding {
  readonly references: readonly TsReference[];
}

/**
 * TS-ESLint declares lib globals such as `Array` as implicit variables without
 * definitions. Oxlint analyzes with `lib: []`, so an unconfigured global has no
 * variable and its references stay in the global scope's `through`; those are
 * the implicit variable's references.
 */
function nativeBinding(identifier: Identifier, sourceCode: SourceCode): NativeBinding | undefined {
  const binding = findVariable(sourceCode.getScope(identifier), identifier.name);
  if (binding !== null) return binding.defs.length === 0 ? binding : undefined;
  const through = globalScope(sourceCode)?.through.map(tsReference) ?? [];
  return { references: through.filter((reference) => reference.identifier.name === identifier.name) };
}

function globalScope(sourceCode: SourceCode) {
  return (sourceCode.scopeManager as SourceCode["scopeManager"] | null)?.globalScope ?? null;
}

// One file has one unshadowed global `Array`, so the cache holds one entry.
function stableArray(binding: NativeBinding, sourceCode: SourceCode, cache: Map<string, boolean>): boolean {
  const previous = cache.get("Array");
  if (previous !== undefined) return previous;
  const scope = globalScope(sourceCode);
  const untouched = binding.references.every(ordinaryArrayReference) && HOST_GLOBALS.every((name) => {
    const found = scope?.set.get(name);
    const host = found === undefined ? undefined : tsVariable(found);
    const unresolved = scope?.through.map(tsReference).filter((reference) => reference.identifier.name === name) ?? [];
    return (host === undefined || host.defs.length > 0 || host.references.every(ordinaryHostReference)) && unresolved.every(ordinaryHostReference);
  }) && namespaceReferences("Reflect", sourceCode).every(typeOnlyReference) &&
    namespaceReferences("Object", sourceCode).every((reference) => typeOnlyReference(reference) || ordinaryObjectUse(reference.identifier));
  cache.set("Array", untouched);
  return untouched;
}

/** Reflection or namespace aliases can reveal the same constructor without an Array read. */
function namespaceReferences(name: string, sourceCode: SourceCode): readonly TsReference[] {
  const scope = globalScope(sourceCode);
  const found = scope?.set.get(name);
  const binding = found === undefined ? undefined : tsVariable(found);
  const known = binding?.defs.length === 0 ? binding.references : [];
  const unresolved = scope?.through.map(tsReference).filter((reference) => reference.identifier.name === name) ?? [];
  return [...known, ...unresolved];
}

function typeOnlyReference(reference: TsReference): boolean {
  return !reference.isWrite() && reference.isTypeReference && !reference.isValueReference;
}

function ordinaryObjectUse(node: Node): boolean {
  const member = parentOf(node);
  if (member?.type !== "MemberExpression" || member.object !== node) return false;
  const name = getPropertyName(member);
  return name !== null && !OBJECT_REFLECTION.has(name);
}

/** Extracted methods, aliases, writes and namespace arguments lose native ownership. */
function ordinaryArrayReference(reference: TsReference): boolean {
  if (reference.isWrite()) return false;
  if (reference.isTypeReference && !reference.isValueReference) return true;
  return ordinaryArrayUse(reference.identifier);
}

function ordinaryArrayUse(node: Node): boolean {
  const member = parentOf(node);
  if (member?.type === "TSTypeQuery") return true;
  if (member?.type !== "MemberExpression" || member.object !== node || member.optional || getPropertyName(member) !== "isArray") return false;
  const call = parentOf(member);
  return call?.type === "CallExpression" && call.callee === member && !call.optional;
}

/** A visible host alias can replace the same constructor through another spelling. */
function ordinaryHostReference(reference: TsReference): boolean {
  if (reference.isWrite()) return false;
  if (reference.isTypeReference && !reference.isValueReference) return true;
  let node: Node = reference.identifier;
  for (let parent = parentOf(node); parent?.type === "MemberExpression" && parent.object === node; parent = parentOf(node)) {
    const member: ESTree.MemberExpression = parent;
    const name = getPropertyName(member);
    if (name === null) return false;
    if (name === "Array") return ordinaryArrayUse(member);
    if (name === "Reflect") return false;
    if (name === "Object") return ordinaryObjectUse(member);
    if (!HOST_GLOBALS.some((host) => host === name)) return true;
    node = member;
  }
  return false;
}
