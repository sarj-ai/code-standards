/**
 * @fileoverview private-scalar-consumer — prove private scalar consumers and their direct callers, over tsrs nodes and its checker.
 *
 * Symbols are compared by tsrs id; the original compares `ts.Symbol` identity.
 */

import type { ArrowFunction, FunctionDeclaration, Node as TsAstNode, ParameterDeclaration, SourceFile } from "tsrs/ast";

import type { ESTree, Node, SourceCode, TsVariable } from "../types.js";
import { parentOf, unwrapExpression } from "./ast.js";
import type { NativeAst, NativeTypes } from "./checked-native-source.js";
import { returnedExpression, scalarParameterReads } from "./scalar-parameter-view.js";
import { stableValueBinding } from "./stable-value-binding.js";

export type ScalarConsumerNode = ESTree.Function | ESTree.ArrowFunctionExpression;

export interface PrivateScalarConsumer {
  readonly parameter: ParameterDeclaration;
  readonly reads: ReadonlySet<string>;
}

interface ConsumerOptions {
  readonly scalarCalls?: boolean;
  readonly auxiliaryScalars?: boolean;
}

/** Erased assertions preserve direct lexical eval and its access to private bindings. */
export function directEval(node: ESTree.CallExpression): boolean {
  let callee = unwrapExpression(node.callee);
  // An instantiated generic value also retains the direct reference after emit.
  while (callee.type === "TSInstantiationExpression") callee = unwrapExpression(callee.expression);
  return callee.type === "Identifier" && callee.name === "eval";
}

/** Broad primitive annotations exclude domain tags, callbacks and erased values. */
export function primitiveKeyword(ast: NativeAst, node: TsAstNode | undefined): boolean {
  const k = ast.SyntaxKind;
  return node !== undefined && (node.kind === k.StringKeyword || node.kind === k.NumberKeyword ||
    node.kind === k.BooleanKeyword || node.kind === k.BigIntKeyword);
}

/** Admit only a direct broad primitive and null or undefined pair. */
export function nullishPrimitiveUnion(ast: NativeAst, node: TsAstNode | undefined): boolean {
  return node !== undefined && ast.isUnionTypeNode(node) && node.types.length === 2 && node.types.some((part) => primitiveKeyword(ast, part)) &&
    node.types.some((part) => part.kind === ast.SyntaxKind.UndefinedKeyword ||
      (ast.isLiteralTypeNode(part) && part.literal.kind === ast.SyntaxKind.NullKeyword));
}

/** TypeScript 7 keeps a member's `?` (or `!`) in `postfixToken`; TypeScript 6 has `questionToken`. */
export function optionalMember(ast: NativeAst, member: TsAstNode): boolean {
  return (member as { readonly postfixToken?: TsAstNode }).postfixToken?.kind === ast.SyntaxKind.QuestionToken;
}

export function consumerAnnotation(node: ScalarConsumerNode, auxiliaryScalars = false): Node | undefined {
  if (node.params.length !== 1) {
    if (!auxiliaryScalars) return undefined;
    let annotation: Node | undefined;
    for (const parameter of node.params) {
      if (parameter.type !== "Identifier" && parameter.type !== "ObjectPattern") continue;
      const current = annotationOf(parameter);
      if (current?.type !== "TSTypeLiteral") continue;
      if (annotation) return undefined;
      annotation = current;
    }
    return annotation;
  }
  const parameter = node.params[0];
  return parameter?.type === "Identifier" || parameter?.type === "ObjectPattern" ? annotationOf(parameter) : undefined;
}

function annotationOf(parameter: Node): Node | undefined {
  // Oxlint gives an absent annotation as null where TS-ESTree has undefined.
  return (parameter as { typeAnnotation?: { typeAnnotation: Node } | null }).typeAnnotation?.typeAnnotation ?? undefined;
}

/** Module exports (by tsrs symbol id) include type-only exports that ESLint's value references can omit. */
export function exportedSymbols(native: NativeTypes, source: SourceFile): ReadonlySet<number> {
  const { checker, sync } = native;
  const symbol = checker.getSymbolAtLocation(source);
  return new Set(symbol ? checker.getExportsOfModule(symbol).map((entry) =>
    ((entry.flags & sync.SymbolFlags.Alias) !== 0 ? checker.getAliasedSymbol(entry) : entry).id) : []);
}

type NativeFunction = FunctionDeclaration | ArrowFunction;

