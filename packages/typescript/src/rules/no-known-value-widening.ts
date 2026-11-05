/**
 * @fileoverview no-known-value-widening — retain evidence in local values.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-known-value-widening.test.ts
 */

import { getTypeServices, type TypeServices, type TypeScriptSourceCode } from "./_eslint-rule.js";


import { ASTUtils, AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";
import ts from "typescript";

import { retainsNamedTypeUses } from "./_type-binding.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { hasIdentifierNamed, isUnusedPrivateBinding } from "./_unused-private-binding.js";
import { outerExpression } from "./_unwrap-expression.js";
import { stableValueBinding, typeOnlyReference, writtenMember } from "./_stable-value-binding.js";
import { isGeneratedFile } from "./_paths.js";

export const NO_KNOWN_VALUE_WIDENING_DOCUMENTATION = {
  summary: "Preserve a known value's contract instead of widening a local binding to unknown, object, or an unknown-valued dictionary.",
  rationale: "Erasing a typed value's fields forces downstream code to rediscover the same contract through casts, reflection, or representation checks.",
  remediation: "Keep the inferred type, select the required domain fields, or use satisfies to check compatibility without erasing evidence.",
  category: "maintainability",
  requiresTypeInformation: true,
  references: ["https://github.com/dmmulroy/anti-slop/blob/13909c9e07590f5a85d93c62712259fe14a883f7/src/rules/no-known-value-widening.ts"],
  autofix: "safe",
  limitations: [
    "Requires TypeScript type information. Checks annotated local const bindings with independently known identifier, nonempty literal or monomorphic-call initializers; complete readonly private field writes and proven closed literal registries are also inspected. Parameters, direct exports, computed SDK/schema contracts, uncertain contextual inference and assertions are excluded.",
    "Known-value erasure checks target unknown, object, and index-only dictionaries with unknown values. Separate finite-key guidance applies to proven closed registries with concrete values. Typed dynamic registries, finite-key records, empty accumulators, unknown external input and incomplete private-field write sets are preserved. Finite-key guidance requires a closed local literal with no mutations, escapes or unknown invocation receivers.",
    "Intentional type erasure at a real abstraction boundary needs a local suppression explaining that boundary. New initializer, field and registry cases remain manual. Automatic fixes remove the annotation only from an unused private identifier-initialized binding in a module or block; referenced bindings retain their declared contract for manual review.",
  ],
  examples: [
    { id: "erased-tool", title: "A dictionary erases a known tool contract", outcome: "match", files: [{ path: "src/tool.ts", source: "type Tool = { name: string; enabled: boolean };\ndeclare const tool: Tool;\nconst fields: Record<string, unknown> = tool;" }], focusPath: "src/tool.ts", expectedCount: 1, public: true },
    { id: "retained-tool", title: "Retain the tool's fields", outcome: "no-match", files: [{ path: "src/tool.ts", source: "type Tool = { name: string; enabled: boolean };\ndeclare const tool: Tool;\nconst fields = tool;" }], focusPath: "src/tool.ts", expectedCount: 0, public: true },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; declare const tool: { name: string }; const fields: unknown = tool;" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; declare const tool: { name: string }; const fields = tool;" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
    {"id": "finite-registry-before", "scenarioId": "finite-registry", "title": "Preserve a closed registry key set — before", "outcome": "match", "files": [{"path": "src/example.ts", "source": "const handlers: Record<string, () => void> = { start() {} }; handlers.start();"}], "focusPath": "src/example.ts", "expectedCount": 1, "public": true},
    {"id": "finite-registry-after", "scenarioId": "finite-registry", "title": "Preserve a closed registry key set — after", "outcome": "no-match", "files": [{"path": "src/example.ts", "source": "type Command = 'start'; const handlers = { start() {} } satisfies Record<Command, () => void>; handlers.start();"}], "focusPath": "src/example.ts", "expectedCount": 0, "public": true},
    {"id": "private-storage-before", "scenarioId": "private-storage", "title": "Retain a completely owned storage contract — before", "outcome": "match", "files": [{"path": "src/example.ts", "source": "class Store { readonly #value: unknown = { id: 'u1' }; read() { return this.#value; } }"}], "focusPath": "src/example.ts", "expectedCount": 1, "public": true},
    {"id": "private-storage-after", "scenarioId": "private-storage", "title": "Retain a completely owned storage contract — after", "outcome": "no-match", "files": [{"path": "src/example.ts", "source": "class Store { readonly #value = { id: 'u1' }; read() { return this.#value; } }"}], "focusPath": "src/example.ts", "expectedCount": 0, "public": true},
    {"id": "factory-initializer-before", "scenarioId": "factory-initializer", "title": "Retain the monomorphic factory contract — before", "outcome": "match", "files": [{"path": "src/example.ts", "source": "declare function load(): { id: string }; const value: unknown = load();"}], "focusPath": "src/example.ts", "expectedCount": 1, "public": true},
    {"id": "factory-initializer-after", "scenarioId": "factory-initializer", "title": "Retain the monomorphic factory contract — after", "outcome": "no-match", "files": [{"path": "src/example.ts", "source": "declare function load(): { id: string }; const value = load();"}], "focusPath": "src/example.ts", "expectedCount": 0, "public": true},
    {"id": "literal-initializer-before", "scenarioId": "literal-initializer", "title": "Retain the independently known literal contract — before", "outcome": "match", "files": [{"path": "src/example.ts", "source": "const value: unknown = { id: 'u1' };"}], "focusPath": "src/example.ts", "expectedCount": 1, "public": true},
    {"id": "literal-initializer-after", "scenarioId": "literal-initializer", "title": "Retain the independently known literal contract — after", "outcome": "no-match", "files": [{"path": "src/example.ts", "source": "const value = { id: 'u1' };"}], "focusPath": "src/example.ts", "expectedCount": 0, "public": true},
  ],
} as const satisfies RuleDocumentation;

function erasesContract(type: ts.Type, checker: ts.TypeChecker): boolean {
  if ((type.flags & (ts.TypeFlags.Unknown | ts.TypeFlags.NonPrimitive)) !== 0) return true;
  const indexes = checker.getIndexInfosOfType(type);
  return indexes.length > 0 && checker.getPropertiesOfType(type).length === 0 &&
    indexes.every((index) => (index.type.flags & ts.TypeFlags.Unknown) !== 0);
}

function hasUnknownContract(type: ts.Type, checker: ts.TypeChecker): boolean {
  if (type.isUnionOrIntersection()) return type.types.some((part) => hasUnknownContract(part, checker));
  return (type.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown | ts.TypeFlags.Never | ts.TypeFlags.TypeParameter | ts.TypeFlags.Conditional | ts.TypeFlags.IndexedAccess | ts.TypeFlags.Substitution)) !== 0 || erasesContract(type, checker);
}


