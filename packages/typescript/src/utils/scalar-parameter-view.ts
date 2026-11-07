/**
 * @fileoverview scalar-parameter-view — trace scalar parameter reads in a pure returned view, over tsrs nodes and its checker.
 *
 * Symbols are compared by tsrs id; the original compares `ts.Symbol` identity.
 */

import type { Node, ParameterDeclaration } from "tsrs/ast";
import type { Symbol as TsSymbol, Type } from "tsrs/sync";

import { checkedNativeSource, declarationNode, type NativeAst, type NativeTypes } from "./checked-native-source.js";
import { constInitializer } from "./native-const-value.js";

interface Kinds {
  readonly scalarOperators: ReadonlySet<number>;
  readonly scalarPrefixes: ReadonlySet<number>;
  readonly returnedOperands: ReadonlySet<number>;
}

let kinds: Kinds | undefined;
function operatorKinds(ast: NativeAst): Kinds {
  if (kinds !== undefined) return kinds;
  const k = ast.SyntaxKind;
  kinds = {
    scalarOperators: new Set([
      k.PlusToken, k.MinusToken, k.AsteriskToken, k.SlashToken, k.PercentToken, k.AsteriskAsteriskToken,
      k.LessThanToken, k.LessThanEqualsToken, k.GreaterThanToken, k.GreaterThanEqualsToken,
      k.EqualsEqualsEqualsToken, k.ExclamationEqualsEqualsToken, k.EqualsEqualsToken, k.ExclamationEqualsToken,
      k.AmpersandAmpersandToken, k.BarBarToken, k.QuestionQuestionToken,
    ]),
    scalarPrefixes: new Set([k.PlusToken, k.MinusToken, k.ExclamationToken, k.TildeToken]),
    returnedOperands: new Set([k.AmpersandAmpersandToken, k.BarBarToken, k.QuestionQuestionToken]),
  };
  return kinds;
}

/** `&&`, `||` and `??`: operands that may return React children. */
export function returnedOperands(ast: NativeAst): ReadonlySet<number> {
  return operatorKinds(ast).returnedOperands;
}

interface ParameterView {
  readonly native: NativeTypes;
  /** Set when scalar consumers may call local helpers. */
  readonly calls: boolean;
  readonly props: Type;
  readonly root: TsSymbol | undefined;
  readonly aliases: ReadonlyMap<number, string>;
  readonly reads: Set<string>;
  readonly auxiliaries: ReadonlySet<number> | undefined;
}

/** Accept one pure returned view, retaining every bound or inspected root field. */
export function scalarParameterView(native: NativeTypes, parameter: ParameterDeclaration, body: Node): ReadonlySet<string> | null {
  return parameterReads(native, parameter, body, true);
}

/** Scalar consumers do not inherit the JSX runtime proof used by component views. */
export function scalarParameterReads(native: NativeTypes, parameter: ParameterDeclaration, body: Node, calls = false,
  auxiliaries?: ReadonlySet<number>): ReadonlySet<string> | null {
  return parameterReads(native, parameter, body, false, calls, auxiliaries);
}

function parameterReads(native: NativeTypes, parameter: ParameterDeclaration, body: Node, jsx: boolean, calls = false,
  auxiliaries?: ReadonlySet<number>): ReadonlySet<string> | null {
  const { ast, checker } = native;
  if (parameter.dotDotDotToken || parameter.initializer || ast.isArrayBindingPattern(parameter.name)) return null;
  const root = ast.isIdentifier(parameter.name) ? checker.getSymbolAtLocation(parameter.name) : undefined;
  if (ast.isIdentifier(parameter.name) && !root) return null;
  const reads = new Set<string>();
  const aliases = parameterAliases(native, parameter.name, reads);
  if (!aliases) return null;
  const expression = returnedExpression(ast, body);
  const view: ParameterView = { native, props: checker.getTypeAtLocation(parameter), root, aliases, reads, calls, auxiliaries };
  return expression && scalarView(expression, view, jsx) ? reads : null;
}

