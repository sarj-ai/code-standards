/**
 * @fileoverview prefer-module-level-constant — a literal-only collection or regex declared inside a function is rebuilt on every call.
 *
 * Port of the 18.x `prefer-module-level-constant` rule. Options and file
 * gates move to `before()`; the analysis is unchanged.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-module-level-constant.test.ts
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { tsVariable } from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isStoryFile, isTestFile, type FilePath } from "../utils/paths.js";
import { enclosingFunction } from "../utils/stable-value-binding.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { literalLookupHoistFix } from "./_literal-lookup-hoist-fix.js";

interface Options {
  readonly minElements?: number;
  readonly checkRegex?: boolean;
  readonly ignoreTestFiles?: boolean;
}

const DEFAULT_MIN_ELEMENTS = 3;

/** How deep a nested literal may go before we stop trying to prove it static. */
const MAX_LITERAL_DEPTH = 4;

const IGNORE_PATTERNS: readonly RegExp[] = [
  /[\\/]generated[\\/]/,
  /\.gen\.tsx?$/,
  /\.generated\.tsx?$/,
  /\.d\.ts$/,
];

const MUTATING_METHODS: ReadonlySet<string> = new Set([
  // Array
  "push", "pop", "shift", "unshift", "splice", "sort", "reverse", "fill", "copyWithin",
  // Set / Map
  "add", "set", "delete", "clear",
  // Object-ish escape hatches
  "assign",
]);

const COLLECTION_CONSTRUCTORS: ReadonlySet<string> = new Set(["Set", "Map"]);

/** `g` and `y` carry `lastIndex` between calls, so hoisting changes behaviour. */
const HAS_STATEFUL_FLAG_RE = /[gy]/;

/**
 * Built-ins that read their argument and return a fresh value without keeping
 * or mutating the original, so passing the binding to them is still a read.
 */
const NON_RETAINING_BUILTINS: ReadonlyMap<string, ReadonlySet<string>> = new Map([
  ["Object", new Set(["keys", "values", "entries", "freeze", "fromEntries", "assign"])],
  ["Array", new Set(["from", "isArray"])],
  ["JSON", new Set(["stringify"])],
]);

type Candidate =
  | { kind: "array" | "object" | "Set" | "Map"; size: number }
  | { kind: "regex"; size: number };

function isIgnoredFile(filename: string, sourceText: string): boolean {
  if (IGNORE_PATTERNS.some((re) => re.test(filename))) {
    return true;
  }
  return /@generated\b/.test(sourceText.slice(0, 1024));
}

function isLocalFixtureFile(filename: FilePath): boolean {
  return isTestFile(filename) || isStoryFile(filename);
}

/** Unwraps `x as const` / `x satisfies T` down to the inner expression. */
function unwrap(node: Node): Node {
  if (
    node.type === "TSAsExpression" ||
    node.type === "TSSatisfiesExpression" ||
    node.type === "TSNonNullExpression"
  ) {
    return unwrap(node.expression);
  }
  return node;
}

function literalRegex(node: Node): { flags: string } | undefined {
  return node.type === "Literal" && "regex" in node ? (node.regex ?? undefined) : undefined;
}

function isLiteralOnly(node: Node, depth: number): boolean {
  if (depth > MAX_LITERAL_DEPTH) {
    return false;
  }
  const inner = unwrap(node);
  switch (inner.type) {
    case "Literal": {
      // A stateful regex nested in a collection would carry `lastIndex` across calls once hoisted.
      return !HAS_STATEFUL_FLAG_RE.test(literalRegex(inner)?.flags ?? "");
    }
    case "TemplateLiteral": {
      return inner.expressions.length === 0;
    }
    case "UnaryExpression": {
      return (
        (inner.operator === "-" || inner.operator === "+") &&
        inner.argument.type === "Literal" &&
        typeof inner.argument.value === "number"
      );
    }
    case "ArrayExpression": {
      return inner.elements.every(
        (el) => el !== null && el.type !== "SpreadElement" && isLiteralOnly(el, depth + 1),
      );
    }
    case "ObjectExpression": {
      return inner.properties.every((prop) => {
        if (prop.type !== "Property") {
          return false;
        }
        if (prop.shorthand || prop.method || prop.kind !== "init") {
          return false;
        }
        if (prop.computed && prop.key.type !== "Literal") {
          return false;
        }
        return isLiteralOnly(prop.value, depth + 1);
      });
    }
    default: {
      return false;
    }
  }
}