function independentInitializer(node: TSESTree.Expression, services: TypeServices, checker: ts.TypeChecker): boolean {
  if (node.type === AST_NODE_TYPES.Identifier) return true;
  if (node.type === AST_NODE_TYPES.AwaitExpression) return independentInitializer(node.argument, services, checker);
  if (node.type === AST_NODE_TYPES.CallExpression) {
    const signature = checker.getResolvedSignature(services.esTreeNodeToTSNodeMap.get(node));
    const declaration = signature?.declaration;
    return declaration !== undefined && declaration.typeParameters === undefined &&
      signature !== undefined && (checker.getReturnTypeOfSignature(signature).flags & ts.TypeFlags.Void) === 0;
  }
  if (node.type === AST_NODE_TYPES.ObjectExpression) return node.properties.length > 0 &&
    node.properties.every(property => property.type === AST_NODE_TYPES.Property && !property.computed &&
      property.kind === "init" && !property.method &&
      property.value.type !== AST_NODE_TYPES.ArrowFunctionExpression &&
      property.value.type !== AST_NODE_TYPES.FunctionExpression);
  if (node.type === AST_NODE_TYPES.ArrayExpression) return node.elements.length > 0 &&
    node.elements.every(element => element !== null && element.type !== AST_NODE_TYPES.SpreadElement &&
      element.type !== AST_NODE_TYPES.ArrowFunctionExpression && element.type !== AST_NODE_TYPES.FunctionExpression);
  return node.type === AST_NODE_TYPES.Literal && node.value !== null;
}

function computedContract(node: ts.Node, checker: ts.TypeChecker, seen = new Set<ts.Symbol>()): boolean {
  if (ts.isIndexedAccessTypeNode(node) || ts.isConditionalTypeNode(node) || ts.isTypeQueryNode(node)) return true;
  if (ts.isParenthesizedTypeNode(node)) return computedContract(node.type, checker, seen);
  if (ts.isUnionTypeNode(node) || ts.isIntersectionTypeNode(node))
    return node.types.some(part => computedContract(part, checker, seen));
  if (!ts.isTypeReferenceNode(node)) return false;
  const reference = checker.getSymbolAtLocation(node.typeName);
  if (reference === undefined) return true;
  const symbol = (reference.flags & ts.SymbolFlags.Alias) !== 0 ? checker.getAliasedSymbol(reference) : reference;
  if (seen.has(symbol)) return true;
  seen.add(symbol);
  return symbol.getDeclarations()?.some(declaration => ts.isTypeAliasDeclaration(declaration) &&
    computedContract(declaration.type, checker, seen)) ?? false;
}

