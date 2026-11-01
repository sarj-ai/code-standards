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

interface ConsumerOptions {
  readonly scalarCalls?: boolean;
  readonly auxiliaryScalars?: boolean;
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

/** Admit only a direct broad primitive and null or undefined pair. */
export function nullishPrimitiveUnion(node: ts.TypeNode | undefined): boolean {
  return node !== undefined && ts.isUnionTypeNode(node) && node.types.length === 2 && node.types.some(primitiveKeyword) &&
    node.types.some((part) => part.kind === ts.SyntaxKind.UndefinedKeyword || (ts.isLiteralTypeNode(part) && part.literal.kind === ts.SyntaxKind.NullKeyword));
}

export function consumerAnnotation(node: ScalarConsumerNode, auxiliaryScalars = false): TSESTree.TypeNode | undefined {
  if (node.params.length !== 1) {
    if (!auxiliaryScalars) return undefined;
    let annotation: TSESTree.TypeNode | undefined;
    for (const parameter of node.params) {
      if (parameter.type !== AST_NODE_TYPES.Identifier && parameter.type !== AST_NODE_TYPES.ObjectPattern) continue;
      const current = parameter.typeAnnotation?.typeAnnotation;
      if (current?.type !== AST_NODE_TYPES.TSTypeLiteral) continue;
      if (annotation) return undefined;
      annotation = current;
    }
    return annotation;
  }
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

export function privateScalarConsumer(node: ScalarConsumerNode, sourceCode: TSESLint.SourceCode, services: ParserServicesWithTypeInformation, exports: ReadonlySet<ts.Symbol>, options: ConsumerOptions = {}): PrivateScalarConsumer | null {
  const native = services.esTreeNodeToTSNodeMap.get(node);
  if ((!ts.isFunctionDeclaration(native) && !ts.isArrowFunction(native)) || !native.body) return null;
  let parameter = native.parameters[0];
  if (native.parameters.length !== 1) {
    const annotation = consumerAnnotation(node, options.auxiliaryScalars);
    const selected = annotation && services.esTreeNodeToTSNodeMap.get(annotation);
    parameter = native.parameters.find((entry) => entry.type === selected);
  }
  if (!parameter || !independentSignature(native, parameter, options.auxiliaryScalars === true)) return null;
  const checker = services.program.getTypeChecker();
  if (!ts.isExternalModule(native.getSourceFile()) || !services.program.getCompilerOptions().strict) return null;
  if (!privateDirectCallable(node, native, sourceCode, checker, exports)) return null;
  const signature = checker.getSignatureFromDeclaration(native);
  if (!signature || signature.typeParameters?.length || checker.getTypePredicateOfSignature(signature)) return null;
  const expression = returnedExpression(native.body);
  if (!expression || !checker.isTypeAssignableTo(checker.getTypeAtLocation(expression), checker.getReturnTypeOfSignature(signature))) return null;
  const auxiliaries = native.parameters.length > 1 ? auxiliaryBindings(native, parameter, checker) : undefined;
  if (auxiliaries === null) return null;
  const reads = scalarParameterReads(parameter, native.body, checker, options.scalarCalls ? services.program : undefined, auxiliaries);
  return reads?.size ? { parameter, reads } : null;
}

/** Match the sole private native declaration to its lexical binding and direct callers. */
function privateDirectCallable(node: ScalarConsumerNode, native: ts.FunctionDeclaration | ts.ArrowFunction,
  sourceCode: TSESLint.SourceCode, checker: ts.TypeChecker, exports: ReadonlySet<ts.Symbol>): boolean {
  const binding = callableBinding(node, sourceCode);
  if (!binding || binding.defs.length !== 1) return false;
  const name = ts.isFunctionDeclaration(native) ? native.name : ts.isVariableDeclaration(native.parent) ? native.parent.name : undefined;
  const symbol = name && checker.getSymbolAtLocation(name);
  return symbol !== undefined && symbol.declarations?.length === 1 && !exports.has(symbol) && directCalls(binding, native.parameters.length);
}

/** An annotation supplied by an overload, callback or predicate is a separate contract. */
function independentSignature(native: ts.FunctionDeclaration | ts.ArrowFunction, selected: ts.ParameterDeclaration, auxiliaryScalars: boolean): boolean {
  if ((!auxiliaryScalars && native.parameters.length !== 1) || native.typeParameters?.length || native.asteriskToken || native.modifiers?.length || !primitiveKeyword(native.type)) return false;
  return native.parameters.every((parameter) => parameter.type !== undefined && !parameter.modifiers?.length && !parameter.questionToken && !parameter.initializer && !parameter.dotDotDotToken &&
    (!ts.isIdentifier(parameter.name) || parameter.name.text !== "this") &&
    (parameter === selected || (ts.isIdentifier(parameter.name) && primitiveKeyword(parameter.type))));
}

/** Auxiliary values have their own exact parameter bindings, never object read keys. */
function auxiliaryBindings(native: ts.FunctionDeclaration | ts.ArrowFunction, selected: ts.ParameterDeclaration, checker: ts.TypeChecker): ReadonlySet<ts.Symbol> | null {
  const bindings = new Set<ts.Symbol>();
  for (const parameter of native.parameters) {
    if (parameter === selected) continue;
    const symbol = ts.isIdentifier(parameter.name) ? checker.getSymbolAtLocation(parameter.name) : undefined;
    if (!symbol || symbol.declarations?.length !== 1 || symbol.declarations[0] !== parameter || bindings.has(symbol)) return null;
    bindings.add(symbol);
  }
  return bindings;
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

function directCalls(binding: TSESLint.Scope.Variable, arity: number): boolean {
  let calls = 0;
  const stable = stableValueBinding(binding, (reference) => {
    const identifier = reference.identifier;
    const call = identifier.parent;
    if (reference.isTypeReference || !reference.isReadOnly() || call.type !== AST_NODE_TYPES.CallExpression || call.callee !== identifier || call.optional || call.typeArguments ||
      call.arguments.length !== arity || !call.arguments.every((argument) => argument.type === AST_NODE_TYPES.Identifier)) return false;
    calls += 1;
    return true;
  });
  return stable && calls > 0;
}