/** Classifies the initializer, or returns null when it is not a hoistable literal-only collection / regex. */
function classify(init: Node, checkRegex: boolean, sourceCode: SourceCode): Candidate | null {
  const node = unwrapObjectFreeze(init, sourceCode);
  const regex = literalRegex(node);
  if (regex !== undefined) {
    if (!checkRegex) {
      return null;
    }
    if (HAS_STATEFUL_FLAG_RE.test(regex.flags)) {
      return null;
    }
    return { kind: "regex", size: 1 };
  }
  if (node.type === "ArrayExpression") {
    return isLiteralOnly(node, 0) ? { kind: "array", size: node.elements.length } : null;
  }
  if (node.type === "ObjectExpression") {
    return isLiteralOnly(node, 0) ? { kind: "object", size: node.properties.length } : null;
  }
  if (
    node.type === "NewExpression" &&
    node.callee.type === "Identifier" &&
    COLLECTION_CONSTRUCTORS.has(node.callee.name) &&
    isUnshadowedBuiltin(node.callee, sourceCode)
  ) {
    return classifyCollection(node, node.callee.name);
  }
  return null;
}

/** `Object.freeze(x)` → `x`; anything else is returned untouched. */
function unwrapObjectFreeze(node: Node, sourceCode: SourceCode): Node {
  const inner = unwrap(node);
  if (inner.type !== "CallExpression") return inner;
  const callee = unwrapExpression(inner.callee);
  const argument = inner.arguments[0];
  if (
    callee.type === "MemberExpression" &&
    !callee.computed &&
    callee.object.type === "Identifier" &&
    callee.object.name === "Object" &&
    isUnshadowedBuiltin(callee.object, sourceCode) &&
    callee.property.type === "Identifier" &&
    callee.property.name === "freeze" &&
    inner.arguments.length === 1 &&
    argument !== undefined &&
    argument.type !== "SpreadElement"
  ) {
    return unwrap(argument);
  }
  return inner;
}

function isSafeRead(identifier: ESTree.IdentifierReference, sourceCode: SourceCode): boolean {
  if (isTypeQueryName(identifier)) return true;
  const value = outerExpression(identifier);
  const parent = parentOf(value);
  switch (parent?.type) {
    case "MemberExpression":
      return isSafeMemberRead(value, parent);
    // `for (const x of X)` — iteration is a read.
    case "ForOfStatement":
      return parent.right === value;
    case "SpreadElement": // `[...X]`, `{...X}`, `f(...X)` — every spread copies.
    case "BinaryExpression": // `"a" in X`, `X instanceof Y`, `X === undefined`
      return true;
    case "CallExpression":
      return parent.arguments.includes(value as ESTree.Argument) && isNonRetainingBuiltinCall(parent, value, sourceCode);
    // `typeof X`, `!X`
    case "UnaryExpression":
      return parent.operator !== "delete";
    default:
      return false;
  }
}

/** `typeof X` or `typeof X.a` in a type position. */
function isTypeQueryName(identifier: ESTree.IdentifierReference): boolean {
  let typeOwner = parentOf(identifier);
  while (typeOwner?.type === "TSQualifiedName") typeOwner = parentOf(typeOwner);
  return typeOwner?.type === "TSTypeQuery";
}

function isNonRetainingBuiltinCall(node: ESTree.CallExpression, argument: Node, sourceCode: SourceCode): boolean {
  const callee = unwrapExpression(node.callee);
  if (callee.type === "Identifier" && callee.name === "structuredClone") {
    return isUnshadowedBuiltin(callee, sourceCode);
  }
  if (callee.type !== "MemberExpression" || callee.computed) return false;
  const calleeReceiver = unwrapExpression(callee.object);
  if (
    calleeReceiver.type !== "Identifier" ||
    callee.property.type !== "Identifier" ||
    !isUnshadowedBuiltin(calleeReceiver, sourceCode)
  ) {
    return false;
  }
  const members = NON_RETAINING_BUILTINS.get(calleeReceiver.name);
  if (members === undefined || !members.has(callee.property.name)) {
    return false;
  }
  // `Object.assign(X, src)` mutates its FIRST argument; only later positions (sources) are reads.
  if (calleeReceiver.name === "Object" && callee.property.name === "assign") {
    return node.arguments[0] !== argument;
  }
  return true;
}

function isUnshadowedBuiltin(identifier: Node & { name: string }, sourceCode: SourceCode): boolean {
  return (findVariable(sourceCode.getScope(identifier), identifier.name)?.defs.length ?? 0) === 0;
}

function classifyCollection(node: ESTree.NewExpression, constructorName: string): Candidate | null {
  const arg = node.arguments[0];
  if (node.arguments.length !== 1 || arg === undefined || arg.type === "SpreadElement") {
    return null;
  }
  const entries = unwrap(arg);
  if (entries.type !== "ArrayExpression") {
    return null;
  }
  return isLiteralOnly(entries, 0)
    ? { kind: constructorName === "Set" ? "Set" : "Map", size: entries.elements.length }
    : null;
}

