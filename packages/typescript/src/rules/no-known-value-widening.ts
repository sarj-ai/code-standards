/**
 * @fileoverview no-known-value-widening — retain evidence in local values.
 *
 * Port of the 18.x `no-known-value-widening` rule. Typed: the original
 * returns no visitors without a program, so without tsrs (or when tsrs cannot
 * hold the file) this port reports nothing. The walk applies the original's
 * syntactic checks and collects candidates; `Program:exit` runs its type
 * checks over tsrs's checker, then reports.
 *
 * Under Oxlint the original crashes on a readonly `#field` without a type
 * annotation: it tests `node.typeAnnotation === undefined`, Oxlint gives
 * `null`, and it then reads `null.typeAnnotation`. This port treats both as
 * absent. Symbol identity (`seen`, field references) is by tsrs symbol id.
 */

import type * as TsrsAst from "tsrs/ast";
import type { Symbol as TsSymbol, Type } from "tsrs/sync";

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { tsVariable } from "../types.js";
import { outerExpression, parentOf } from "../utils/ast.js";
import { nativeTypes, type NativeTypes } from "../utils/checked-native-source.js";
import { docsUrl } from "../utils/docs-url.js";
import { isPresent } from "../utils/is-present.js";
import { isGeneratedFile } from "../utils/paths.js";
import { stableValueBinding, typeOnlyReference, writtenMember } from "../utils/stable-value-binding.js";
import { getPropertyName } from "../utils/static-string.js";
import { type TsrsServices, tsrsServices } from "../utils/tsrs-services.js";
import { retainsNamedTypeUses } from "../utils/type-binding.js";
import { hasIdentifierNamed, isUnusedPrivateBinding } from "../utils/unused-private-binding.js";

const NAME = "no-known-value-widening";
// Annotations whose type has properties (primitives, literals and arrays through their apparent types)
// or no index signature (any, never, null, undefined, void) never erase a contract, and a registry
// needs an object literal, so declarators with them and another initializer need no types.
const PROPERTIED_ANNOTATIONS: ReadonlySet<string> = new Set([
  "TSAnyKeyword", "TSArrayType", "TSBigIntKeyword", "TSBooleanKeyword", "TSLiteralType", "TSNeverKeyword", "TSNullKeyword",
  "TSNumberKeyword", "TSStringKeyword", "TSSymbolKeyword", "TSTemplateLiteralType", "TSTupleType", "TSUndefinedKeyword", "TSVoidKeyword",
]);

type TsNode = TsrsAst.Node;

function erasesContract(type: Type, native: NativeTypes): boolean {
  const flags = native.sync.TypeFlags;
  if ((type.flags & (flags.Unknown | flags.NonPrimitive)) !== 0) return true;
  const indexes = native.checker.getIndexInfosOfType(type);
  return indexes.length > 0 && native.checker.getPropertiesOfType(type).length === 0 &&
    indexes.every((index) => (index.valueType.flags & flags.Unknown) !== 0);
}

function hasUnknownContract(type: Type, native: NativeTypes): boolean {
  const flags = native.sync.TypeFlags;
  if (type.isUnionType() || type.isIntersectionType()) return type.getTypes().some((part) => hasUnknownContract(part, native));
  return (type.flags & (flags.Any | flags.Unknown | flags.Never | flags.TypeParameter | flags.Conditional | flags.IndexedAccess | flags.Substitution)) !== 0 ||
    erasesContract(type, native);
}

function independentInitializer(node: Node, native: NativeTypes): boolean {
  if (node.type === "Identifier") return true;
  if (node.type === "AwaitExpression") return independentInitializer(node.argument, native);
  if (node.type === "CallExpression") {
    const call = native.node(node);
    if (call === undefined) return false;
    const signature = native.checker.getResolvedSignature(call);
    const handle = signature?.declaration;
    const declaration = handle?.resolve() as (TsNode & { readonly typeParameters?: unknown }) | undefined;
    return declaration !== undefined && !isPresent(declaration.typeParameters) &&
      (native.checker.getReturnTypeOfSignature(signature).flags & native.sync.TypeFlags.Void) === 0;
  }
  if (node.type === "ObjectExpression") return node.properties.length > 0 &&
    node.properties.every((property) => property.type === "Property" && !property.computed &&
      property.kind === "init" && !property.method &&
      property.value.type !== "ArrowFunctionExpression" &&
      property.value.type !== "FunctionExpression");
  if (node.type === "ArrayExpression") return node.elements.length > 0 &&
    node.elements.every((element) => element !== null && element.type !== "SpreadElement" &&
      element.type !== "ArrowFunctionExpression" && element.type !== "FunctionExpression");
  return node.type === "Literal" && node.value !== null;
}

