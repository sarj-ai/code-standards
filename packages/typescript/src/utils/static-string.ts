/**
 * @fileoverview static-string — static string values, scope lookup and
 * property names, without `@typescript-eslint/utils`.
 *
 * `findVariable`, `getPropertyName` and `getStringIfConstant` follow
 * @eslint-community/eslint-utils 4.10.1 (MIT, Toru Nagashima). Called without a
 * scope, as every port does, `getStaticValue` only folds literals and operators
 * over them; `staticValue` below covers that subset.
 */

import type { ESTree, Node, Scope, SourceCode, TsVariable } from "../types.js";
import { tsVariable } from "../types.js";
import { unwrapExpression } from "./ast.js";

export function staticString(node: Node | undefined | null): string | null {
  if (node === undefined || node === null) return null;
  const value = unwrapExpression(node);
  if (value.type === "Literal" && typeof value.value === "string") return value.value;
  return value.type === "TemplateLiteral" && value.expressions.length === 0
    ? value.quasis[0]?.value.cooked ?? null : null;
}

/** Find a variable by name from a scope outward. */
export function findVariable(initialScope: Scope, name: string): TsVariable | null {
  let scope: Scope | null = initialScope;
  while (scope !== null) {
    const variable = scope.set.get(name);
    if (variable !== undefined) return tsVariable(variable);
    scope = scope.upper;
  }
  return null;
}

const SCOPED_STRING_VALUES = new WeakMap<object, WeakMap<TsVariable, string | null>>();

/** Follow stable local aliases without evaluating function or object-derived values. */
export function scopedStaticString(node: Node, sourceCode: SourceCode): string | null {
  let value = unwrapExpression(node);
  if (value.type !== "Identifier") return staticString(value);
  // Oxlint reuses one SourceCode object for every file, so cache per AST.
  const key = sourceCode.ast;
  let values = SCOPED_STRING_VALUES.get(key);
  if (values === undefined) {
    values = new WeakMap<TsVariable, string | null>();
    SCOPED_STRING_VALUES.set(key, values);
  }
  const seen = new Set<TsVariable>();
  const pending: TsVariable[] = [];
  let result: string | null = null;
  while (value.type === "Identifier") {
    const binding = findVariable(sourceCode.getScope(value), value.name);
    if (binding === null || seen.has(binding)) break;
    if (values.has(binding)) {
      result = values.get(binding) ?? null;
      break;
    }
    seen.add(binding);
    pending.push(binding);
    const definition = binding.defs.length === 1 ? binding.defs[0] : undefined;
    if (definition?.type !== "Variable") break;
    const declarator = definition.node as ESTree.VariableDeclarator;
    if (declarator.id.type !== "Identifier" || declarator.init === null ||
      binding.references.some((reference) => reference.isWrite() && reference.init !== true)) break;
    value = unwrapExpression(declarator.init);
    if (value.type !== "Identifier") result = staticString(value);
  }
  for (const binding of pending) values.set(binding, result);
  return result;
}

type NamedNode = ESTree.MemberExpression | ESTree.ObjectProperty | ESTree.MethodDefinition | ESTree.PropertyDefinition;

/** The static name of a member or property key, as eslint-utils `getPropertyName` without a scope. */
export function getPropertyName(node: Node): string | null {
  switch (node.type) {
    case "MemberExpression":
      if (node.computed) return getStringIfConstant(node.property);
      if (node.property.type === "PrivateIdentifier") return null;
      return (node.property as { name: string }).name;
    case "Property":
    case "MethodDefinition":
    case "PropertyDefinition": {
      const named = node as NamedNode & { key: Node; computed: boolean };
      if (named.computed) return getStringIfConstant(named.key);
      if (named.key.type === "Literal") return String((named.key as { value: unknown }).value);
      if (named.key.type === "PrivateIdentifier") return null;
      return (named.key as { name: string }).name;
    }
    default:
      return null;
  }
}

/** Preserve literal property decoding and additionally resolve stable local string keys. */
export function staticPropertyName(
  node: ESTree.MemberExpression | ESTree.ObjectProperty,
  sourceCode: SourceCode,
): string | null {
  const direct = getPropertyName(node);
  if (direct !== null || !node.computed) return direct;
  const key = node.type === "MemberExpression" ? node.property : node.key;
  return scopedStaticString(key, sourceCode);
}

function getStringIfConstant(node: Node | null | undefined): string | null {
  if (node === null || node === undefined) return null;
  if (node.type === "Literal" && node.value === null) {
    const literal = node as { regex?: { pattern: string; flags: string }; bigint?: string };
    if (literal.regex) return `/${literal.regex.pattern}/${literal.regex.flags}`;
    if (literal.bigint) return literal.bigint;
  }
  const evaluated = staticValue(node);
  if (evaluated) {
    try {
      return String(evaluated.value);
    } catch {
      // String(Symbol.prototype) throws.
    }
  }
  return null;
}

type Static = { readonly value: unknown } | null;