function isSafeMemberRead(identifier: Node, start: ESTree.MemberExpression): boolean {
  if (start.object !== identifier) {
    // `foo[X]` — the binding is used as a key, which is a plain read.
    return true;
  }
  let parent: ESTree.MemberExpression = start;
  for (let next = parentOf(parent); next?.type === "MemberExpression" && next.object === parent; next = parentOf(parent)) {
    parent = next;
  }
  const usage = outerExpression(parent);
  const grandparent = parentOf(usage);
  switch (grandparent?.type) {
    case "VariableDeclarator":
    case "SpreadElement":
    case "UpdateExpression": // `X.a++`
      return false;
    // `X.a = 1`, `X[0] = 1`, `X.a += 1`
    case "AssignmentExpression":
      return grandparent.left !== usage;
    // `delete X.a`
    case "UnaryExpression":
      return grandparent.operator !== "delete";
    // `X.push(...)`, `X.sort()`, ...
    case "CallExpression": {
      const method = getPropertyName(parent);
      return grandparent.callee !== usage || (method !== null && !MUTATING_METHODS.has(method));
    }
    // Other member reads retain the existing heuristic; callbacks and returned children are not analyzed.
    default:
      return true;
  }
}

/** `(() => { … })()`, possibly through erased wrappers: the body runs once, so hoisting gains nothing. */
function isImmediatelyInvoked(fn: Node): boolean {
  let expression = fn;
  for (let parent = parentOf(expression); parent !== null && unwrap(parent) === expression; parent = parentOf(expression)) {
    expression = parent;
  }
  const call = parentOf(expression);
  return call?.type === "CallExpression" && call.callee === expression;
}

export default defineRule({
  meta: {
    defaultOptions: [{}],
    type: "suggestion",
    fixable: "code",
    docs: {
      description:
        "Hoist literal-only constant collections and regexes out of function bodies to module scope so they are allocated once.",
      url: docsUrl("prefer-module-level-constant"),
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          minElements: { description: "Minimum collection size before recommending a module-level constant.", type: "number", minimum: 1 },
          checkRegex: { description: "Include reusable regular expression literals in hoisting checks.", type: "boolean" },
          ignoreTestFiles: { description: "Skip test files when recommending module-level constants.", type: "boolean" },
        },
      },
    ],
    messages: {
      hoistCollection:
        "`{{name}}` is a literal-only {{kind}} rebuilt on every call. Hoist it to module scope in immutable form (`as const`, a readonly collection, or `Object.freeze`) so it is allocated once without exposing mutable shared state.",
      hoistRegex:
        "`{{name}}` is a constant regex recompiled on every call. Hoist it to module scope.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let minElements = DEFAULT_MIN_ELEMENTS;
    let checkRegex = true;

    function allReferencesAreSafeReads(declarator: ESTree.VariableDeclarator): boolean {
      const variable = sourceCode.getDeclaredVariables(declarator)[0];
      if (variable === undefined) {
        return false;
      }
      for (const reference of tsVariable(variable).references) {
        if (reference.isTypeReference && !reference.isValueReference) continue;
        // The initializer write itself is not a usage.
        if (reference.init === true) {
          continue;
        }
        if (reference.isWrite()) {
          return false;
        }
        // A `JSXIdentifier` reference means the constant is rendered as a JSX tag name.
        if (reference.identifier.type !== "Identifier") {
          return false;
        }
        if (!isSafeRead(reference.identifier as ESTree.IdentifierReference, sourceCode)) {
          return false;
        }
      }
      return true;
    }

    return {
      before() {
        sourceCode = context.sourceCode;
        const [options = {}] = context.options as unknown as readonly [Options?];
        minElements = options.minElements ?? DEFAULT_MIN_ELEMENTS;
        checkRegex = options.checkRegex ?? true;
        const ignoreTestFiles = options.ignoreTestFiles ?? true;
        if (isIgnoredFile(context.filename, sourceCode.getText())) return false;
        if (ignoreTestFiles && isLocalFixtureFile({ filename: context.filename, cwd: context.cwd })) return false;
        return undefined;
      },
      VariableDeclarator(node: ESTree.VariableDeclarator): void {
        const declaration = parentOf(node);
        if (declaration?.type !== "VariableDeclaration" || declaration.kind !== "const" || declaration.declare === true ||
          node.id.type !== "Identifier" || node.init === null) return;
        const owner = enclosingFunction(node);
        if (owner === null || isImmediatelyInvoked(owner)) return;
        const candidate = classify(node.init, checkRegex, sourceCode);
        if (candidate === null || (candidate.kind !== "regex" && candidate.size < minElements)) return;
        if (!allReferencesAreSafeReads(node)) return;
        const fix = literalLookupHoistFix(sourceCode, node);
        context.report({
          node: node.id,
          ...(fix !== null && { fix }),
          messageId: candidate.kind === "regex" ? "hoistRegex" : "hoistCollection",
          data: { name: node.id.name, kind: candidate.kind },
        });
      },
    };
  },
});
