/**
 * @fileoverview existing-type-alias-fix — reuse an existing context-free alias.
 *
 * Port of the 18.x `_existing-type-alias-fix.ts` helper. Oxlint sets an absent
 * `typeParameters` or `TSPropertySignature.typeAnnotation` to `null` where
 * TS-ESTree leaves it `undefined`; both count as absent here. The alias index
 * is cached per `sourceCode.ast`, because Oxlint reuses one `SourceCode` object
 * for every file.
 */

import type { ESTree, Node, SourceCode, TsVariable } from "../types.js";
import { tsVariable } from "../types.js";
import { findVariable } from "./static-string.js";
import { findTypeBinding } from "./type-binding.js";

const PRIMITIVE_TYPES: ReadonlySet<string> = new Set([
  "TSStringKeyword",
  "TSNumberKeyword",
  "TSBooleanKeyword",
  "TSBigIntKeyword",
  "TSSymbolKeyword",
  "TSNullKeyword",
  "TSUndefinedKeyword",
  "TSNeverKeyword",
  "TSUnknownKeyword",
  "TSAnyKeyword",
  "TSObjectKeyword",
]);

interface AliasCandidate {
  readonly identifier: ESTree.BindingIdentifier;
  readonly binding: TsVariable;
}
type AliasIndex = ReadonlyMap<string, readonly AliasCandidate[]>;
const ALIASES = new WeakMap<ESTree.Program, AliasIndex>();

/** Reuse one existing alias from proven equivalent declarations or exact exported token matches. */
export function existingTypeAliasFix(
  sourceCode: Readonly<SourceCode>,
  annotation: ESTree.TSType,
  equivalentAliases?: readonly ESTree.TSTypeAliasDeclaration[],
): string | null {
  if (!closedType(annotation) || sourceCode.getCommentsInside(annotation).length > 0) return null;
  const candidates = equivalentAliases === undefined
    ? aliasIndex(sourceCode).get(tokenSignature(sourceCode, annotation)) ?? []
    : equivalentAliases.map((alias) => aliasCandidate(sourceCode, alias, true));
  if (candidates.length === 0) return null;
  const scope = sourceCode.getScope(annotation);
  const resolve = equivalentAliases === undefined ? findVariable : findTypeBinding;
  let name: string | null = null;
  for (const candidate of candidates) {
    if (candidate === null || resolve(scope, candidate.identifier.name) !== candidate.binding) continue;
    if (name !== null) return null;
    name = sourceCode.getText(candidate.identifier);
  }
  return name;
}

function aliasCandidate(
  sourceCode: Readonly<SourceCode>,
  alias: ESTree.TSTypeAliasDeclaration,
  typeNamespaceOnly = false,
): AliasCandidate | null {
  if (alias.typeParameters != null) return null;
  const declared = sourceCode.getDeclaredVariables(alias).find((variable) => variable.name === alias.id.name);
  if (declared === undefined) return null;
  const binding = tsVariable(declared);
  const definitions = typeNamespaceOnly ? binding.defs.filter((definition) => definition.isTypeDefinition) : binding.defs;
  if (definitions.length !== 1 || definitions[0]?.node !== alias) return null;
  return { identifier: alias.id, binding };
}

function aliasIndex(sourceCode: Readonly<SourceCode>): AliasIndex {
  const cached = ALIASES.get(sourceCode.ast);
  if (cached !== undefined) return cached;
  const index = new Map<string, AliasCandidate[]>();
  for (const statement of sourceCode.ast.body) {
    if (statement.type !== "ExportNamedDeclaration" || statement.declaration?.type !== "TSTypeAliasDeclaration")
      continue;
    const alias = statement.declaration;
    if (sourceCode.getCommentsInside(alias).length > 0 || !closedType(alias.typeAnnotation)) continue;
    const candidate = aliasCandidate(sourceCode, alias);
    if (candidate === null) continue;
    const signature = tokenSignature(sourceCode, alias.typeAnnotation);
    const candidates = index.get(signature) ?? [];
    candidates.push(candidate);
    index.set(signature, candidates);
  }
  ALIASES.set(sourceCode.ast, index);
  return index;
}

function tokenSignature(sourceCode: Readonly<SourceCode>, node: Node): string {
  return JSON.stringify(sourceCode.getTokens(node).map((token) => [token.type, token.value]));
}

function closedType(node: Node): boolean {
  if (PRIMITIVE_TYPES.has(node.type)) return true;
  switch (node.type) {
    case "TSLiteralType":
      return (
        node.literal.type === "Literal" ||
        (node.literal.type === "UnaryExpression" &&
          node.literal.operator === "-" &&
          node.literal.argument.type === "Literal")
      );
    case "TSUnionType":
      return node.types.every(closedType);
    case "TSTypeLiteral":
      return node.members.every(
        (member) =>
          member.type === "TSPropertySignature" &&
          !member.computed &&
          member.typeAnnotation != null &&
          closedType(member.typeAnnotation.typeAnnotation),
      );
    case "TSArrayType":
      return closedType(node.elementType);
    case "TSTypeOperator":
      return node.operator === "readonly" && node.typeAnnotation != null && closedType(node.typeAnnotation);
    default:
      return false;
  }
}
