/**
 * @fileoverview require-explicit-contract-implementation — Detect structural substitutes rejected by nominal runtime guards.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-explicit-contract-implementation.test.ts
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";
import * as ts from "typescript";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "declareActualContract";
type Options = readonly [];

export const REQUIRE_EXPLICIT_CONTRACT_IMPLEMENTATION_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Require nominal inheritance when an injected abstract class is rejected by an instanceof guard.",
  rationale: "A structurally assignable fake can still fail a constructor's nominal runtime guard. Pure structural interfaces do not require an implements clause.",
  remediation: "Use an implementation inheriting the existing abstract class, or remove the nominal guard if the boundary is intentionally structural.",
  category: "architecture",
  autofix: "none",
  limitations: [
    "Requires direct construction of both owned consumer and collaborator classes, with a first-statement consumer constructor guard rejecting the exact parameter with if (!(parameter instanceof Contract)) throw.",
    "The contract must resolve to an abstract class without decorators, unresolved ancestors, or custom computed static members in its resolved hierarchy.",
    "Structural interfaces, non-rejecting branches, reassignment before the guard, casts, unresolved heritage, dynamic factories, explicit implementation constructors or initializers, modules referencing prototype-mutator members or assigning prototypes, and third-party classes are excluded.",
  ],
  examples: [
    {
      id: "runtime-nominal-guard-with-structural-fake",
      title: "A structurally compatible fake fails the constructor's runtime guard",
      outcome: "match",
      files: [{ path: "src/service.ts", source: "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher { publish() {} } new Consumer(new FakePublisher());" }],
      focusPath: "src/service.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "runtime-nominal-guard-with-inherited-fake",
      title: "The fake satisfies the existing nominal runtime contract",
      outcome: "no-match",
      files: [{ path: "src/service.ts", source: "abstract class Publisher { abstract publish(): void } class Consumer { constructor(readonly publisher: Publisher) { if (!(publisher instanceof Publisher)) throw new TypeError('Nominal publisher required'); } } class FakePublisher extends Publisher { publish() {} } new Consumer(new FakePublisher());" }],
      focusPath: "src/service.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function behavioralContract(checker: ts.TypeChecker, type: ts.Type): ts.Type | null {
  if (type.isUnion()) {
    const substantive = type.types.filter((member) =>
      (member.flags & (ts.TypeFlags.Null | ts.TypeFlags.Undefined)) === 0);
    if (substantive.length !== 1) return null;
    return behavioralContract(checker, substantive[0]!);
  }
  if ((type.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown)) !== 0) return null;
  const declaration = type.getSymbol()?.declarations?.find((item) =>
    ts.isClassDeclaration(item) && item.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.AbstractKeyword));
  if (declaration === undefined) return null;
  return checker.getPropertiesOfType(type).some((property) => {
    if (!property.declarations?.some((member) => ts.isMethodSignature(member) || ts.isMethodDeclaration(member))) return false;
    const propertyType = checker.getTypeOfSymbolAtLocation(property, declaration);
    return propertyType.getCallSignatures().length > 0;
  }) ? type : null;
}

function ownedClass(checker: ts.TypeChecker, expression: ts.Node): ts.ClassDeclaration | null {
  if (!ts.isNewExpression(expression)) return null;
  const type = checker.getTypeAtLocation(expression);
  if ((type.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown)) !== 0) return null;
  const declaration = type.getSymbol()?.declarations?.find(ts.isClassDeclaration);
  const constructed = canonicalSymbol(checker, expression.expression)?.declarations?.find(ts.isClassDeclaration);
  if (declaration === undefined || declaration !== constructed || declaration.getSourceFile().isDeclarationFile ||
      /(?:^|[/\\])(?:node_modules|vendor|generated)(?:[/\\])/u.test(declaration.getSourceFile().fileName)) return null;
  return declaration;
}

function memberName(node: ts.Node): string | null {
  if (ts.isPropertyAccessExpression(node)) return node.name.text;
  if (ts.isElementAccessExpression(node) && ts.isStringLiteralLike(node.argumentExpression)) return node.argumentExpression.text;
  return null;
}

function hasPrototypeMutation(source: ts.SourceFile): boolean {
  function visit(node: ts.Node): boolean | undefined {
    const member = memberName(node);
    if (member === "setPrototypeOf" || member === "__proto__" || member === "hasInstance") return true;
    if (ts.isBinaryExpression(node) && node.operatorToken.kind >= ts.SyntaxKind.FirstAssignment &&
        node.operatorToken.kind <= ts.SyntaxKind.LastAssignment && memberName(node.left) === "prototype") return true;
    return ts.forEachChild(node, visit);
  }
  return visit(source) === true;
}

function nominallyInherits(
  checker: ts.TypeChecker,
  declaration: ts.ClassDeclaration,
  target: ts.Symbol,
  seen: Set<ts.Symbol>,
): boolean | null {
  if (ts.canHaveDecorators(declaration) && ts.getDecorators(declaration)?.length) return null;
  if (hasPrototypeMutation(declaration.getSourceFile()) || declaration.members.some((member) =>
    ts.isConstructorDeclaration(member) || (ts.isPropertyDeclaration(member) && member.initializer !== undefined))) return null;
  const symbol = declaration.name === undefined ? undefined : canonicalSymbol(checker, declaration.name);
  if (symbol !== undefined) {
    if (seen.has(symbol)) return null;
    seen.add(symbol);
  }
  const parents = declaration.heritageClauses?.find((clause) => clause.token === ts.SyntaxKind.ExtendsKeyword)?.types;
  if (parents === undefined) return false;
  if (parents.length !== 1) return null;
  const parentSymbol = canonicalSymbol(checker, parents[0]!.expression);
  if (parentSymbol === undefined) return null;
  if (parentSymbol === target) return true;
  const inherited = parentSymbol.declarations?.find(ts.isClassDeclaration);
  return inherited === undefined ? null : nominallyInherits(checker, inherited, target, new Set(seen));
}

function canonicalSymbol(checker: ts.TypeChecker, node: ts.Node): ts.Symbol | undefined {
  const symbol = checker.getSymbolAtLocation(node);
  return symbol === undefined ? undefined : (symbol.flags & ts.SymbolFlags.Alias) !== 0
    ? checker.getAliasedSymbol(symbol) : symbol;
}

function hasNominalRejectionGuard(
  checker: ts.TypeChecker,
  signature: ts.Signature,
  parameter: ts.Symbol,
  contract: ts.Symbol,
): boolean {
  const declaration = signature.getDeclaration();
  if (declaration === undefined || !ts.isConstructorDeclaration(declaration)) return false;
  if (ts.canHaveDecorators(declaration.parent) && ts.getDecorators(declaration.parent)?.length) return false;
  if (hasPrototypeMutation(declaration.getSourceFile())) return false;
  const first = declaration.body?.statements[0];
  if (first === undefined || !ts.isIfStatement(first) || !alwaysThrows(first.thenStatement)) return false;
  const condition = unparenthesized(first.expression);
  if (!ts.isPrefixUnaryExpression(condition) || condition.operator !== ts.SyntaxKind.ExclamationToken) return false;
  const comparison = unparenthesized(condition.operand);
  if (!ts.isBinaryExpression(comparison) || comparison.operatorToken.kind !== ts.SyntaxKind.InstanceOfKeyword) return false;
  if (canonicalSymbol(checker, comparison.left) !== parameter || canonicalSymbol(checker, comparison.right) !== contract) return false;
  const target = contract.declarations?.find(ts.isClassDeclaration);
  return target !== undefined && hasOrdinaryInstanceCheck(checker, target, new Set());
}

function unparenthesized(expression: ts.Expression): ts.Expression {
  let current = expression;
  while (ts.isParenthesizedExpression(current)) current = current.expression;
  return current;
}

function alwaysThrows(statement: ts.Statement): boolean {
  return ts.isThrowStatement(statement) ||
    (ts.isBlock(statement) && statement.statements.length === 1 && ts.isThrowStatement(statement.statements[0]!));
}

function hasOrdinaryInstanceCheck(checker: ts.TypeChecker, declaration: ts.ClassDeclaration, seen: Set<ts.ClassDeclaration>): boolean {
  if (seen.has(declaration) || ts.getDecorators(declaration)?.length || hasPrototypeMutation(declaration.getSourceFile())) return false;
  seen.add(declaration);
  if (declaration.members.some((member) => member.name !== undefined && ts.isComputedPropertyName(member.name) &&
      ts.canHaveModifiers(member) && ts.getModifiers(member)?.some((modifier) => modifier.kind === ts.SyntaxKind.StaticKeyword))) return false;
  for (const clause of declaration.heritageClauses ?? []) {
    if (clause.token !== ts.SyntaxKind.ExtendsKeyword) continue;
    for (const parent of clause.types) {
      const ancestor = canonicalSymbol(checker, parent.expression)?.declarations?.find(ts.isClassDeclaration);
      if (ancestor === undefined || !hasOrdinaryInstanceCheck(checker, ancestor, seen)) return false;
    }
  }
  return true;
}

export default createRule<Options, MessageIds>({
  name: "require-explicit-contract-implementation",
  documentation: REQUIRE_EXPLICIT_CONTRACT_IMPLEMENTATION_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: REQUIRE_EXPLICIT_CONTRACT_IMPLEMENTATION_DOCUMENTATION.summary },
    schema: [],
    messages: {
      declareActualContract: "`{{implementation}}` structurally matches `{{contract}}` but fails the rejecting instanceof guard; use nominal inheritance or make the boundary structural.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    if (!context.sourceCode.parserServices?.program || !context.sourceCode.parserServices.esTreeNodeToTSNodeMap) return {};
    const services = ESLintUtils.getParserServices(context);
    const checker = services.program.getTypeChecker();
    function inspect(node: TSESTree.NewExpression): void {
      const tsNode = services.esTreeNodeToTSNodeMap.get(node);
      if (!ts.isNewExpression(tsNode)) return;
      const consumer = canonicalSymbol(checker, tsNode.expression)?.declarations?.find(ts.isClassDeclaration);
      if (consumer === undefined) return;
      const signature = checker.getResolvedSignature(tsNode);
      if (signature === undefined || signature.getDeclaration()?.parent !== consumer) return;
      const parameters = signature.getParameters();
      for (const [index, argument] of node.arguments.entries()) {
        if (argument.type !== AST_NODE_TYPES.NewExpression) continue;
        const parameter = parameters[index];
        if (parameter === undefined) continue;
        const parameterType = checker.getTypeOfSymbolAtLocation(parameter, tsNode);
        const contractType = behavioralContract(checker, parameterType);
        if (contractType === null) continue;
        const contractSymbol = contractType.getSymbol();
        if (contractSymbol === undefined || !hasNominalRejectionGuard(checker, signature, parameter, contractSymbol)) continue;
        const tsArgument = services.esTreeNodeToTSNodeMap.get(argument);
        const actualType = checker.getTypeAtLocation(tsArgument);
        if (!checker.isTypeAssignableTo(actualType, contractType)) continue;
        const implementation = ownedClass(checker, tsArgument);
        if (implementation === null) continue;
        const relationship = nominallyInherits(checker, implementation, contractSymbol, new Set());
        if (relationship !== false) continue;
        context.report({
          node: argument,
          messageId: "declareActualContract",
          data: { implementation: implementation.name?.text ?? "class", contract: contractSymbol.getName() },
        });
      }
    }
    return {
      NewExpression: inspect,
    };
  },
});
