/**
 * @fileoverview require-explicit-contract-implementation — Require owned substitutes to name their injected contract.
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
  summary: "Require owned classes supplied as typed collaborators to explicitly implement their contract.",
  rationale: "Structural assignment checks a fake only at the use site; an implements clause keeps its obligations visible at the class declaration.",
  remediation: "Add an implements clause for the actual injected interface, or inherit an abstract class that declares it.",
  category: "architecture",
  autofix: "none",
  limitations: [
    "Only class instances whose concrete class and selected constructor parameter resolve through the TypeScript checker are checked.",
    "Object literals, casts, any, callback-valued data properties, unresolved heritage, dynamic factories, and third-party classes are excluded.",
  ],
  examples: [
    {
      id: "structural-fake-at-injection",
      title: "A fake reaches a typed collaborator without implementing its interface",
      outcome: "match",
      files: [{ path: "src/service.ts", source: "interface Publisher { publish(): void } class Consumer { constructor(readonly publisher: Publisher) {} } class FakePublisher { publish() {} } new Consumer(new FakePublisher());" }],
      focusPath: "src/service.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "explicit-fake-at-injection",
      title: "The fake names its actual interface",
      outcome: "no-match",
      files: [{ path: "src/service.ts", source: "interface Publisher { publish(): void } class Consumer { constructor(readonly publisher: Publisher) {} } class FakePublisher implements Publisher { publish() {} } new Consumer(new FakePublisher());" }],
      focusPath: "src/service.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "inherited-implementation",
      title: "The fake inherits an implementation of the port",
      outcome: "no-match",
      files: [{ path: "src/service.ts", source: "interface Publisher { publish(): void } class Consumer { constructor(readonly publisher: Publisher) {} } class BasePublisher implements Publisher { publish() {} } class FakePublisher extends BasePublisher {} new Consumer(new FakePublisher());" }],
      focusPath: "src/service.ts",
      expectedCount: 0,
      public: false,
    },
    {
      id: "non-contract-data-argument",
      title: "A data object is not a service port",
      outcome: "no-match",
      files: [{ path: "src/service.ts", source: "interface Options { name: string } class Consumer { constructor(readonly options: Options) {} } class FakeOptions { name = 'test' } new Consumer(new FakeOptions());" }],
      focusPath: "src/service.ts",
      expectedCount: 0,
      public: false,
    },
    {
      id: "explicit-cast-origin-unknown",
      title: "A cast hides the concrete source",
      outcome: "no-match",
      files: [{ path: "src/service.ts", source: "interface Publisher { publish(): void } class Consumer { constructor(readonly publisher: Publisher) {} } class FakePublisher { publish() {} } new Consumer(new FakePublisher() as Publisher);" }],
      focusPath: "src/service.ts",
      expectedCount: 0,
      public: false,
    },
    {
      id: "unrelated-interface",
      title: "Implementing another interface does not declare the supplied port",
      outcome: "match",
      files: [{ path: "src/service.ts", source: "interface Publisher { publish(): void } interface Other { publish(): void } class Consumer { constructor(readonly publisher: Publisher) {} } class FakePublisher implements Other { publish() {} } new Consumer(new FakePublisher());" }],
      focusPath: "src/service.ts",
      expectedCount: 1,
      public: false,
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
    ts.isInterfaceDeclaration(item) || ts.isTypeAliasDeclaration(item) ||
    (ts.isClassDeclaration(item) && item.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.AbstractKeyword)));
  if (declaration === undefined) return null;
  return checker.getPropertiesOfType(type).some((property) => {
    if (!property.declarations?.some((member) => ts.isMethodSignature(member) || ts.isMethodDeclaration(member))) return false;
    const propertyType = checker.getTypeOfSymbolAtLocation(property, declaration);
    return propertyType.getCallSignatures().length > 0;
  }) ? type : null;
}

function ownedClass(type: ts.Type): ts.ClassDeclaration | null {
  if ((type.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown)) !== 0) return null;
  const declaration = type.getSymbol()?.declarations?.find(ts.isClassDeclaration);
  if (declaration === undefined || declaration.getSourceFile().isDeclarationFile ||
      /(?:^|[/\\])(?:node_modules|vendor|generated)(?:[/\\])/u.test(declaration.getSourceFile().fileName)) return null;
  return declaration;
}

function explicitlyImplements(
  checker: ts.TypeChecker,
  declaration: ts.ClassDeclaration | ts.InterfaceDeclaration,
  target: ts.Symbol,
  seen: Set<ts.Symbol>,
): boolean | null {
  const symbol = declaration.name === undefined ? undefined : canonicalSymbol(checker, declaration.name);
  if (symbol !== undefined) {
    if (seen.has(symbol)) return null;
    seen.add(symbol);
  }
  let unknown = false;
  for (const clause of declaration.heritageClauses ?? []) {
    for (const parent of clause.types) {
      const parentSymbol = canonicalSymbol(checker, parent.expression);
      if (parentSymbol === undefined) {
        unknown = true;
        continue;
      }
      if (parentSymbol === target) return true;
      const inherited = parentSymbol.declarations?.find((item): item is ts.ClassDeclaration | ts.InterfaceDeclaration =>
        ts.isClassDeclaration(item) || ts.isInterfaceDeclaration(item));
      if (inherited === undefined) {
        unknown = true;
        continue;
      }
      const relationship = explicitlyImplements(checker, inherited, target, new Set(seen));
      if (relationship === true) return true;
      unknown ||= relationship === null;
    }
  }
  return unknown ? null : false;
}

function canonicalSymbol(checker: ts.TypeChecker, node: ts.Node): ts.Symbol | undefined {
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
      declareActualContract: "`{{implementation}}` is supplied as `{{contract}}` without explicitly implementing that contract.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    if (!context.sourceCode.parserServices?.program || !context.sourceCode.parserServices.esTreeNodeToTSNodeMap) return {};
    const services = ESLintUtils.getParserServices(context);
    const checker = services.program.getTypeChecker();
    function inspect(node: TSESTree.CallExpression | TSESTree.NewExpression): void {
      const tsNode = services.esTreeNodeToTSNodeMap.get(node);
      if (!ts.isCallExpression(tsNode) && !ts.isNewExpression(tsNode)) return;
      const signature = checker.getResolvedSignature(tsNode);
      if (signature === undefined) return;
      const parameters = signature.getParameters();
      for (const [index, argument] of node.arguments.entries()) {
        if (argument.type === AST_NODE_TYPES.SpreadElement || argument.type === AST_NODE_TYPES.TSAsExpression ||
            argument.type === AST_NODE_TYPES.TSTypeAssertion || argument.type === AST_NODE_TYPES.TSSatisfiesExpression) continue;
        const parameter = parameters[index];
        if (parameter === undefined) continue;
        const parameterType = checker.getTypeOfSymbolAtLocation(parameter, tsNode);
        const contractType = behavioralContract(checker, parameterType);
        if (contractType === null) continue;
        const contractSymbol = contractType.getSymbol();
        if (contractSymbol === undefined) continue;
        const tsArgument = services.esTreeNodeToTSNodeMap.get(argument);
        const actualType = checker.getTypeAtLocation(tsArgument);
        if (!checker.isTypeAssignableTo(actualType, contractType)) continue;
        const implementation = ownedClass(actualType);
        if (implementation === null) continue;
        const relationship = explicitlyImplements(checker, implementation, contractSymbol, new Set());
        if (relationship !== false) continue;
        context.report({
          node: argument,
          messageId: "declareActualContract",
          data: { implementation: implementation.name?.text ?? "class", contract: contractSymbol.getName() },
        });
      }
    }
    return {
      CallExpression: inspect,
      NewExpression: inspect,
    };
  },
});
