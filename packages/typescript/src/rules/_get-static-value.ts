/**
 * @fileoverview _get-static-value — `getStaticValue(node, scope)` without ESLint.
 *
 * Port of `getStaticValue` from @eslint-community/eslint-utils 4.10.1 (MIT, Toru Nagashima), the
 * scoped form: identifiers resolve to built-in globals and to effectively-constant variables.
 * `utils/static-string.ts` `staticValue` covers only the scope-less form, which the original
 * rule's `ASTUtils.getStaticValue(node, scope)` calls go beyond.
 */

import type { Node, Scope, TsVariable } from "../types.js";
import { tsVariable } from "../types.js";

type StaticValue = { readonly value: unknown; readonly optional?: true } | null;
type AnyNode = Node & Record<string, unknown>;
type Callable = (...args: unknown[]) => unknown;

const GLOBAL_OBJECT = globalThis as unknown as Record<string, unknown>;

const BUILTIN_NAMES: ReadonlySet<string> = new Set([
  "Array", "ArrayBuffer", "BigInt", "BigInt64Array", "BigUint64Array", "Boolean", "DataView", "Date",
  "decodeURI", "decodeURIComponent", "encodeURI", "encodeURIComponent", "escape", "Float32Array",
  "Float64Array", "Function", "Infinity", "Int16Array", "Int32Array", "Int8Array", "isFinite", "isNaN",
  "isPrototypeOf", "JSON", "Map", "Math", "NaN", "Number", "Object", "parseFloat", "parseInt", "Promise",
  "Proxy", "Reflect", "RegExp", "Set", "String", "Symbol", "Uint16Array", "Uint32Array", "Uint8Array",
  "Uint8ClampedArray", "undefined", "unescape", "WeakMap", "WeakSet",
]);

const LEGACY = GLOBAL_OBJECT as { escape?: unknown; unescape?: unknown; isPrototypeOf?: unknown };

const CALL_ALLOWED: ReadonlySet<unknown> = new Set(
  [
    ...members(Array, ["isArray", "of"]),
    ...members(Array.prototype, [
      "at", "concat", "entries", "every", "filter", "find", "findIndex", "flat", "includes", "indexOf", "join", "keys",
      "lastIndexOf", "slice", "some", "toString", "values",
    ]),
    typeof BigInt === "function" ? BigInt : undefined,
    Boolean, Date, ...members(Date, ["parse"]), decodeURI, decodeURIComponent, encodeURI, encodeURIComponent, LEGACY.escape,
    isFinite, isNaN, LEGACY.isPrototypeOf, Map, ...members(Map.prototype, ["entries", "get", "has", "keys", "values"]),
    ...members(Math, Object.getOwnPropertyNames(Math).filter((key) => key !== "random")),
    Number, ...members(Number, ["isFinite", "isNaN", "parseFloat", "parseInt"]),
    ...members(Number.prototype, ["toExponential", "toFixed", "toPrecision", "toString"]),
    Object, ...members(Object, ["entries", "is", "isExtensible", "isFrozen", "isSealed", "keys", "values"]),
    parseFloat, parseInt, RegExp, Set, ...members(Set.prototype, ["entries", "has", "keys", "values"]),
    String, ...members(String, ["fromCharCode", "fromCodePoint", "raw"]),
    ...members(String.prototype, [
      "at", "charAt", "charCodeAt", "codePointAt", "concat", "endsWith", "includes", "indexOf", "lastIndexOf",
      "normalize", "padEnd", "padStart", "slice", "startsWith", "substr", "substring", "toLowerCase", "toString",
      "toUpperCase", "trim", "trimEnd", "trimLeft", "trimRight", "trimStart",
    ]),
    ...members(Symbol, ["for", "keyFor"]), LEGACY.unescape,
  ].filter((value) => typeof value === "function"),
);