export function scalarType(native: NativeTypes, type: Type, allowUndefined = true): boolean {
  if (type.isUnionType()) return type.getTypes().every((part) => scalarType(native, part, allowUndefined));
  const f = native.sync.TypeFlags;
  const flags = f.StringLike | f.NumberLike | f.BooleanLike | f.BigIntLike | f.Null;
  return (type.flags & (allowUndefined ? flags | f.Undefined : flags)) !== 0;
}

function parameterAliases(native: NativeTypes, name: Node, reads: Set<string>): ReadonlyMap<number, string> | null {
  const { ast, checker } = native;
  const aliases = new Map<number, string>();
  if (ast.isIdentifier(name)) return aliases;
  if (!ast.isObjectBindingPattern(name)) return null;
  for (const element of name.elements) {
    const key = element.propertyName ?? element.name;
    if (element.dotDotDotToken || element.initializer || !element.name || !ast.isIdentifier(element.name) || !key ||
      (!ast.isIdentifier(key) && !ast.isStringLiteralLikeNode(key) && !ast.isNumericLiteral(key))) return null;
    const binding = checker.getSymbolAtLocation(element.name);
    if (!binding) return null;
    reads.add(key.text);
    aliases.set(binding.id, key.text);
  }
  return aliases;
}

export function returnedExpression(ast: NativeAst, body: Node): Node | undefined {
  if (!ast.isBlock(body)) return body;
  const statement = body.statements.length === 1 ? body.statements[0] : undefined;
  return statement && ast.isReturnStatement(statement) ? statement.expression : undefined;
}

function scalarView(node: Node, view: ParameterView, jsx = false): boolean {
  const { ast, checker } = view.native;
  if (scalarLiteral(ast, node)) return true;
  if (ast.isCallExpression(node)) return !jsx && scalarCall(node, view);
  if (ast.isJsxExpression(node)) return !node.dotDotDotToken && (!node.expression || scalarView(node.expression, view, jsx));
  if (ast.isIdentifier(node)) {
    const binding = checker.getSymbolAtLocation(node);
    if (binding && view.auxiliaries?.has(binding.id)) return scalarType(view.native, checker.getTypeAtLocation(node));
    const key = binding && view.aliases.get(binding.id);
    return key !== undefined && readField(node, key, view);
  }
  if (ast.isPropertyAccessExpression(node) || ast.isElementAccessExpression(node)) return memberRead(node, view);
  return scalarOperation(node, view, jsx);
}

/** Compose scalar reads without changing which operands may return JSX. */
function scalarOperation(node: Node, view: ParameterView, jsx: boolean): boolean {
  const { ast } = view.native;
  if (ast.isParenthesizedExpression(node) || ast.isNonNullExpression(node)) return scalarView(node.expression, view, jsx);
  if (ast.isTypeOfExpression(node)) return scalarView(node.expression, view);
  if (ast.isConditionalExpression(node)) {
    return scalarView(node.condition, view) && scalarView(node.whenTrue, view, jsx) && scalarView(node.whenFalse, view, jsx);
  }
  if (ast.isBinaryExpression(node)) return binaryView(node, view, jsx);
  if (ast.isPrefixUnaryExpression(node)) return operatorKinds(ast).scalarPrefixes.has(node.operator) && scalarView(node.operand, view);
  if (ast.isTemplateExpression(node)) return node.templateSpans.every((span) => scalarView(span.expression, view));
  return jsx && jsxView(node, view);
}

/** Only primitive values cross a local helper call; the parameter object never does. */
function scalarCall(node: Node & { readonly kind: number }, view: ParameterView): boolean {
  const { ast, checker } = view.native;
  if (!ast.isCallExpression(node)) return false;
  if (!view.calls || node.questionDotToken || node.typeArguments?.length || !ast.isIdentifier(node.expression) ||
    !node.arguments.length || node.arguments.some((argument) => ast.isSpreadElement(argument))) return false;
  const declarations = checker.getSymbolAtLocation(node.expression)?.declarations;
  const handle = declarations?.length === 1 ? declarations[0] : undefined;
  // A declaration in another file fails the same-file check below; never fetch that file.
  const declaration = handle && handle.path === node.getSourceFile().path ? declarationNode(view.native, handle) : undefined;
  const helper = declaration && localHelper(ast, declaration);
  if (!helper || helper.getSourceFile() !== node.getSourceFile() || helper.typeParameters?.length || !helper.type ||
    !node.arguments.every((argument) => scalarView(argument, view))) return false;
  if (!checkedNativeSource(view.native, node.getSourceFile())) return false;
  const signature = checker.getResolvedSignature(node);
  const resolved = signature.declaration === undefined ? undefined : declarationNode(view.native, signature.declaration);
  return resolved === helper && !checker.getTypePredicateOfSignature(signature) && scalarType(view.native, checker.getTypeAtLocation(node));
}

