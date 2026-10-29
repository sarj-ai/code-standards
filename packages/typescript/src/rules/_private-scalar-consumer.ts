/** @fileoverview _private-scalar-consumer — prove private scalar consumers and their direct callers. */
import { AST_NODE_TYPES, type ParserServicesWithTypeInformation, type TSESLint, type TSESTree } from "@typescript-eslint/utils";
import ts from "typescript";

import { returnedExpression, scalarParameterReads } from "./_scalar-parameter-view.js";
import { stableValueBinding } from "./_stable-value-binding.js";
import { unwrapExpression } from "./_unwrap-expression.js";

export type ScalarConsumerNode = TSESTree.FunctionDeclaration | TSESTree.ArrowFunctionExpression;

export interface PrivateScalarConsumer {
  readonly parameter: ts.ParameterDeclaration;
  readonly reads: ReadonlySet<string>;
}

/** Erased assertions preserve direct lexical eval and its access to private bindings. */
export function directEval(node: TSESTree.CallExpression): boolean {
  let callee = unwrapExpression(node.callee);
  // An instantiated generic value also retains the direct reference after emit.
  while (callee.type === AST_NODE_TYPES.TSInstantiationExpression) callee = unwrapExpression(callee.expression);
  return callee.type === AST_NODE_TYPES.Identifier && callee.name === "eval";
}

/** Broad primitive annotations exclude domain tags, callbacks and erased values. */
export function primitiveKeyword(node: ts.TypeNode | undefined): boolean {
  return node !== undefined && (node.kind === ts.SyntaxKind.StringKeyword || node.kind === ts.SyntaxKind.NumberKeyword ||
    node.kind === ts.SyntaxKind.BooleanKeyword || node.kind === ts.SyntaxKind.BigIntKeyword);
}

export function consumerAnnotation(node: ScalarConsumerNode): TSESTree.TypeNode | undefined {
  if (node.params.length !== 1) return undefined;
  const parameter = node.params[0];
  return parameter?.type === AST_NODE_TYPES.Identifier || parameter?.type === AST_NODE_TYPES.ObjectPattern
    ? parameter.typeAnnotation?.typeAnnotation : undefined;
}

/** Module exports include type-only exports that ESLint's value references can omit. */
export function exportedSymbols(source: ts.SourceFile, checker: ts.TypeChecker): ReadonlySet<ts.Symbol> {
  const symbol = checker.getSymbolAtLocation(source);
  return new Set(symbol ? checker.getExportsOfModule(symbol).map((entry) =>
    (entry.flags & ts.SymbolFlags.Alias) !== 0 ? checker.getAliasedSymbol(entry) : entry) : []);
}

export function privateScalarConsumer(node: ScalarConsumerNode, sourceCode: TSESLint.SourceCode, services: ParserServicesWithTypeInformation, exports: ReadonlySet<ts.Symbol>, scalarCalls = false): PrivateScalarConsumer | null {
  const native = services.esTreeNodeToTSNodeMap.get(node);
  if ((!ts.isFunctionDeclaration(native) && !ts.isArrowFunction(native)) || !native.body || !independentSignature(native)) return null;
  const checker = services.program.getTypeChecker();
  if (!ts.isExternalModule(native.getSourceFile()) || !services.program.getCompilerOptions().strict) return null;
  const parameter = native.parameters[0];
  if (!parameter) return null;
  const binding = callableBinding(node, sourceCode);
  if (!binding || binding.defs.length !== 1) return null;
  const name = ts.isFunctionDeclaration(native) ? native.name : ts.isVariableDeclaration(native.parent) ? native.parent.name : undefined;
  const symbol = name && checker.getSymbolAtLocation(name);
  if (!symbol || symbol.declarations?.length !== 1 || exports.has(symbol) || !directCalls(binding)) return null;
  const signature = checker.getSignatureFromDeclaration(native);
  if (!signature || signature.typeParameters?.length || checker.getTypePredicateOfSignature(signature)) return null;
  const expression = returnedExpression(native.body);
  if (!expression || !checker.isTypeAssignableTo(checker.getTypeAtLocation(expression), checker.getReturnTypeOfSignature(signature))) return null;
  const reads = scalarParameterReads(parameter, native.body, checker, scalarCalls ? services.program : undefined);
  return reads?.size ? { parameter, reads } : null;
}

/** An annotation supplied by an overload, callback or predicate is a separate contract. */
function independentSignature(native: ts.FunctionDeclaration | ts.ArrowFunction): boolean {
  if (native.parameters.length !== 1 || native.typeParameters?.length || native.asteriskToken || native.modifiers?.length || !primitiveKeyword(native.type)) return false;
  const parameter = native.parameters[0];
  return parameter !== undefined && parameter.type !== undefined && !parameter.modifiers?.length && !parameter.questionToken && !parameter.initializer && !parameter.dotDotDotToken &&
    (!ts.isIdentifier(parameter.name) || parameter.name.text !== "this");
}

function callableBinding(node: ScalarConsumerNode, sourceCode: TSESLint.SourceCode): TSESLint.Scope.Variable | undefined {
  if (node.type === AST_NODE_TYPES.FunctionDeclaration) {
    if (node.parent.type !== AST_NODE_TYPES.Program) return undefined;
    return sourceCode.getDeclaredVariables(node).find((variable) => variable.defs.some((definition) => definition.type === "FunctionName" && definition.node === node));
  }
  const declaration = node.parent;
  if (declaration.type !== AST_NODE_TYPES.VariableDeclarator || declaration.init !== node || declaration.id.type !== AST_NODE_TYPES.Identifier || declaration.id.typeAnnotation ||
    declaration.parent.kind !== "const" || declaration.parent.parent.type !== AST_NODE_TYPES.Program) return undefined;
  return sourceCode.getDeclaredVariables(declaration).find((variable) => variable.defs.some((definition) => definition.type === "Variable" && definition.node === declaration));
}

function directCalls(binding: TSESLint.Scope.Variable): boolean {
  let calls = 0;
  const stable = stableValueBinding(binding, (reference) => {
    const identifier = reference.identifier;
    const call = identifier.parent;
    if (reference.isTypeReference || !reference.isReadOnly() || call.type !== AST_NODE_TYPES.CallExpression || call.callee !== identifier || call.optional || call.typeArguments ||
      call.arguments.length !== 1 || call.arguments[0]?.type !== AST_NODE_TYPES.Identifier) return false;
    calls += 1;
    return true;
  });
  return stable && calls > 0;
}