const CALL_PASS_THROUGH: ReadonlySet<unknown> = new Set([Object.freeze, Object.preventExtensions, Object.seal]);

const GETTER_ALLOWED: readonly (readonly [abstract new (...args: never[]) => unknown, ReadonlySet<string>])[] = [
  [Map, new Set(["size"])],
  [RegExp, new Set(["dotAll", "flags", "global", "hasIndices", "ignoreCase", "multiline", "source", "sticky", "unicode"])],
  [Set, new Set(["size"])],
];

/** The named members of a built-in, read by name so the table holds the functions themselves, never detached calls. */
function members(owner: object, names: readonly string[]): readonly unknown[] {
  return names.map((name): unknown => Reflect.get(owner, name));
}

function isGetter(object: unknown, name: PropertyKey): boolean {
  const descriptor = getPropertyDescriptor(object, name);
  return descriptor != null && descriptor.get != null;
}

function getPropertyDescriptor(object: unknown, name: PropertyKey): PropertyDescriptor | null {
  let x = object;
  while ((typeof x === "object" || typeof x === "function") && x !== null) {
    const descriptor = Object.getOwnPropertyDescriptor(x, name);
    if (descriptor) return descriptor;
    x = Object.getPrototypeOf(x);
  }
  return null;
}

function findVariableFrom(initialScope: Scope, node: Node & { name: string }): TsVariable | null {
  let scope: Scope | null = getInnermostScope(initialScope, node);
  while (scope != null) {
    const variable = scope.set.get(node.name);
    if (variable != null) return tsVariable(variable);
    scope = scope.upper;
  }
  return null;
}

function getInnermostScope(initialScope: Scope, node: Node): Scope {
  const location = node.range[0];
  let scope = initialScope;
  let found: boolean;
  do {
    found = false;
    for (const childScope of scope.childScopes) {
      const range = childScope.block.range;
      if (range[0] <= location && location < range[1]) {
        scope = childScope;
        found = true;
        break;
      }
    }
  } while (found);
  return scope;
}

function getElementValues(nodeList: readonly (AnyNode | null)[], initialScope: Scope | null): unknown[] | null {
  const valueList: unknown[] = [];
  for (let i = 0; i < nodeList.length; ++i) {
    const elementNode = nodeList[i];
    if (elementNode == null) {
      valueList.length = i + 1;
    } else if (elementNode.type === "SpreadElement") {
      const argument = getStaticValueR(elementNode["argument"] as AnyNode, initialScope);
      if (argument == null) return null;
      valueList.push(...(argument.value as Iterable<unknown>));
    } else {
      const element = getStaticValueR(elementNode, initialScope);
      if (element == null) return null;
      valueList.push(element.value);
    }
  }
  return valueList;
}

function isBuiltinGlobal(variable: TsVariable | null): boolean {
  return variable != null && variable.defs.length === 0 && BUILTIN_NAMES.has(variable.name) && variable.name in GLOBAL_OBJECT;
}

function canBeConsideredConst(variable: TsVariable): boolean {
  if (variable.defs.length !== 1) return false;
  const definition = variable.defs[0] as unknown as { parent: { kind?: string } | null; type: string };
  return Boolean(definition.parent && definition.type === "Variable" &&
    (definition.parent.kind === "const" || isEffectivelyConst(variable)));
}

function isEffectivelyConst(variable: TsVariable): boolean {
  const refs = variable.references;
  const inits = refs.filter((reference) => reference.init).length;
  const reads = refs.filter((reference) => reference.isReadOnly()).length;
  return inits === 1 && reads + inits === refs.length;
}

const MUTATION_ARRAY_METHODS: ReadonlySet<unknown> = new Set(["copyWithin", "fill", "pop", "push", "reverse", "shift", "sort", "splice", "unshift"]);

function hasMutationInProperty(variable: TsVariable, initialScope: Scope | null): boolean {
  return variable.references.some((reference) => mutatesProperty(reference.identifier as AnyNode, initialScope));
}