/** Imported, ambient, overloaded, contextual and aliased callees remain unsupported. */
function localHelper(ast: NativeAst, node: Node) {
  if (ast.isFunctionDeclaration(node)) return node.body && ast.isSourceFile(node.parent) ? node : undefined;
  if (!ast.isVariableDeclaration(node) || node.type || !node.initializer || constInitializer(ast, node) !== node.initializer ||
    !ast.isArrowFunction(node.initializer) || !ast.isVariableStatement(node.parent.parent) ||
    !ast.isSourceFile(node.parent.parent.parent)) return undefined;
  return node.initializer;
}

/** Logical operands may return React children; scalar operators require scalar operands. */
function binaryView(node: Node, view: ParameterView, jsx: boolean): boolean {
  const { ast } = view.native;
  if (!ast.isBinaryExpression(node)) return false;
  const { scalarOperators, returnedOperands: returned } = operatorKinds(ast);
  const operands = jsx && returned.has(node.operatorToken.kind);
  return scalarOperators.has(node.operatorToken.kind) && scalarView(node.left, view, operands) && scalarView(node.right, view, operands);
}

function scalarLiteral(ast: NativeAst, node: Node): boolean {
  const k = ast.SyntaxKind;
  return ast.isStringLiteralLikeNode(node) || ast.isNumericLiteral(node) || ast.isBigIntLiteral(node) || ast.isJsxText(node) ||
    node.kind === k.TrueKeyword || node.kind === k.FalseKeyword || node.kind === k.NullKeyword;
}

function memberRead(node: Node, view: ParameterView): boolean {
  const { ast, checker } = view.native;
  if (!ast.isPropertyAccessExpression(node) && !ast.isElementAccessExpression(node)) return false;
  if (!view.root || !ast.isIdentifier(node.expression) || checker.getSymbolAtLocation(node.expression)?.id !== view.root.id) return false;
  const key = ast.isPropertyAccessExpression(node)
    ? (ast.isIdentifier(node.name) ? node.name.text : undefined)
    : node.argumentExpression && (ast.isStringLiteralLikeNode(node.argumentExpression) || ast.isNumericLiteral(node.argumentExpression))
      ? node.argumentExpression.text : undefined;
  return key !== undefined && readField(node, key, view);
}

function readField(node: Node, key: string, view: ParameterView): boolean {
  const { checker } = view.native;
  if (!checker.getPropertyOfType(view.props, key) || !scalarType(view.native, checker.getTypeAtLocation(node))) return false;
  view.reads.add(key);
  return true;
}

function jsxView(node: Node, view: ParameterView): boolean {
  const { ast } = view.native;
  if (ast.isJsxFragment(node)) return node.children.every((child) => scalarView(child, view, true));
  if (ast.isJsxElement(node)) return jsxView(node.openingElement, view) && node.children.every((child) => scalarView(child, view, true));
  if (!ast.isJsxOpeningElement(node) && !ast.isJsxSelfClosingElement(node)) return false;
  if (!ast.isIdentifier(node.tagName) || !/^[a-z][A-Za-z0-9]*$/u.test(node.tagName.text)) return false;
  return node.attributes.properties.every((attribute) => intrinsicAttribute(attribute, view));
}

function intrinsicAttribute(attribute: Node, view: ParameterView): boolean {
  const { ast } = view.native;
  return ast.isJsxAttribute(attribute) && ast.isIdentifier(attribute.name) && attribute.name.text !== "is" &&
    (!attribute.initializer || scalarView(attribute.initializer, view));
}