type LiteralNode = Extract<Node, { type: "Literal" }>;
type UnaryNode = Extract<Node, { type: "UnaryExpression" }>;
type LogicalNode = Extract<Node, { type: "LogicalExpression" }>;
type TemplateNode = Extract<Node, { type: "TemplateLiteral" }>;
type ArrayNode = Extract<Node, { type: "ArrayExpression" }>;

/** Fold literals and operators over them, as eslint-utils `getStaticValue(node, null)`. */
export function staticValue(node: Node | null | undefined): Static {
  if (node === null || node === undefined) return null;
  switch (node.type) {
    case "Literal":
      return literalValue(node);
    case "TemplateLiteral":
      return templateValue(node);
    case "BinaryExpression": {
      if (node.operator === "in" || node.operator === "instanceof") return null;
      const left = staticValue(node.left);
      const right = left === null ? null : staticValue(node.right);
      if (left === null || right === null) return null;
      return binary(node.operator, left.value, right.value);
    }
    case "LogicalExpression":
      return logicalValue(node);
    case "UnaryExpression":
      return unaryValue(node);
    case "ConditionalExpression": {
      const test = staticValue(node.test);
      return test === null ? null : staticValue(test.value ? node.consequent : node.alternate);
    }
    case "SequenceExpression": {
      const last = node.expressions.at(-1);
      return last === undefined ? null : staticValue(last);
    }
    case "ArrayExpression":
      return arrayValue(node);
    case "ChainExpression":
    case "TSAsExpression":
    case "TSSatisfiesExpression":
    case "TSNonNullExpression":
    case "TSTypeAssertion":
      return staticValue(node.expression);
    default:
      return null;
  }
}

function literalValue(node: LiteralNode): Static {
  const literal = node as { value: unknown; regex?: { pattern: string; flags: string }; bigint?: string };
  // ESTree gives `value: null` for a bigint or regex literal the runtime cannot represent; rebuild it.
  if (literal.value !== null) return { value: literal.value };
  if (literal.bigint !== undefined) return { value: BigInt(literal.bigint) };
  if (literal.regex === undefined) return { value: null };
  try {
    return { value: new RegExp(literal.regex.pattern, literal.regex.flags) };
  } catch {
    return null;
  }
}

function templateValue(node: TemplateNode): Static {
  const expressions: unknown[] = [];
  for (const expression of node.expressions) {
    const value = staticValue(expression);
    if (value === null) return null;
    expressions.push(value.value);
  }
  let text = node.quasis[0]?.value.cooked ?? "";
  for (let i = 0; i < expressions.length; i++) {
    text += String(expressions[i]) + (node.quasis[i + 1]?.value.cooked ?? "");
  }
  return { value: text };
}

function logicalValue(node: LogicalNode): Static {
  const left = staticValue(node.left);
  if (left === null) return null;
  return shortCircuits(node.operator, left.value) ? left : staticValue(node.right);
}

/** Whether a logical expression's left operand alone decides its value. */
function shortCircuits(operator: string, left: unknown): boolean {
  if (operator === "||") return Boolean(left);
  if (operator === "&&") return !left;
  return left !== null && left !== undefined;
}

function unaryValue(node: UnaryNode): Static {
  if (node.operator === "delete") return null;
  if (node.operator === "void") return { value: undefined };
  const argument = staticValue(node.argument);
  if (argument === null) return null;
  const value = argument.value as never;
  switch (node.operator) {
    case "-": return { value: -value };
    case "+": return { value: +value };
    case "!": return { value: !value };
    case "~": return { value: ~value };
    case "typeof": return { value: typeof value };
    default: return null;
  }
}

function arrayValue(node: ArrayNode): Static {
  const values: unknown[] = [];
  for (const element of node.elements) {
    if (element === null) {
      values.push(undefined);
      continue;
    }
    const value = staticValue(element.type === "SpreadElement" ? element.argument : element);
    if (value === null) return null;
    if (element.type !== "SpreadElement") values.push(value.value);
    else if (Array.isArray(value.value)) values.push(...(value.value as unknown[]));
    else return null;
  }
  return { value: values };
}

function binary(operator: string, left: unknown, right: unknown): Static {
  const l = left as never;
  const r = right as never;
  switch (operator) {
    case "==": return { value: l == r };
    case "!=": return { value: l != r };
    case "===": return { value: l === r };
    case "!==": return { value: l !== r };
    case "<": return { value: l < r };
    case "<=": return { value: l <= r };
    case ">": return { value: l > r };
    case ">=": return { value: l >= r };
    case "<<": return { value: l << r };
    case ">>": return { value: l >> r };
    case ">>>": return { value: l >>> r };
    case "+": return { value: (l as string) + (r as string) };
    case "-": return { value: l - r };
    case "*": return { value: l * r };
    case "/": return { value: l / r };
    case "%": return { value: l % r };
    case "**": return { value: l ** r };
    case "|": return { value: l | r };
    case "^": return { value: l ^ r };
    case "&": return { value: l & r };
    default: return null;
  }
}