/** The member chain on `identifier` is assigned, updated or receives an array-mutating method call. */
function mutatesProperty(identifier: AnyNode, initialScope: Scope | null): boolean {
  let node = identifier;
  while (node.parent?.type === "MemberExpression") node = node.parent as AnyNode;
  const parent = node.parent as AnyNode | null;
  if (parent == null) return false;
  if ((parent.type === "AssignmentExpression" && parent["left"] === node) ||
    (parent.type === "UpdateExpression" && parent["argument"] === node)) return true;
  if (parent.type !== "CallExpression" || parent["callee"] !== node || node.type !== "MemberExpression") return false;
  const methodName = getStaticPropertyNameValue(node, initialScope);
  return methodName != null && methodName.value != null && MUTATION_ARRAY_METHODS.has(methodName.value);
}

function binary(operator: string, left: never, right: never): StaticValue {
  switch (operator) {
    case "==": return { value: left == right };
    case "!=": return { value: left != right };
    case "===": return { value: left === right };
    case "!==": return { value: left !== right };
    case "<": return { value: left < right };
    case "<=": return { value: left <= right };
    case ">": return { value: left > right };
    case ">=": return { value: left >= right };
    case "<<": return { value: left << right };
    case ">>": return { value: left >> right };
    case ">>>": return { value: left >>> right };
    case "+": return { value: (left as number) + (right as number) };
    case "-": return { value: left - right };
    case "*": return { value: left * right };
    case "/": return { value: left / right };
    case "%": return { value: left % right };
    case "**": return { value: left ** right };
    case "|": return { value: left | right };
    case "^": return { value: left ^ right };
    case "&": return { value: left & right };
    default: return null;
  }
}

function callResult(func: unknown, receiver: unknown, args: unknown[]): StaticValue | undefined {
  if (CALL_ALLOWED.has(func)) return { value: (func as Callable).apply(receiver, args) };
  if (CALL_PASS_THROUGH.has(func)) return { value: args[0] };
  return undefined;
}

type Operation = (node: AnyNode, initialScope: Scope | null) => StaticValue;