function computedContract(node: TsNode, native: NativeTypes, seen = new Set<number>()): boolean {
  const { ast, checker, sync } = native;
  if (ast.isIndexedAccessTypeNode(node) || ast.isConditionalTypeNode(node) || ast.isTypeQueryNode(node)) return true;
  if (ast.isParenthesizedTypeNode(node)) return computedContract(node.type, native, seen);
  if (ast.isUnionTypeNode(node) || ast.isIntersectionTypeNode(node)) return node.types.some((part) => computedContract(part, native, seen));
  if (!ast.isTypeReferenceNode(node)) return false;
  const reference = checker.getSymbolAtLocation(node.typeName);
  if (reference === undefined) return true;
  const symbol = (reference.flags & sync.SymbolFlags.Alias) !== 0 ? checker.getAliasedSymbol(reference) : reference;
  if (seen.has(symbol.id)) return true;
  seen.add(symbol.id);
  return symbol.declarations.some((handle) => {
    if (handle.kind !== ast.SyntaxKind.TypeAliasDeclaration) return false;
    const declaration = handle.resolve();
    return declaration !== undefined && ast.isTypeAliasDeclaration(declaration) && computedContract(declaration.type, native, seen);
  });
}

function receiverIsUnobserved(symbol: TsSymbol, native: NativeTypes): boolean {
  const { ast, checker, sync } = native;
  const seen = new Set<number>();
  function inspect(current: TsSymbol): boolean {
    if (seen.has(current.id)) return false;
    seen.add(current.id);
    if ((current.flags & sync.SymbolFlags.Alias) !== 0) return inspect(checker.getAliasedSymbol(current));
    const declarations = current.declarations;
    if (declarations.length !== 1) return false;
    const declaration = declarations[0]?.resolve();
    if (declaration === undefined) return false;
    if (ast.isPropertyAssignment(declaration) || ast.isVariableDeclaration(declaration)) {
      const value = declaration.initializer;
      if (value === undefined) return false;
      if (ast.isIdentifier(value)) {
        const owner = checker.getSymbolAtLocation(value);
        return owner !== undefined && inspect(owner);
      }
      return functionDoesNotUseReceiver(value);
    }
    return functionDoesNotUseReceiver(declaration);
  }
  function functionDoesNotUseReceiver(node: TsNode): boolean {
    if (!ast.isFunctionDeclaration(node) && !ast.isFunctionExpression(node) &&
      !ast.isArrowFunction(node) && !ast.isMethodDeclaration(node)) return false;
    if (node.body === undefined) return false;
    let unobserved = true;
    function visit(current: TsNode): undefined {
      if (!unobserved) return undefined;
      if (current.kind === ast.SyntaxKind.ThisKeyword || ast.isIdentifier(current) && current.text === "eval") {
        unobserved = false;
        return undefined;
      }
      current.forEachChild(visit);
      return undefined;
    }
    visit(node.body);
    return unobserved;
  }
  return inspect(symbol);
}

function closedRegistry(node: ESTree.VariableDeclarator, source: SourceCode, sourceType: Type, targetType: Type, native: NativeTypes): boolean {
  const { checker } = native;
  if (node.id.type !== "Identifier" || node.init?.type !== "ObjectExpression" ||
    node.init.properties.length === 0 || node.init.properties.some((property) =>
      property.type !== "Property" || property.computed || property.kind !== "init")) return false;
  const indexes = checker.getIndexInfosOfType(targetType);
  if (targetType.getProperties().length > 0 || indexes.length === 0 ||
    indexes.some((index) => hasUnknownContract(index.valueType, native))) return false;
  const identifier = node.id;
  const found = source.getDeclaredVariables(node).find((candidate) => candidate.identifiers.includes(identifier));
  const variable = found === undefined ? undefined : tsVariable(found);
  if (variable === undefined || variable.scope.type === "global" || !stableValueBinding(variable) ||
    !variable.references.some((reference) => reference.isRead() || typeOnlyReference(reference))) return false;
  return variable.references.every((reference) => {
    if (reference.init === true || typeOnlyReference(reference)) return true;
    const value = outerExpression(reference.identifier);
    const member = parentOf(value);
    if (member === null) return false;
    if (member.type !== "MemberExpression" || member.object !== value || writtenMember(member)) return false;
    const key = getPropertyName(member);
    if (key === null) return false;
    const outer = outerExpression(member);
    const call = parentOf(outer);
    if (call?.type !== "CallExpression" || call.callee !== outer) return true;
    const property = checker.getPropertyOfType(sourceType, key);
    return property === undefined || receiverIsUnobserved(property, native);
  });
}

