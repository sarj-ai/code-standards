/** @fileoverview _scalar-parameter-view — trace scalar parameter reads in a pure returned view. */
import ts from "typescript";

import { checkedNativeSource } from "./_checked-native-source.js";
import { constInitializer } from "./_native-const-value.js";

const SCALAR_OPERATORS: ReadonlySet<ts.SyntaxKind> = new Set([
  ts.SyntaxKind.PlusToken, ts.SyntaxKind.MinusToken, ts.SyntaxKind.AsteriskToken, ts.SyntaxKind.SlashToken, ts.SyntaxKind.PercentToken, ts.SyntaxKind.AsteriskAsteriskToken,
  ts.SyntaxKind.LessThanToken, ts.SyntaxKind.LessThanEqualsToken, ts.SyntaxKind.GreaterThanToken, ts.SyntaxKind.GreaterThanEqualsToken,
  ts.SyntaxKind.EqualsEqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsEqualsToken, ts.SyntaxKind.EqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsToken,
  ts.SyntaxKind.AmpersandAmpersandToken, ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionToken,
]);
const SCALAR_PREFIXES: ReadonlySet<ts.SyntaxKind> = new Set([ts.SyntaxKind.PlusToken, ts.SyntaxKind.MinusToken, ts.SyntaxKind.ExclamationToken, ts.SyntaxKind.TildeToken]);
export const RETURNED_OPERANDS: ReadonlySet<ts.SyntaxKind> = new Set([ts.SyntaxKind.AmpersandAmpersandToken, ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionToken]);

interface ParameterView {
  readonly checker: ts.TypeChecker;
  readonly callProgram: ts.Program | undefined;
  readonly props: ts.Type;
  readonly root: ts.Symbol | undefined;
  readonly aliases: ReadonlyMap<ts.Symbol, string>;
  readonly reads: Set<string>;
}

/** Accept one pure returned view, retaining every bound or inspected root field. */
export function scalarParameterView(parameter: ts.ParameterDeclaration, body: ts.ConciseBody, checker: ts.TypeChecker): ReadonlySet<string> | null {
  return parameterReads(parameter, body, checker, true);
}

/** Scalar consumers do not inherit the JSX runtime proof used by component views. */
export function scalarParameterReads(parameter: ts.ParameterDeclaration, body: ts.ConciseBody, checker: ts.TypeChecker, callProgram?: ts.Program): ReadonlySet<string> | null {
  return parameterReads(parameter, body, checker, false, callProgram);
}

function parameterReads(parameter: ts.ParameterDeclaration, body: ts.ConciseBody, checker: ts.TypeChecker, jsx: boolean, callProgram?: ts.Program): ReadonlySet<string> | null {
  if (parameter.dotDotDotToken || parameter.initializer || ts.isArrayBindingPattern(parameter.name)) return null;
  const root = ts.isIdentifier(parameter.name) ? checker.getSymbolAtLocation(parameter.name) : undefined;
  if (ts.isIdentifier(parameter.name) && !root) return null;
  const reads = new Set<string>();
  const aliases = parameterAliases(parameter.name, checker, reads);
  if (!aliases) return null;
  const expression = returnedExpression(body);
  const view = { checker, props: checker.getTypeAtLocation(parameter), root, aliases, reads, callProgram };
  return expression && scalarView(expression, view, jsx) ? reads : null;
}

export function scalarType(type: ts.Type, allowUndefined = true): boolean {
  if (type.isUnion()) return type.types.every((part) => scalarType(part, allowUndefined));
  const flags = ts.TypeFlags.StringLike | ts.TypeFlags.NumberLike | ts.TypeFlags.BooleanLike | ts.TypeFlags.BigIntLike | ts.TypeFlags.Null;
  return (type.flags & (allowUndefined ? flags | ts.TypeFlags.Undefined : flags)) !== 0;
}

function parameterAliases(name: ts.Identifier | ts.ObjectBindingPattern, checker: ts.TypeChecker, reads: Set<string>): ReadonlyMap<ts.Symbol, string> | null {
  const aliases = new Map<ts.Symbol, string>();
  if (ts.isIdentifier(name)) return aliases;
  for (const element of name.elements) {
    const key = element.propertyName ?? element.name;
    if (element.dotDotDotToken || element.initializer || !ts.isIdentifier(element.name) ||
      (!ts.isIdentifier(key) && !ts.isStringLiteralLike(key) && !ts.isNumericLiteral(key))) return null;
    const binding = checker.getSymbolAtLocation(element.name);
    if (!binding) return null;
    reads.add(key.text);
    aliases.set(binding, key.text);
  }
  return aliases;
}

export function returnedExpression(body: ts.ConciseBody): ts.Expression | undefined {
  if (!ts.isBlock(body)) return body;
  const statement = body.statements.length === 1 ? body.statements[0] : undefined;
  return statement && ts.isReturnStatement(statement) ? statement.expression : undefined;
}

function scalarView(node: ts.Node, view: ParameterView, jsx = false): boolean {
  if (scalarLiteral(node)) return true;
  if (ts.isCallExpression(node)) return !jsx && scalarCall(node, view);
  if (ts.isJsxExpression(node)) return !node.dotDotDotToken && (!node.expression || scalarView(node.expression, view, jsx));
  if (ts.isIdentifier(node)) {
    const binding = view.checker.getSymbolAtLocation(node);
    const key = binding && view.aliases.get(binding);
    return key !== undefined && readField(node, key, view);
  }
  if (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) return memberRead(node, view);
  return scalarOperation(node, view, jsx);
}

