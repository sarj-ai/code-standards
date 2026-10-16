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
const ESCAPED_CLASSES = new WeakMap<ts.Program, ReadonlySet<ts.Symbol>>();

export const REQUIRE_EXPLICIT_CONTRACT_IMPLEMENTATION_DOCUMENTATION = {
  defaultLevel: "error",
  summary: "Require nominal inheritance when an injected abstract class is rejected by an instanceof guard.",
  rationale: "A structurally assignable fake can still fail a constructor's nominal runtime guard. Pure structural interfaces do not require an implements clause.",
  remediation: "Use an implementation inheriting the existing abstract class, or remove the nominal guard if the boundary is intentionally structural.",
  category: "architecture",
  autofix: "none",
  limitations: [
    "Requires direct construction of both owned consumer and collaborator classes, with a first-statement consumer constructor guard rejecting the exact parameter with if (!(parameter instanceof Contract)) throw. Parentheses preserve exact constructor and guard symbol identity; casts remain excluded.",
    "The contract must resolve to an abstract class without decorators, static blocks, unresolved ancestors, or custom computed static members in its resolved hierarchy. Escaped class constructors are checked across every owned module in the typed program.",
    "Structural interfaces, non-rejecting branches, reassignment before the guard, casts, unresolved heritage, dynamic factories, implementation static blocks, explicit implementation constructors or initializers, involved modules referencing prototype-mutator members or assigning prototypes, escaped class constructors, and third-party classes are excluded.",
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

function memberName(node: ts.Node): string | null {
  if (ts.isPropertyAccessExpression(node)) return node.name.text;
  if (ts.isElementAccessExpression(node) && ts.isStringLiteralLike(node.argumentExpression)) return node.argumentExpression.text;
  return null;
}

function ownedSource(source: ts.SourceFile): boolean {
  return !source.isDeclarationFile && !/(?:^|[/\\])(?:node_modules|vendor|vendored|generated|dist)(?:[/\\])/u.test(source.fileName) &&
    !isGeneratedFile(source.fileName, source.text);
}

function escapedClasses(program: ts.Program, checker: ts.TypeChecker): ReadonlySet<ts.Symbol> {
  const cached = ESCAPED_CLASSES.get(program);
  if (cached !== undefined) return cached;
  const escaped = new Set<ts.Symbol>();
  const namespaceValues = new Map<ts.Symbol, ReadonlySet<ts.Symbol>>();
  function visit(node: ts.Node): void {
    if (ts.isTypeNode(node) || ts.isImportDeclaration(node)) return;
    if (ts.isIdentifier(node) || ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) {
      recordEscapedReference(checker, node, escaped, namespaceValues);
    }
    ts.forEachChild(node, visit);
  }
  for (const source of program.getSourceFiles()) if (ownedSource(source)) visit(source);
  ESCAPED_CLASSES.set(program, escaped);
  return escaped;
}

function recordEscapedReference(
  checker: ts.TypeChecker,
  node: ts.Identifier | ts.PropertyAccessExpression | ts.ElementAccessExpression,
  escaped: Set<ts.Symbol>,
  namespaceValues: Map<ts.Symbol, ReadonlySet<ts.Symbol>>,
): void {
  const symbol = canonicalSymbol(checker, node);
  if (symbol !== undefined) {
    let values = namespaceValues.get(symbol);
    if (values === undefined) {
      values = ownedClassValues(checker, symbol);
      namespaceValues.set(symbol, values);
    }
    if (!namespacePrefix(symbol, node) && !safeClassReference(node)) for (const value of values) escaped.add(value);
  }
  if (ts.isElementAccessExpression(node) && !safeClassReference(node)) {
    const receiver = canonicalSymbol(checker, node.expression) ?? checker.getTypeAtLocation(node.expression).getSymbol();
    if (receiver !== undefined) for (const value of ownedClassValues(checker, receiver)) escaped.add(value);
  }
}

function ownedClassValues(checker: ts.TypeChecker, original: ts.Symbol, seen = new Set<ts.Symbol>()): ReadonlySet<ts.Symbol> {
  const symbol = original.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(original) : original;
  const values = new Set<ts.Symbol>();
  if (seen.has(symbol)) return values;
  seen.add(symbol);
  if (symbol.declarations?.some((declaration) => ts.isClassDeclaration(declaration) && ownedSource(declaration.getSourceFile()))) values.add(symbol);
  if (symbol.declarations?.some((declaration) =>
    (ts.isSourceFile(declaration) || ts.isModuleDeclaration(declaration)) && ownedSource(declaration.getSourceFile()))) {
    for (const exported of checker.getExportsOfModule(symbol)) {
      for (const value of ownedClassValues(checker, exported, seen)) values.add(value);
    }
  }
  return values;
}

function safeClassReference(node: ts.Identifier | ts.PropertyAccessExpression | ts.ElementAccessExpression): boolean {
  let reference: ts.Node = ts.isPropertyAccessExpression(node.parent) && node.parent.name === node ? node.parent : node;
  while (ts.isParenthesizedExpression(reference.parent)) reference = reference.parent;
  const parent = reference.parent;
  return (ts.isClassDeclaration(parent) && parent.name === reference) ||
    (ts.isNewExpression(parent) && parent.expression === reference) ||
    (ts.isExpressionWithTypeArguments(parent) && parent.expression === reference) ||
    (ts.isBinaryExpression(parent) && parent.operatorToken.kind === ts.SyntaxKind.InstanceOfKeyword && parent.right === reference);
}

function namespacePrefix(symbol: ts.Symbol, node: ts.Node): boolean {
  const parent = node.parent;
  const memberCall = (ts.isPropertyAccessExpression(parent) || ts.isElementAccessExpression(parent)) &&
    ts.isCallExpression(parent.parent) && parent.parent.expression === parent;
  return !symbol.declarations?.some(ts.isClassDeclaration) &&
    (ts.isPropertyAccessExpression(parent) || ts.isElementAccessExpression(parent)) && parent.expression === node && !memberCall;
}

interface MissingImplementation {
  readonly implementation: ts.ClassDeclaration;
  readonly contractSymbol: ts.Symbol;
}

function closedNominalBoundary(
  program: ts.Program,
  checker: ts.TypeChecker,
  call: ts.NewExpression,
  consumer: ts.ClassDeclaration,
  missing: MissingImplementation,
): boolean {
  const { implementation, contractSymbol } = missing;
  const implementationSymbol = implementation.name === undefined ? undefined : canonicalSymbol(checker, implementation.name);
  const consumerSymbol = consumer.name === undefined ? undefined : canonicalSymbol(checker, consumer.name);
  if (implementationSymbol === undefined || consumerSymbol === undefined) return false;
  const contract = contractSymbol.declarations?.find(ts.isClassDeclaration);
  if (contract === undefined) return false;
  const targets = new Set([consumerSymbol, ...classHierarchySymbols(checker, contract), ...classHierarchySymbols(checker, implementation)]);
  const sources = new Set([call.getSourceFile(), consumer.getSourceFile(), implementation.getSourceFile(), ...contractSymbol.declarations?.map((item) => item.getSourceFile()) ?? []]);
  return ![...sources].some(hasPrototypeMutation) && ![...targets].some((target) => escapedClasses(program, checker).has(target));
}

function classHierarchySymbols(checker: ts.TypeChecker, declaration: ts.ClassDeclaration, seen = new Set<ts.Symbol>()): Set<ts.Symbol> {
  const symbol = declaration.name === undefined ? undefined : canonicalSymbol(checker, declaration.name);
  if (symbol === undefined || seen.has(symbol)) return seen;
  seen.add(symbol);
  for (const clause of declaration.heritageClauses ?? []) {
    if (clause.token !== ts.SyntaxKind.ExtendsKeyword) continue;
    for (const parent of clause.types) {
      const ancestor = canonicalSymbol(checker, parent.expression)?.declarations?.find(ts.isClassDeclaration);
      if (ancestor !== undefined) classHierarchySymbols(checker, ancestor, seen);
    }
  }
  return seen;
}

function missingImplementation(
  checker: ts.TypeChecker,
  signature: ts.Signature,
  parameter: ts.Symbol,
  call: ts.NewExpression,
  argument: ts.Node,
): MissingImplementation | null {
  const parameterType = checker.getTypeOfSymbolAtLocation(parameter, call);
  const contractType = behavioralContract(checker, parameterType);
  if (contractType === null) return null;
  const contractSymbol = contractType.getSymbol();
  if (contractSymbol === undefined || !hasNominalRejectionGuard(checker, signature, parameter, contractSymbol)) return null;
  const actualType = checker.getTypeAtLocation(argument);
  if (!checker.isTypeAssignableTo(actualType, contractType)) return null;
  const implementation = ownedClass(checker, argument);
  if (implementation === null) return null;
  if (nominallyInherits(checker, implementation, contractSymbol, new Set()) !== false) return null;
  return { implementation, contractSymbol };
}

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

function nominallyInherits(
  checker: ts.TypeChecker,
  declaration: ts.ClassDeclaration,
  target: ts.Symbol,
  seen: Set<ts.Symbol>,
): boolean | null {
  if (ts.canHaveDecorators(declaration) && ts.getDecorators(declaration)?.length) return null;
  if (hasPrototypeMutation(declaration.getSourceFile()) || declaration.members.some((member) =>
    ts.isConstructorDeclaration(member) || ts.isClassStaticBlockDeclaration(member) ||
    (ts.isPropertyDeclaration(member) && member.initializer !== undefined))) return null;
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
  if (seen.has(declaration) || ts.getDecorators(declaration)?.length || hasPrototypeMutation(declaration.getSourceFile()) ||
    declaration.members.some(ts.isClassStaticBlockDeclaration)) return false;
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

function canonicalSymbol(checker: ts.TypeChecker, node: ts.Node): ts.Symbol | undefined {
  if (ts.isParenthesizedExpression(node)) node = unparenthesized(node);
  const symbol = checker.getSymbolAtLocation(node);
  return symbol === undefined ? undefined : (symbol.flags & ts.SymbolFlags.Alias) !== 0
    ? checker.getAliasedSymbol(symbol) : symbol;
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
        const tsArgument = services.esTreeNodeToTSNodeMap.get(argument);
        const missing = missingImplementation(checker, signature, parameter, tsNode, tsArgument);
        if (missing === null || !closedNominalBoundary(services.program, checker, tsNode, consumer, missing)) continue;
        context.report({
          node: argument,
          messageId: "declareActualContract",
          data: { implementation: missing.implementation.name?.text ?? "class", contract: missing.contractSymbol.getName() },
        });
      }
    }
    return {
      NewExpression: inspect,
    };
  },
});