const OPERATIONS: Readonly<Record<string, Operation>> = {
  ArrayExpression(node, initialScope) {
    const elements = getElementValues(node["elements"] as (AnyNode | null)[], initialScope);
    return elements != null ? { value: elements } : null;
  },
  AssignmentExpression(node, initialScope) {
    return node["operator"] === "=" ? getStaticValueR(node["right"] as AnyNode, initialScope) : null;
  },
  BinaryExpression(node, initialScope) {
    const operator = node["operator"] as string;
    if (operator === "in" || operator === "instanceof") return null;
    const left = getStaticValueR(node["left"] as AnyNode, initialScope);
    const right = getStaticValueR(node["right"] as AnyNode, initialScope);
    return left != null && right != null ? binary(operator, left.value as never, right.value as never) : null;
  },
  CallExpression(node, initialScope) {
    const calleeNode = node["callee"] as AnyNode;
    const args = getElementValues(node["arguments"] as AnyNode[], initialScope);
    if (args == null) return null;
    if (calleeNode.type === "MemberExpression") {
      if ((calleeNode["property"] as Node).type === "PrivateIdentifier") return null;
      const object = getStaticValueR(calleeNode["object"] as AnyNode, initialScope);
      if (object == null) return null;
      if (object.value == null && (object.optional || node["optional"])) return { value: undefined, optional: true };
      const property = getStaticPropertyNameValue(calleeNode, initialScope);
      if (property == null) return null;
      const receiver = object.value as Record<PropertyKey, unknown>;
      return callResult(receiver[property.value as PropertyKey], receiver, args) ?? null;
    }
    const callee = getStaticValueR(calleeNode, initialScope);
    if (callee == null) return null;
    if (callee.value == null && node["optional"]) return { value: undefined, optional: true };
    return callResult(callee.value, undefined, args) ?? null;
  },
  ConditionalExpression(node, initialScope) {
    const test = getStaticValueR(node["test"] as AnyNode, initialScope);
    if (test == null) return null;
    return test.value
      ? getStaticValueR(node["consequent"] as AnyNode, initialScope)
      : getStaticValueR(node["alternate"] as AnyNode, initialScope);
  },
  ExpressionStatement(node, initialScope) {
    return getStaticValueR(node["expression"] as AnyNode, initialScope);
  },
  Identifier(node, initialScope) {
    if (initialScope == null) return null;
    const variable = findVariableFrom(initialScope, node as AnyNode & { name: string });
    if (variable == null) return null;
    if (isBuiltinGlobal(variable)) return { value: GLOBAL_OBJECT[variable.name] };
    if (!canBeConsideredConst(variable)) return null;
    const declarator = variable.defs[0]?.node as unknown as AnyNode;
    if ((declarator["id"] as Node).type !== "Identifier") return null;
    const init = getStaticValueR(declarator["init"] as AnyNode | null, initialScope);
    if (init && typeof init.value === "object" && init.value !== null && hasMutationInProperty(variable, initialScope)) return null;
    return init;
  },
  Literal(node) {
    if ((node["regex"] != null || node["bigint"] != null) && node["value"] == null) return null;
    return { value: node["value"] };
  },
  LogicalExpression(node, initialScope) {
    const left = getStaticValueR(node["left"] as AnyNode, initialScope);
    if (left == null) return null;
    const operator = node["operator"];
    if ((operator === "||" && Boolean(left.value) === true) ||
      (operator === "&&" && Boolean(left.value) === false) ||
      (operator === "??" && left.value != null)) return left;
    const right = getStaticValueR(node["right"] as AnyNode, initialScope);
    return right != null ? right : null;
  },
  MemberExpression(node, initialScope) {
    if ((node["property"] as Node).type === "PrivateIdentifier") return null;
    const object = getStaticValueR(node["object"] as AnyNode, initialScope);
    if (object == null) return null;
    if (object.value == null && (object.optional || node["optional"])) return { value: undefined, optional: true };
    const property = getStaticPropertyNameValue(node, initialScope);
    if (property == null) return null;
    const key = property.value as PropertyKey;
    const target = object.value as Record<PropertyKey, unknown>;
    if (!isGetter(target, key)) return { value: target[key] };
    for (const [classFn, allowed] of GETTER_ALLOWED) {
      if (target instanceof classFn && allowed.has(key as string)) return { value: target[key] };
    }
    return null;
  },
  ChainExpression(node, initialScope) {
    const expression = getStaticValueR(node["expression"] as AnyNode, initialScope);
    return expression != null ? { value: expression.value } : null;
  },
  NewExpression(node, initialScope) {
    const callee = getStaticValueR(node["callee"] as AnyNode, initialScope);
    const args = getElementValues(node["arguments"] as AnyNode[], initialScope);
    if (callee != null && args != null && CALL_ALLOWED.has(callee.value)) {
      const Func = callee.value as new (...values: unknown[]) => unknown;
      return { value: new Func(...args) };
    }
    return null;
  },
  ObjectExpression(node, initialScope) {
    const object: Record<PropertyKey, unknown> = {};
    for (const propertyNode of node["properties"] as AnyNode[]) {
      if (propertyNode.type === "Property") {
        if (propertyNode["kind"] !== "init") return null;
        const key = getStaticPropertyNameValue(propertyNode, initialScope);
        const value = getStaticValueR(propertyNode["value"] as AnyNode, initialScope);
        if (key == null || value == null) return null;
        object[key.value as PropertyKey] = value.value;
      } else if (propertyNode.type === "SpreadElement") {
        const argument = getStaticValueR(propertyNode["argument"] as AnyNode, initialScope);
        if (argument == null) return null;
        Object.assign(object, argument.value);
      } else {
        return null;
      }
    }
    return { value: object };
  },
  SequenceExpression(node, initialScope) {
    const expressions = node["expressions"] as AnyNode[];
    return getStaticValueR(expressions[expressions.length - 1], initialScope);
  },
  TaggedTemplateExpression(node, initialScope) {
    const tag = getStaticValueR(node["tag"] as AnyNode, initialScope);
    const quasi = node["quasi"] as AnyNode;
    const expressions = getElementValues(quasi["expressions"] as AnyNode[], initialScope);
    if (tag != null && expressions != null && tag.value === String.raw) {
      const quasis = quasi["quasis"] as { value: { cooked: string; raw: string } }[];
      const strings = Object.assign(quasis.map((q) => q.value.cooked), { raw: quasis.map((q) => q.value.raw) });
      return { value: String.raw(strings, ...expressions) };
    }
    return null;
  },
  TemplateLiteral(node, initialScope) {
    const expressions = getElementValues(node["expressions"] as AnyNode[], initialScope);
    if (expressions == null) return null;
    const quasis = node["quasis"] as { value: { cooked: string } }[];
    let value: unknown = quasis[0]?.value.cooked;
    for (let i = 0; i < expressions.length; ++i) {
      value = (value as string) + (expressions[i] as string);
      value = (value as string) + (quasis[i + 1]?.value.cooked as string);
    }
    return { value };
  },
  UnaryExpression(node, initialScope) {
    const operator = node["operator"];
    if (operator === "delete") return null;
    if (operator === "void") return { value: undefined };
    const arg = getStaticValueR(node["argument"] as AnyNode, initialScope);
    if (arg == null) return null;
    const value = arg.value as never;
    switch (operator) {
      case "-": return { value: -value };
      case "+": return { value: +value };
      case "!": return { value: !value };
      case "~": return { value: ~value };
      case "typeof": return { value: typeof value };
      default: return null;
    }
  },
  TSAsExpression(node, initialScope) { return getStaticValueR(node["expression"] as AnyNode, initialScope); },
  TSSatisfiesExpression(node, initialScope) { return getStaticValueR(node["expression"] as AnyNode, initialScope); },
  TSTypeAssertion(node, initialScope) { return getStaticValueR(node["expression"] as AnyNode, initialScope); },
  TSNonNullExpression(node, initialScope) { return getStaticValueR(node["expression"] as AnyNode, initialScope); },
  TSInstantiationExpression(node, initialScope) { return getStaticValueR(node["expression"] as AnyNode, initialScope); },
};