/** Compose scalar reads without changing which operands may return JSX. */
function scalarOperation(node: ts.Node, view: ParameterView, jsx: boolean): boolean {
  if (ts.isParenthesizedExpression(node) || ts.isNonNullExpression(node)) return scalarView(node.expression, view, jsx);
  if (ts.isTypeOfExpression(node)) return scalarView(node.expression, view);
  if (ts.isConditionalExpression(node)) return scalarView(node.condition, view) && scalarView(node.whenTrue, view, jsx) && scalarView(node.whenFalse, view, jsx);
  if (ts.isBinaryExpression(node)) return binaryView(node, view, jsx);
  if (ts.isPrefixUnaryExpression(node)) return SCALAR_PREFIXES.has(node.operator) && scalarView(node.operand, view);
  if (ts.isTemplateExpression(node)) return node.templateSpans.every((span) => scalarView(span.expression, view));
  return jsx && jsxView(node, view);
}

/** Only primitive values cross a local helper call; the parameter object never does. */
function scalarCall(node: ts.CallExpression, view: ParameterView): boolean {
  if (!view.callProgram || node.questionDotToken || node.typeArguments?.length || !ts.isIdentifier(node.expression) ||
    !node.arguments.length || node.arguments.some(ts.isSpreadElement)) return false;
  const declarations = view.checker.getSymbolAtLocation(node.expression)?.declarations;
  const declaration = declarations?.length === 1 ? declarations[0] : undefined;
  const helper = declaration && localHelper(declaration);
  if (!helper || helper.getSourceFile() !== node.getSourceFile() || helper.typeParameters?.length || !helper.type ||
    !node.arguments.every((argument) => scalarView(argument, view))) return false;
  if (!checkedNativeSource(view.callProgram, node.getSourceFile())) return false;
  const signature = view.checker.getResolvedSignature(node);
  return signature?.declaration === helper && !view.checker.getTypePredicateOfSignature(signature) &&
    scalarType(view.checker.getTypeAtLocation(node));
}

/** Imported, ambient, overloaded, contextual and aliased callees remain unsupported. */
function localHelper(node: ts.Declaration): ts.FunctionDeclaration | ts.ArrowFunction | undefined {
  if (ts.isFunctionDeclaration(node)) return node.body && ts.isSourceFile(node.parent) ? node : undefined;
  if (!ts.isVariableDeclaration(node) || node.type || !node.initializer || constInitializer(node) !== node.initializer ||
    !ts.isArrowFunction(node.initializer) || !ts.isVariableStatement(node.parent.parent) ||
    !ts.isSourceFile(node.parent.parent.parent)) return undefined;
  return node.initializer;
}

/** Logical operands may return React children; scalar operators require scalar operands. */
function binaryView(node: ts.BinaryExpression, view: ParameterView, jsx: boolean): boolean {
  const returned = jsx && RETURNED_OPERANDS.has(node.operatorToken.kind);
  return SCALAR_OPERATORS.has(node.operatorToken.kind) && scalarView(node.left, view, returned) && scalarView(node.right, view, returned);
}

function scalarLiteral(node: ts.Node): boolean {
  return ts.isStringLiteralLike(node) || ts.isNumericLiteral(node) || ts.isBigIntLiteral(node) || ts.isJsxText(node) ||
    node.kind === ts.SyntaxKind.TrueKeyword || node.kind === ts.SyntaxKind.FalseKeyword || node.kind === ts.SyntaxKind.NullKeyword;
}

function memberRead(node: ts.PropertyAccessExpression | ts.ElementAccessExpression, view: ParameterView): boolean {
  if (!view.root || !ts.isIdentifier(node.expression) || view.checker.getSymbolAtLocation(node.expression) !== view.root) return false;
  const key = ts.isPropertyAccessExpression(node) ? node.name.text : node.argumentExpression &&
    (ts.isStringLiteralLike(node.argumentExpression) || ts.isNumericLiteral(node.argumentExpression)) ? node.argumentExpression.text : undefined;
  return key !== undefined && readField(node, key, view);
}

function readField(node: ts.Node, key: string, view: ParameterView): boolean {
  if (!view.checker.getPropertyOfType(view.props, key) || !scalarType(view.checker.getTypeAtLocation(node))) return false;
  view.reads.add(key);
  return true;
}

function jsxView(node: ts.Node, view: ParameterView): boolean {
  if (ts.isJsxFragment(node)) return node.children.every((child) => scalarView(child, view, true));
  if (ts.isJsxElement(node)) return jsxView(node.openingElement, view) && node.children.every((child) => scalarView(child, view, true));
  if (!ts.isJsxOpeningElement(node) && !ts.isJsxSelfClosingElement(node)) return false;
  if (!ts.isIdentifier(node.tagName) || !/^[a-z][A-Za-z0-9]*$/u.test(node.tagName.text)) return false;
  return node.attributes.properties.every((attribute) => intrinsicAttribute(attribute, view));
}

function intrinsicAttribute(attribute: ts.JsxAttributeLike, view: ParameterView): boolean {
  return ts.isJsxAttribute(attribute) && ts.isIdentifier(attribute.name) && attribute.name.text !== "is" &&
    (!attribute.initializer || scalarView(attribute.initializer, view));
}