function receiverIsUnobserved(symbol: ts.Symbol, checker: ts.TypeChecker): boolean {
  const seen = new Set<ts.Symbol>();
  function inspect(current: ts.Symbol): boolean {
    if (seen.has(current)) return false;
    seen.add(current);
    if ((current.flags & ts.SymbolFlags.Alias) !== 0) return inspect(checker.getAliasedSymbol(current));
    const declarations = current.getDeclarations();
    if (declarations === undefined || declarations.length !== 1) return false;
    const declaration = declarations[0];
    if (declaration === undefined) return false;
    if (ts.isPropertyAssignment(declaration) || ts.isVariableDeclaration(declaration)) {
      const value = declaration.initializer;
      if (value === undefined) return false;
      if (ts.isIdentifier(value)) {
        const owner = checker.getSymbolAtLocation(value);
        return owner !== undefined && inspect(owner);
      }
      return functionDoesNotUseReceiver(value);
    }
    return functionDoesNotUseReceiver(declaration);
  }
  function functionDoesNotUseReceiver(node: ts.Node): boolean {
    if (!ts.isFunctionDeclaration(node) && !ts.isFunctionExpression(node) &&
      !ts.isArrowFunction(node) && !ts.isMethodDeclaration(node)) return false;
    if (node.body === undefined) return false;
    let unobserved = true;
    function visit(current: ts.Node): void {
      if (!unobserved) return;
      if (current.kind === ts.SyntaxKind.ThisKeyword ||
        ts.isIdentifier(current) && current.text === "eval") {
        unobserved = false;
        return;
      }
      ts.forEachChild(current, visit);
    }
    visit(node.body);
    return unobserved;
  }
  return inspect(symbol);
}

function closedRegistry(
  node: TSESTree.VariableDeclarator,
  source: Readonly<TypeScriptSourceCode>,
  sourceType: ts.Type,
  targetType: ts.Type,
  checker: ts.TypeChecker,
): boolean {
  if (node.id.type !== AST_NODE_TYPES.Identifier || node.init?.type !== AST_NODE_TYPES.ObjectExpression ||
    node.init.properties.length === 0 || node.init.properties.some(property =>
      property.type !== AST_NODE_TYPES.Property || property.computed || property.kind !== "init")) return false;
  const indexes = checker.getIndexInfosOfType(targetType);
  if (targetType.getProperties().length > 0 || indexes.length === 0 ||
    indexes.some(index => hasUnknownContract(index.type, checker))) return false;
  const identifier = node.id;
  const variable = source.getDeclaredVariables(node).find(candidate => candidate.identifiers.includes(identifier));
  if (variable === undefined || variable.scope.type === "global" || !stableValueBinding(variable) ||
    !variable.references.some(reference => reference.isRead() || typeOnlyReference(reference))) return false;
  return variable.references.every(reference => {
    if (reference.init === true || typeOnlyReference(reference)) return true;
    const value = outerExpression(reference.identifier);
    const member = value.parent;
    if (member === undefined) return false;
    if (member.type !== AST_NODE_TYPES.MemberExpression || member.object !== value ||
      writtenMember(member)) return false;
    const key = ASTUtils.getPropertyName(member);
    if (key === null) return false;
    const outer = outerExpression(member);
    if (outer.parent?.type !== AST_NODE_TYPES.CallExpression || outer.parent.callee !== outer) return true;
    const property = checker.getPropertyOfType(sourceType, key);
    return property === undefined || receiverIsUnobserved(property, checker);
  });
}