/** Every write to the field inside its class assigns a value of exactly the initializer's type. */
function fieldWritesKeepType(classNode: TsNode, fieldAccesses: ReadonlySet<TsNode>, source: Type, native: NativeTypes): boolean {
  const { ast, checker } = native;
  const kinds = ast.SyntaxKind;
  function hasChangingWrite(current: TsNode): boolean {
    return !keepsType(current) || current.forEachChild(hasChangingWrite) === true;
  }
  function keepsType(current: TsNode): boolean {
    if (ast.isBinaryExpression(current) &&
      current.operatorToken.kind >= kinds.FirstAssignment && current.operatorToken.kind <= kinds.LastAssignment) {
      if (!isField(current.left)) return !containsField(current.left);
      const value = checker.getTypeAtLocation(current.right);
      return current.operatorToken.kind === kinds.EqualsToken && !hasUnknownContract(value, native) &&
        checker.isTypeAssignableTo(source, value) && checker.isTypeAssignableTo(value, source);
    }
    if ((ast.isPrefixUnaryExpression(current) || ast.isPostfixUnaryExpression(current)) &&
      (current.operator === kinds.PlusPlusToken || current.operator === kinds.MinusMinusToken)) return !containsField(current.operand);
    if (ast.isForOfStatement(current) || ast.isForInStatement(current)) return !containsField(current.initializer);
    return true;
  }
  function containsField(current: TsNode): boolean {
    return isField(current) || current.forEachChild(containsField) === true;
  }
  function isField(value: TsNode): boolean {
    while (ast.isParenthesizedExpression(value) || ast.isAsExpression(value) ||
      ast.isTypeAssertion(value) || ast.isNonNullExpression(value) || ast.isSatisfiesExpression(value)) value = value.expression;
    return ast.isPropertyAccessExpression(value) && fieldAccesses.has(value);
  }
  return !hasChangingWrite(classNode);
}

interface DeclaratorCandidate {
  readonly kind: "declarator";
  readonly node: ESTree.VariableDeclarator & { readonly id: ESTree.BindingIdentifier; readonly init: ESTree.Expression };
  readonly annotation: ESTree.TSTypeAnnotation;
}

interface FieldCandidate {
  readonly kind: "field";
  readonly node: ESTree.PropertyDefinition & { readonly value: ESTree.Expression };
  readonly annotation: ESTree.TSTypeAnnotation;
  readonly owner: ESTree.Class;
}

interface DeclaratorTypes {
  readonly source: Type;
  readonly target: Type;
  readonly targetNode: TsNode;
}

/**
 * The initializer and annotation types of every declarator, in one request. The original asks
 * for them a declarator at a time, and for the annotation only after the initializer passes.
 */
function declaratorTypes(candidates: readonly (DeclaratorCandidate | FieldCandidate)[], native: NativeTypes): Map<DeclaratorCandidate, DeclaratorTypes> {
  const found: { candidate: DeclaratorCandidate; init: TsNode; targetNode: TsNode }[] = [];
  for (const candidate of candidates) {
    if (candidate.kind !== "declarator") continue;
    const init = native.node(candidate.node.init);
    const targetNode = native.outerNode(candidate.annotation.typeAnnotation);
    if (init !== undefined && targetNode !== undefined) found.push({ candidate, init, targetNode });
  }
  const types = found.length === 0 ? [] : native.checker.getTypeAtLocation(found.flatMap(({ init, targetNode }) => [init, targetNode]));
  const byCandidate = new Map<DeclaratorCandidate, DeclaratorTypes>();
  found.forEach(({ candidate, targetNode }, i) => {
    const source = types[2 * i];
    const target = types[2 * i + 1];
    if (source !== undefined && target !== undefined) byCandidate.set(candidate, { source, target, targetNode });
  });
  return byCandidate;
}