function getStaticValueR(node: AnyNode | null | undefined, initialScope: Scope | null): StaticValue {
  if (node != null && Object.hasOwn(OPERATIONS, node.type)) {
    return (OPERATIONS[node.type] as Operation)(node, initialScope);
  }
  return null;
}

function getStaticPropertyNameValue(node: AnyNode, initialScope: Scope | null): StaticValue {
  const nameNode = (node.type === "Property" ? node["key"] : node["property"]) as AnyNode;
  if (node["computed"]) return getStaticValueR(nameNode, initialScope);
  if (nameNode.type === "Identifier") return { value: nameNode["name"] };
  if (nameNode.type === "Literal") {
    if (nameNode["bigint"]) return { value: nameNode["bigint"] };
    return { value: String(nameNode["value"]) };
  }
  return null;
}

/** The static value of `node`, resolving identifiers from `initialScope`, or null. */
export function getStaticValue(node: Node, initialScope: Scope | null = null): StaticValue {
  try {
    return getStaticValueR(node as AnyNode, initialScope);
  } catch {
    // eslint-disable-next-line @sarj/no-sentinel-return-on-catch -- Verbatim eslint-utils getStaticValue contract: evaluating a user getter or call may throw, and that means "not statically known" (null), as the original rules observe.
    return null;
  }
}
