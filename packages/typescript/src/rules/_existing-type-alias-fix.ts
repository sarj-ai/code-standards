/**
 * @fileoverview _existing-type-alias-fix — reuse an existing context-free exported alias.
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

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
  readonly identifier: TSESTree.Identifier;
  readonly binding: TSESLint.Scope.Variable;
}
type AliasIndex = ReadonlyMap<string, readonly AliasCandidate[]>;
const ALIASES = new WeakMap<Readonly<TSESLint.SourceCode>, AliasIndex>();

/** Reuse one existing exported, context-free alias without introducing a domain name or export. */
export function existingTypeAliasFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  annotation: TSESTree.TypeNode,
): string | null {
  if (
    !closedType(annotation) ||
    sourceCode.getCommentsInside(annotation).length > 0
  )
    return null;
  const signature = tokenSignature(sourceCode, annotation);
  const matches: string[] = [];
  for (const candidate of aliasIndex(sourceCode).get(signature) ?? []) {
    if (
      ASTUtils.findVariable(
        sourceCode.getScope(annotation),
        candidate.identifier.name,
      ) !== candidate.binding
    )
      continue;
    matches.push(sourceCode.getText(candidate.identifier));
    if (matches.length > 1) return null;
  }
  return matches[0] ?? null;
}

function aliasIndex(sourceCode: Readonly<TSESLint.SourceCode>): AliasIndex {
  const cached = ALIASES.get(sourceCode);
  if (cached !== undefined) return cached;
  const index = new Map<string, AliasCandidate[]>();
  for (const statement of sourceCode.ast.body) {
    if (
      statement.type !== AST_NODE_TYPES.ExportNamedDeclaration ||
      statement.declaration?.type !== AST_NODE_TYPES.TSTypeAliasDeclaration
    )
      continue;
    const alias = statement.declaration;
    if (
      alias.typeParameters !== undefined ||
      sourceCode.getCommentsInside(alias).length > 0 ||
      !closedType(alias.typeAnnotation)
    )
      continue;
    const binding = sourceCode
      .getDeclaredVariables(alias)
      .find((variable) => variable.name === alias.id.name);
    if (
      binding === undefined ||
      binding.defs.length !== 1 ||
      binding.defs[0]?.node !== alias
    )
      continue;
    const signature = tokenSignature(sourceCode, alias.typeAnnotation);
    const candidates = index.get(signature) ?? [];
    candidates.push({ identifier: alias.id, binding });
    index.set(signature, candidates);
  }
  ALIASES.set(sourceCode, index);
  return index;
}

function tokenSignature(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.Node,
): string {
  return JSON.stringify(
    sourceCode.getTokens(node).map((token) => [token.type, token.value]),
  );
}

function closedType(node: TSESTree.Node): boolean {
  if (PRIMITIVE_TYPES.has(node.type)) return true;
  switch (node.type) {
    case AST_NODE_TYPES.TSLiteralType:
      return (
        node.literal.type === AST_NODE_TYPES.Literal ||
        (node.literal.type === AST_NODE_TYPES.UnaryExpression &&
          node.literal.operator === "-" &&
          node.literal.argument.type === AST_NODE_TYPES.Literal)
      );
    case AST_NODE_TYPES.TSUnionType:
      return node.types.every(closedType);
    case AST_NODE_TYPES.TSTypeLiteral:
      return node.members.every(
        (member) =>
          member.type === AST_NODE_TYPES.TSPropertySignature &&
          !member.computed &&
          member.typeAnnotation !== undefined &&
          closedType(member.typeAnnotation.typeAnnotation),
      );
    case AST_NODE_TYPES.TSArrayType:
      return closedType(node.elementType);
    case AST_NODE_TYPES.TSTypeOperator:
      return (
        node.operator === "readonly" &&
        node.typeAnnotation !== undefined &&
        closedType(node.typeAnnotation)
      );
    default:
      return false;
  }
}
