/** @fileoverview _scalar-parameter-view — trace scalar parameter reads in a pure returned view. */
import ts from "typescript";

const SCALAR_OPERATORS: ReadonlySet<ts.SyntaxKind> = new Set([
  ts.SyntaxKind.PlusToken, ts.SyntaxKind.MinusToken, ts.SyntaxKind.AsteriskToken, ts.SyntaxKind.SlashToken, ts.SyntaxKind.PercentToken, ts.SyntaxKind.AsteriskAsteriskToken,
  ts.SyntaxKind.LessThanToken, ts.SyntaxKind.LessThanEqualsToken, ts.SyntaxKind.GreaterThanToken, ts.SyntaxKind.GreaterThanEqualsToken,
  ts.SyntaxKind.EqualsEqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsEqualsToken, ts.SyntaxKind.EqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsToken,
  ts.SyntaxKind.AmpersandAmpersandToken, ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionToken,
]);
const SCALAR_PREFIXES: ReadonlySet<ts.SyntaxKind> = new Set([ts.SyntaxKind.PlusToken, ts.SyntaxKind.MinusToken, ts.SyntaxKind.ExclamationToken, ts.SyntaxKind.TildeToken]);

interface ParameterView {
  readonly checker: ts.TypeChecker;
  readonly props: ts.Type;
  readonly root: ts.Symbol | undefined;
  readonly aliases: ReadonlyMap<ts.Symbol, string>;
  readonly reads: Set<string>;
  readonly jsx: boolean;
}

/** Accept one pure returned view, retaining every bound or inspected root field. */
export function scalarParameterView(parameter: ts.ParameterDeclaration, body: ts.ConciseBody, checker: ts.TypeChecker): ReadonlySet<string> | null {
  return parameterReads(parameter, body, checker, true);
}

/** Scalar consumers do not inherit the JSX runtime proof used by component views. */
export function scalarParameterReads(parameter: ts.ParameterDeclaration, body: ts.ConciseBody, checker: ts.TypeChecker): ReadonlySet<string> | null {
  return parameterReads(parameter, body, checker, false);
}

function parameterReads(parameter: ts.ParameterDeclaration, body: ts.ConciseBody, checker: ts.TypeChecker, jsx: boolean): ReadonlySet<string> | null {
  if (parameter.dotDotDotToken || parameter.initializer || ts.isArrayBindingPattern(parameter.name)) return null;
  const root = ts.isIdentifier(parameter.name) ? checker.getSymbolAtLocation(parameter.name) : undefined;
  if (ts.isIdentifier(parameter.name) && !root) return null;
  const reads = new Set<string>();
  const aliases = parameterAliases(parameter.name, checker, reads);
  if (!aliases) return null;
  const expression = returnedExpression(body);
  const view = { checker, props: checker.getTypeAtLocation(parameter), root, aliases, reads, jsx };
  return expression && scalarView(expression, view) ? reads : null;
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

function scalarView(node: ts.Node, view: ParameterView): boolean {
  if (scalarLiteral(node)) return true;
  if (ts.isIdentifier(node)) {
    const binding = view.checker.getSymbolAtLocation(node);
    const key = binding && view.aliases.get(binding);
    return key !== undefined && readField(node, key, view);
  }
  if (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) return memberRead(node, view);
  if (ts.isParenthesizedExpression(node) || ts.isNonNullExpression(node) || ts.isTypeOfExpression(node)) return scalarView(node.expression, view);
  if (ts.isConditionalExpression(node)) return scalarView(node.condition, view) && scalarView(node.whenTrue, view) && scalarView(node.whenFalse, view);
  if (ts.isBinaryExpression(node)) return SCALAR_OPERATORS.has(node.operatorToken.kind) && scalarView(node.left, view) && scalarView(node.right, view);
  if (ts.isPrefixUnaryExpression(node)) return SCALAR_PREFIXES.has(node.operator) && scalarView(node.operand, view);
  if (ts.isTemplateExpression(node)) return node.templateSpans.every((span) => scalarView(span.expression, view));
  return view.jsx && jsxView(node, view);
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
  if (ts.isJsxExpression(node)) return !node.dotDotDotToken && (!node.expression || scalarView(node.expression, view));
  if (ts.isJsxFragment(node)) return node.children.every((child) => scalarView(child, view));
  if (ts.isJsxElement(node)) return jsxView(node.openingElement, view) && node.children.every((child) => scalarView(child, view));
  if (!ts.isJsxOpeningElement(node) && !ts.isJsxSelfClosingElement(node)) return false;
  if (!ts.isIdentifier(node.tagName) || !/^[a-z][A-Za-z0-9]*$/u.test(node.tagName.text)) return false;
  return node.attributes.properties.every((attribute) => intrinsicAttribute(attribute, view));
}

function intrinsicAttribute(attribute: ts.JsxAttributeLike, view: ParameterView): boolean {
  return ts.isJsxAttribute(attribute) && ts.isIdentifier(attribute.name) && attribute.name.text !== "is" &&
    (!attribute.initializer || scalarView(attribute.initializer, view));
}