interface Finding {
  readonly annotation: ESTree.TSTypeAnnotation;
  readonly messageId: "widening" | "registry";
  readonly canFix: boolean;
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Preserve a known value's contract instead of widening a local binding to unknown, object, or an unknown-valued dictionary.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      widening: "This annotation erases a known value's contract. Retain inference or use a domain contract instead of rediscovering fields through casts or runtime checks.",
      registry: "This closed registry loses its finite keys behind a string index. Preserve its keys with satisfies and an owned finite key union where available.",
    },
  },
  createOnce(context) {
    let tsrs: TsrsServices | null = null;
    let candidates: (DeclaratorCandidate | FieldCandidate)[] = [];

    function declaratorFinding({ node, annotation }: DeclaratorCandidate, native: NativeTypes, types: DeclaratorTypes | undefined): Finding | undefined {
      const sourceCode = context.sourceCode;
      if (types === undefined) return undefined;
      const { source, target, targetNode } = types;
      if (hasUnknownContract(source, native)) return undefined;
      const erased = erasesContract(target, native) && !computedContract(targetNode, native) && independentInitializer(node.init, native);
      const registry = !erased && !hasIdentifierNamed(sourceCode, "eval") && closedRegistry(node, sourceCode, source, target, native);
      if (!erased && !registry) return undefined;
      const canFix = erased && node.init.type === "Identifier" &&
        isUnusedPrivateBinding(sourceCode, node, node.id, context.filename) &&
        sourceCode.getCommentsInside(annotation).length === 0 &&
        retainsNamedTypeUses(sourceCode, annotation);
      return { annotation, messageId: registry ? "registry" : "widening", canFix };
    }

    function fieldFinding({ node, annotation, owner }: FieldCandidate, native: NativeTypes): Finding | undefined {
      const { ast, checker } = native;
      if (!independentInitializer(node.value, native)) return undefined;
      const declaration = native.node(node);
      const classNode = native.node(owner);
      if (declaration === undefined || classNode === undefined || !ast.isPropertyDeclaration(declaration) ||
        !ast.isClassDeclaration(classNode) && !ast.isClassExpression(classNode)) return undefined;
      const field = checker.getSymbolAtLocation(declaration.name);
      const valueNode = native.node(node.value);
      const targetNode = native.outerNode(annotation.typeAnnotation);
      if (valueNode === undefined || targetNode === undefined) return undefined;
      const source = checker.getTypeAtLocation(valueNode);
      const target = checker.getTypeAtLocation(targetNode);
      if (field === undefined || hasUnknownContract(source, native) || !erasesContract(target, native) ||
        computedContract(targetNode, native)) return undefined;
      // The original asks for each property access's symbol as it walks; ask once for every access in the class.
      const accesses: TsrsAst.PropertyAccessExpression[] = [];
      const collect = (current: TsNode): undefined => {
        if (ast.isPropertyAccessExpression(current)) accesses.push(current);
        current.forEachChild(collect);
        return undefined;
      };
      collect(classNode);
      const symbols = accesses.length === 0 ? [] : checker.getSymbolAtLocation(accesses.map((access) => access.name));
      const fieldAccesses = new Set(accesses.filter((_, i) => symbols[i]?.id === field.id));
      return fieldWritesKeepType(classNode, fieldAccesses, source, native) ? { annotation, messageId: "widening", canFix: false } : undefined;
    }

    return {
      before() {
        tsrs = null;
        candidates = [];
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        tsrs = tsrsServices(context);
        return tsrs !== null;
      },
      VariableDeclarator(node) {
        const declaration = parentOf(node) as ESTree.VariableDeclaration;
        if (node.id.type !== "Identifier" || !isPresent(node.id.typeAnnotation) || node.init === null ||
          declaration.kind !== "const" || parentOf(declaration)?.type === "ExportNamedDeclaration") return;
        if (node.init.type !== "ObjectExpression" && PROPERTIED_ANNOTATIONS.has(node.id.typeAnnotation.typeAnnotation.type)) return;
        candidates.push({ kind: "declarator", node: node as DeclaratorCandidate["node"], annotation: node.id.typeAnnotation });
      },
      PropertyDefinition(node) {
        if (node.key.type !== "PrivateIdentifier" || node.readonly !== true || node.static ||
          node.value === null || !isPresent(node.typeAnnotation) || node.decorators.length > 0 ||
          hasIdentifierNamed(context.sourceCode, "eval")) return;
        const owner = parentOf(parentOf(node) as Node) as Node;
        if ((owner.type !== "ClassDeclaration" && owner.type !== "ClassExpression") ||
          owner.decorators.length > 0 || (owner.superClass ?? null) !== null) return;
        candidates.push({ kind: "field", node: node as FieldCandidate["node"], annotation: node.typeAnnotation, owner: owner });
      },
      "Program:exit"() {
        if (candidates.length === 0 || tsrs === null) return;
        const findings = tsrs.run((file) => {
          const native = nativeTypes(file);
          const types = declaratorTypes(candidates, native);
          return candidates.map((candidate) => candidate.kind === "declarator"
            ? declaratorFinding(candidate, native, types.get(candidate)) : fieldFinding(candidate, native));
        });
        if (findings === null) return;
        const sourceCode = context.sourceCode;
        for (const finding of findings) {
          if (finding === undefined) continue;
          const { annotation } = finding;
          context.report({
            node: annotation,
            messageId: finding.messageId,
            ...(finding.canFix && { fix: (fixer) => fixer.replaceText(annotation, sourceCode.getText(annotation).replace(/[^\r\n]/gu, "")) }),
          });
        }
      },
    };
  },
});