export default createRule<[], "widening" | "registry">({
  name: "no-known-value-widening",
  documentation: NO_KNOWN_VALUE_WIDENING_DOCUMENTATION,
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: { description: NO_KNOWN_VALUE_WIDENING_DOCUMENTATION.summary },
    schema: [],
    messages: {
      widening: "This annotation erases a known value's contract. Retain inference or use a domain contract instead of rediscovering fields through casts or runtime checks.",
      registry: "This closed registry loses its finite keys behind a string index. Preserve its keys with satisfies and an owned finite key union where available.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text)) return {};
    if (!context.sourceCode.parserServices?.program || !context.sourceCode.parserServices.esTreeNodeToTSNodeMap) return {};
    const services = getTypeServices(context);
    if (services.program === null) return {};
    const checker = services.program.getTypeChecker();
    return {
      VariableDeclarator(node: TSESTree.VariableDeclarator): void {
        if (node.id.type !== AST_NODE_TYPES.Identifier || !node.id.typeAnnotation || node.init === null ||
          node.parent.kind !== "const" || node.parent.parent.type === AST_NODE_TYPES.ExportNamedDeclaration) return;
        const source = checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(node.init));
        if (hasUnknownContract(source, checker)) return;
        const target = checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(node.id.typeAnnotation.typeAnnotation));
        const erased = erasesContract(target, checker) &&
          !computedContract(services.esTreeNodeToTSNodeMap.get(node.id.typeAnnotation.typeAnnotation), checker) &&
          independentInitializer(node.init, services, checker);
        const registry = !erased && !hasIdentifierNamed(context.sourceCode.ast, "eval") &&
          closedRegistry(node, context.sourceCode, source, target, checker);
        if (!erased && !registry) return;
        const annotation = node.id.typeAnnotation;
        const canFix = erased && node.init.type === AST_NODE_TYPES.Identifier &&
          isUnusedPrivateBinding(context.sourceCode, node, node.id, context.filename) &&
          context.sourceCode.getCommentsInside(annotation).length === 0 &&
          retainsNamedTypeUses(context.sourceCode, annotation);
        context.report({
          node: annotation,
          messageId: registry ? "registry" : "widening",
          fix: canFix ? (fixer) => fixer.replaceText(annotation,
            context.sourceCode.getText(annotation).replace(/[^\r\n]/gu, "")) : null,
        });
      },
      PropertyDefinition(node: TSESTree.PropertyDefinition): void {
        if (node.key.type !== AST_NODE_TYPES.PrivateIdentifier || !node.readonly || node.static ||
          node.value === null || node.typeAnnotation === undefined || node.decorators.length > 0 ||
          hasIdentifierNamed(context.sourceCode.ast, "eval") ||
          !independentInitializer(node.value, services, checker)) return;
        const owner = node.parent.parent;
        if ((owner.type !== AST_NODE_TYPES.ClassDeclaration && owner.type !== AST_NODE_TYPES.ClassExpression) ||
          owner.decorators.length > 0 || owner.superClass !== null) return;
        const declaration = services.esTreeNodeToTSNodeMap.get(node);
        const classNode = services.esTreeNodeToTSNodeMap.get(owner);
        if (!ts.isPropertyDeclaration(declaration) ||
          !ts.isClassDeclaration(classNode) && !ts.isClassExpression(classNode)) return;
        const field = checker.getSymbolAtLocation(declaration.name);
        const source = checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(node.value));
        const target = checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(node.typeAnnotation.typeAnnotation));
        if (field === undefined || hasUnknownContract(source, checker) || !erasesContract(target, checker) ||
          computedContract(services.esTreeNodeToTSNodeMap.get(node.typeAnnotation.typeAnnotation), checker)) return;
        let compatible = true;
        function isField(value: ts.Node): boolean {
          while (ts.isParenthesizedExpression(value) || ts.isAsExpression(value) ||
            ts.isTypeAssertionExpression(value) || ts.isNonNullExpression(value) || ts.isSatisfiesExpression(value))
            value = value.expression;
          return ts.isPropertyAccessExpression(value) && checker.getSymbolAtLocation(value.name) === field;
        }
        function containsField(current: ts.Node): boolean {
          return isField(current) || ts.forEachChild(current, containsField) === true;
        }
        function inspect(current: ts.Node): void {
          if (!compatible) return;
          if (ts.isBinaryExpression(current) && current.operatorToken.kind >= ts.SyntaxKind.FirstAssignment &&
            current.operatorToken.kind <= ts.SyntaxKind.LastAssignment && isField(current.left)) {
            const value = checker.getTypeAtLocation(current.right);
            compatible = current.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
              !hasUnknownContract(value, checker) &&
              checker.isTypeAssignableTo(source, value) && checker.isTypeAssignableTo(value, source);
          } else if (ts.isBinaryExpression(current) && current.operatorToken.kind >= ts.SyntaxKind.FirstAssignment &&
            current.operatorToken.kind <= ts.SyntaxKind.LastAssignment && containsField(current.left)) compatible = false;
          else if ((ts.isPrefixUnaryExpression(current) || ts.isPostfixUnaryExpression(current)) &&
            (current.operator === ts.SyntaxKind.PlusPlusToken || current.operator === ts.SyntaxKind.MinusMinusToken) &&
            containsField(current.operand)) compatible = false;
          else if ((ts.isForOfStatement(current) || ts.isForInStatement(current)) &&
            containsField(current.initializer)) compatible = false;
          ts.forEachChild(current, inspect);
        }
        inspect(classNode);
        if (compatible) context.report({ node: node.typeAnnotation, messageId: "widening" });
      },
    };
  },
});