export function privateScalarConsumer(native: NativeTypes, node: ScalarConsumerNode, sourceCode: SourceCode, exports: ReadonlySet<number>,
  options: ConsumerOptions = {}): PrivateScalarConsumer | null {
  const { ast, checker, program } = native;
  const declaration = native.node(node);
  if (!declaration || (!ast.isFunctionDeclaration(declaration) && !ast.isArrowFunction(declaration)) || !declaration.body) return null;
  let parameter: ParameterDeclaration | undefined = declaration.parameters[0];
  if (declaration.parameters.length !== 1) {
    const annotation = consumerAnnotation(node, options.auxiliaryScalars);
    const selected = annotation && native.node(annotation);
    parameter = declaration.parameters.find((entry) => entry.type !== undefined && entry.type === selected);
  }
  if (!parameter || !independentSignature(ast, declaration, parameter, options.auxiliaryScalars === true)) return null;
  if (!ast.isExternalModule(declaration.getSourceFile()) || !program.getCompilerOptions().strict) return null;
  if (!privateDirectCallable(native, node, declaration, sourceCode, exports)) return null;
  const signature = checker.getSignatureFromDeclaration(declaration);
  if (!signature || signature.typeParameters?.length || checker.getTypePredicateOfSignature(signature)) return null;
  const expression = returnedExpression(ast, declaration.body);
  if (!expression || !checker.isTypeAssignableTo(checker.getTypeAtLocation(expression), checker.getReturnTypeOfSignature(signature))) return null;
  const auxiliaries = declaration.parameters.length > 1 ? auxiliaryBindings(native, declaration, parameter) : undefined;
  if (auxiliaries === null) return null;
  const reads = scalarParameterReads(native, parameter, declaration.body, options.scalarCalls === true, auxiliaries);
  return reads?.size ? { parameter, reads } : null;
}

/** Match the sole private native declaration to its lexical binding and direct callers. */
function privateDirectCallable(native: NativeTypes, node: ScalarConsumerNode, declaration: NativeFunction, sourceCode: SourceCode,
  exports: ReadonlySet<number>): boolean {
  const { ast, checker } = native;
  const binding = callableBinding(node, sourceCode);
  if (!binding || binding.defs.length !== 1) return false;
  const name = ast.isFunctionDeclaration(declaration) ? declaration.name
    : ast.isVariableDeclaration(declaration.parent) ? declaration.parent.name : undefined;
  const symbol = name && checker.getSymbolAtLocation(name);
  return symbol !== undefined && symbol.declarations.length === 1 && !exports.has(symbol.id) && directCalls(binding, declaration.parameters.length);
}

/** An annotation supplied by an overload, callback or predicate is a separate contract. */
function independentSignature(ast: NativeAst, declaration: NativeFunction, selected: ParameterDeclaration, auxiliaryScalars: boolean): boolean {
  if ((!auxiliaryScalars && declaration.parameters.length !== 1) || declaration.typeParameters?.length || declaration.asteriskToken ||
    declaration.modifiers?.length || !primitiveKeyword(ast, declaration.type)) return false;
  return declaration.parameters.every((parameter) => parameter.type !== undefined && !parameter.modifiers?.length && !parameter.questionToken &&
    !parameter.initializer && !parameter.dotDotDotToken &&
    (!ast.isIdentifier(parameter.name) || parameter.name.text !== "this") &&
    (parameter === selected || (ast.isIdentifier(parameter.name) && primitiveKeyword(ast, parameter.type))));
}

/** Auxiliary values have their own exact parameter bindings (tsrs symbol ids), never object read keys. */
function auxiliaryBindings(native: NativeTypes, declaration: NativeFunction, selected: ParameterDeclaration): ReadonlySet<number> | null {
  const { ast, checker } = native;
  const bindings = new Set<number>();
  for (const parameter of declaration.parameters) {
    if (parameter === selected) continue;
    const symbol = ast.isIdentifier(parameter.name) ? checker.getSymbolAtLocation(parameter.name) : undefined;
    const only = symbol?.declarations.length === 1 ? symbol.declarations[0] : undefined;
    if (!symbol || !only || only.resolve(native.program.getProject()) !== parameter || bindings.has(symbol.id)) return null;
    bindings.add(symbol.id);
  }
  return bindings;
}

function callableBinding(node: ScalarConsumerNode, sourceCode: SourceCode): TsVariable | undefined {
  const parent = parentOf(node);
  if (node.type === "FunctionDeclaration") {
    if (parent?.type !== "Program") return undefined;
    return sourceCode.getDeclaredVariables(node).find((variable) =>
      variable.defs.some((definition) => definition.type === "FunctionName" && definition.node === node)) as TsVariable | undefined;
  }
  const declaration = parent;
  if (declaration?.type !== "VariableDeclarator" || declaration.init !== node || declaration.id.type !== "Identifier" || declaration.id.typeAnnotation) return undefined;
  const list = parentOf(declaration);
  if (list?.type !== "VariableDeclaration" || list.kind !== "const" || parentOf(list)?.type !== "Program") return undefined;
  return sourceCode.getDeclaredVariables(declaration).find((variable) =>
    variable.defs.some((definition) => definition.type === "Variable" && definition.node === declaration)) as TsVariable | undefined;
}

function directCalls(binding: TsVariable, arity: number): boolean {
  let calls = 0;
  const stable = stableValueBinding(binding, (reference) => {
    const identifier = reference.identifier;
    const call = parentOf(identifier);
    if (reference.isTypeReference || !reference.isReadOnly() || call?.type !== "CallExpression" || call.callee !== identifier || call.optional ||
      call.typeArguments || call.arguments.length !== arity || !call.arguments.every((argument) => argument.type === "Identifier")) return false;
    calls += 1;
    return true;
  });
  return stable && calls > 0;
}
