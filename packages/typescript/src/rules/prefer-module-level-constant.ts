/**
 * @fileoverview prefer-module-level-constant — a literal-only collection or regex declared inside a function is rebuilt on every call.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-module-level-constant.test.ts
 */

import { type TSESTree, AST_NODE_TYPES } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isStoryFile, isTestFile } from "./_paths.js";

type MessageIds = "hoistCollection" | "hoistRegex";

export const PREFER_MODULE_LEVEL_CONSTANT_DOCUMENTATION = {
  summary: "Hoist literal-only constant collections and regexes out of function bodies to module scope so they are allocated once.",
  rationale: "Recreating immutable lookup data on every call wastes allocations and obscures its constant nature.",
  remediation: "Declare immutable literal collections and non-stateful regular expressions once at module scope.",
  category: "performance",
  limitations: ["Collections that are small, mutated, escape the function, or depend on local values are not reported."],
  examples: [
    { id: "hoisted-collection", title: "Hoist a constant collection", outcome: "no-match", files: [{ path: "src/keys.ts", source: "const KEYS = ['a', 'b', 'c'] as const; function isAllowed(key: string) { return KEYS.includes(key); }" }], focusPath: "src/keys.ts", expectedCount: 0, public: true },
    { id: "local-collection", title: "Do not recreate a constant collection", outcome: "match", files: [{ path: "src/keys.ts", source: "function isAllowed(key: string) { const KEYS = ['a', 'b', 'c']; return KEYS.includes(key); }" }], focusPath: "src/keys.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

type Options = readonly [
  {
    minElements?: number;
    checkRegex?: boolean;
    ignoreTestFiles?: boolean;
  }?,
];

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
  "push",
  "pop",
  "shift",
  "unshift",
  "splice",
  "sort",
  "reverse",
  "fill",
  "copyWithin",
  // Set / Map
  "add",
  "set",
  "delete",
  "clear",
  // Object-ish escape hatches
  "assign",
]);

const FUNCTION_TYPES: ReadonlySet<AST_NODE_TYPES> = new Set([
  AST_NODE_TYPES.FunctionDeclaration,
  AST_NODE_TYPES.FunctionExpression,
  AST_NODE_TYPES.ArrowFunctionExpression,
]);

const COLLECTION_CONSTRUCTORS: ReadonlySet<string> = new Set(["Set", "Map"]);

function isIgnoredFile(filename: string, sourceText: string): boolean {
  if (IGNORE_PATTERNS.some((re) => re.test(filename))) {
    return true;
  }
  return /@generated\b/.test(sourceText.slice(0, 1024));
}

function isLocalFixtureFile(filename: string): boolean {
  return isTestFile(filename) || isStoryFile(filename);
}

/** Unwraps `x as const` / `x satisfies T` down to the inner expression. */
function unwrap(node: TSESTree.Node): TSESTree.Node {
  if (
    node.type === AST_NODE_TYPES.TSAsExpression ||
    node.type === AST_NODE_TYPES.TSSatisfiesExpression ||
    node.type === AST_NODE_TYPES.TSNonNullExpression
  ) {
    return unwrap(node.expression);
  }
  return node;
}

/** `g` and `y` carry `lastIndex` between calls, so hoisting changes behaviour. */
const HAS_STATEFUL_FLAG_RE = /[gy]/;

function isRegexLiteral(node: TSESTree.Node): node is TSESTree.RegExpLiteral {
  return (
    node.type === AST_NODE_TYPES.Literal &&
    "regex" in node &&
    node.regex !== undefined
  );
}

function isLiteralOnly(node: TSESTree.Node, depth: number): boolean {
  if (depth > MAX_LITERAL_DEPTH) {
    return false;
  }
  const inner = unwrap(node);
  switch (inner.type) {
    case AST_NODE_TYPES.Literal: {
      // A `RegExpLiteral` is an `AST_NODE_TYPES.Literal`, so without this a
      // stateful regex nested in a collection — `const patterns = [/a/g, /b/]`
      // — bypassed the top-level `g`/`y` check and the recommended hoist would
      // have carried `lastIndex` across calls.
      return !(isRegexLiteral(inner) && HAS_STATEFUL_FLAG_RE.test(inner.regex.flags));
    }
    case AST_NODE_TYPES.TemplateLiteral: {
      return inner.expressions.length === 0;
    }
    case AST_NODE_TYPES.UnaryExpression: {
      return (
        (inner.operator === "-" || inner.operator === "+") &&
        inner.argument.type === AST_NODE_TYPES.Literal &&
        typeof inner.argument.value === "number"
      );
    }
    case AST_NODE_TYPES.ArrayExpression: {
      return inner.elements.every(
        (el) =>
          el !== null &&
          el.type !== AST_NODE_TYPES.SpreadElement &&
          isLiteralOnly(el, depth + 1),
      );
    }
    case AST_NODE_TYPES.ObjectExpression: {
      return inner.properties.every((prop) => {
        if (prop.type !== AST_NODE_TYPES.Property) {
          return false;
        }
        if (prop.shorthand || prop.method || prop.kind !== "init") {
          return false;
        }
        if (prop.computed && prop.key.type !== AST_NODE_TYPES.Literal) {
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

/**
 * Classifies the initializer, or returns null when it is not a hoistable
 * literal-only collection / regex.
 */
function classify(init: TSESTree.Node, checkRegex: boolean): Candidate | null {
  const node = unwrapObjectFreeze(init);

  if (isRegexLiteral(node)) {
    if (!checkRegex) {
      return null;
    }
    if (HAS_STATEFUL_FLAG_RE.test(node.regex.flags)) {
      return null;
    }
    return { kind: "regex", size: 1 };
  }

  if (node.type === AST_NODE_TYPES.ArrayExpression) {
    return isLiteralOnly(node, 0)
      ? { kind: "array", size: node.elements.length }
      : null;
  }

  if (node.type === AST_NODE_TYPES.ObjectExpression) {
    return isLiteralOnly(node, 0)
      ? { kind: "object", size: node.properties.length }
      : null;
  }

  if (
    node.type === AST_NODE_TYPES.NewExpression &&
    node.callee.type === AST_NODE_TYPES.Identifier &&
    COLLECTION_CONSTRUCTORS.has(node.callee.name)
  ) {
    const arg = node.arguments[0];
    if (
      node.arguments.length !== 1 ||
      arg === undefined ||
      arg.type === AST_NODE_TYPES.SpreadElement
    ) {
      return null;
    }
    const entries = unwrap(arg);
    if (entries.type !== AST_NODE_TYPES.ArrayExpression) {
      return null;
    }
    return isLiteralOnly(entries, 0)
      ? { kind: node.callee.name === "Set" ? "Set" : "Map", size: entries.elements.length }
      : null;
  }

  return null;
}

type Candidate =
  | { kind: "array" | "object" | "Set" | "Map"; size: number }
  | { kind: "regex"; size: number };

/** `Object.freeze(x)` → `x`; anything else is returned untouched. */
function unwrapObjectFreeze(node: TSESTree.Node): TSESTree.Node {
  const inner = unwrap(node);
  if (
    inner.type === AST_NODE_TYPES.CallExpression &&
    inner.callee.type === AST_NODE_TYPES.MemberExpression &&
    !inner.callee.computed &&
    inner.callee.object.type === AST_NODE_TYPES.Identifier &&
    inner.callee.object.name === "Object" &&
    inner.callee.property.type === AST_NODE_TYPES.Identifier &&
    inner.callee.property.name === "freeze" &&
    inner.arguments.length === 1 &&
    inner.arguments[0] !== undefined &&
    inner.arguments[0].type !== AST_NODE_TYPES.SpreadElement
  ) {
    return unwrap(inner.arguments[0]);
  }
  return inner;
}

/** The nearest enclosing function, or null when the node is at module scope. */
function enclosingFunction(node: TSESTree.Node): TSESTree.Node | null {
  let current: TSESTree.Node | undefined | null = node.parent;
  while (current !== undefined && current !== null) {
    if (FUNCTION_TYPES.has(current.type)) {
      return current;
    }
    current = current.parent;
  }
  return null;
}

/**
 * Built-ins that read their argument and return a fresh value without keeping
 * or mutating the original, so passing the binding to them is still a read.
 */
const NON_RETAINING_BUILTINS: ReadonlyMap<string, ReadonlySet<string>> = new Map(
  [
    [
      "Object",
      new Set(["keys", "values", "entries", "freeze", "fromEntries", "assign"]),
    ],
    ["Array", new Set(["from", "isArray"])],
    ["JSON", new Set(["stringify"])],
  ],
);

function isSafeRead(identifier: TSESTree.Identifier): boolean {
  const parent = identifier.parent;

  if (parent.type === AST_NODE_TYPES.MemberExpression) {
    if (parent.object !== identifier) {
      // `foo[X]` — the binding is used as a key, which is a plain read.
      return true;
    }
    const grandparent = parent.parent;
    // `X.a = 1`, `X[0] = 1`, `X.a += 1`
    if (
      grandparent.type === AST_NODE_TYPES.AssignmentExpression &&
      grandparent.left === parent
    ) {
      return false;
    }
    // `X.a++`
    if (grandparent.type === AST_NODE_TYPES.UpdateExpression) {
      return false;
    }
    // `delete X.a`
    if (
      grandparent.type === AST_NODE_TYPES.UnaryExpression &&
      grandparent.operator === "delete"
    ) {
      return false;
    }
    // `X.push(...)`, `X.sort()`, ...
    if (
      !parent.computed &&
      parent.property.type === AST_NODE_TYPES.Identifier &&
      MUTATING_METHODS.has(parent.property.name) &&
      grandparent.type === AST_NODE_TYPES.CallExpression &&
      grandparent.callee === parent
    ) {
      return false;
    }
    // Everything else through a member expression — `X.length`, `X.includes(v)`,
    // `X[i]`, `X.get(k)`, even `arr.map(X.has)` — reads a property of the
    // binding without handing the binding itself out, so it cannot mutate it.
    return true;
  }

  // `for (const x of X)` — iteration is a read.
  if (
    parent.type === AST_NODE_TYPES.ForOfStatement &&
    parent.right === identifier
  ) {
    return true;
  }

  // `[...X]`, `{...X}`, `f(...X)` — every spread copies, so the original is
  // never handed out and hoisting stays safe.
  if (parent.type === AST_NODE_TYPES.SpreadElement) {
    return true;
  }

  // `"a" in X`, `X instanceof Y`, `X === undefined`
  if (parent.type === AST_NODE_TYPES.BinaryExpression) {
    return true;
  }

  if (
    parent.type === AST_NODE_TYPES.CallExpression &&
    parent.arguments.includes(identifier) &&
    isNonRetainingBuiltinCall(parent, identifier)
  ) {
    return true;
  }

  // `typeof X`, `!X`
  if (
    parent.type === AST_NODE_TYPES.UnaryExpression &&
    parent.operator !== "delete"
  ) {
    return true;
  }

  return false;
}

function isNonRetainingBuiltinCall(
  node: TSESTree.CallExpression,
  argument: TSESTree.Identifier,
): boolean {
  const callee = node.callee;
  if (
    callee.type === AST_NODE_TYPES.Identifier &&
    callee.name === "structuredClone"
  ) {
    return true;
  }
  if (
    callee.type !== AST_NODE_TYPES.MemberExpression ||
    callee.computed ||
    callee.object.type !== AST_NODE_TYPES.Identifier ||
    callee.property.type !== AST_NODE_TYPES.Identifier
  ) {
    return false;
  }
  const members = NON_RETAINING_BUILTINS.get(callee.object.name);
  if (members === undefined || !members.has(callee.property.name)) {
    return false;
  }
  // `Object.assign(X, src)` mutates its FIRST argument; only later positions
  // (sources) are reads.
  if (callee.object.name === "Object" && callee.property.name === "assign") {
    return node.arguments[0] !== argument;
  }
  return true;
}

export default createRule<Options, MessageIds>({
  name: "prefer-module-level-constant",
  documentation: PREFER_MODULE_LEVEL_CONSTANT_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Hoist literal-only constant collections and regexes out of function bodies to module scope so they are allocated once.",
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          minElements: { type: "number", minimum: 1 },
          checkRegex: { type: "boolean" },
          ignoreTestFiles: { type: "boolean" },
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
  defaultOptions: [{}],
  create(context, [optionsArg]) {
    const options = optionsArg ?? {};
    const minElements = options.minElements ?? DEFAULT_MIN_ELEMENTS;
    const checkRegex = options.checkRegex ?? true;
    const ignoreTestFiles = options.ignoreTestFiles ?? true;

    const sourceCode = context.sourceCode;
    const filename = context.filename;

    if (isIgnoredFile(filename, sourceCode.getText())) {
      return {};
    }
    if (ignoreTestFiles && isLocalFixtureFile(filename)) {
      return {};
    }

    function allReferencesAreSafeReads(
      declarator: TSESTree.VariableDeclarator,
    ): boolean {
      const variables = sourceCode.getDeclaredVariables(declarator);
      const variable = variables[0];
      if (variable === undefined) {
        return false;
      }
      for (const reference of variable.references) {
        // The initializer write itself is not a usage.
        if (reference.init === true) {
          continue;
        }
        if (reference.isWrite()) {
          return false;
        }
        // A `JSXIdentifier` reference means the constant is rendered as a JSX
        // tag name — not something this rule reasons about, so bail.
        if (reference.identifier.type !== AST_NODE_TYPES.Identifier) {
          return false;
        }
        if (!isSafeRead(reference.identifier)) {
          return false;
        }
      }
      return true;
    }

    return {
      VariableDeclarator(node: TSESTree.VariableDeclarator): void {
        const declaration = node.parent;
        if (
          declaration.type !== AST_NODE_TYPES.VariableDeclaration ||
          declaration.kind !== "const" ||
          declaration.declare === true
        ) {
          return;
        }
        if (node.id.type !== AST_NODE_TYPES.Identifier || node.init === null) {
          return;
        }
        if (enclosingFunction(node) === null) {
          return;
        }

        const candidate = classify(node.init, checkRegex);
        if (candidate === null) {
          return;
        }
        if (candidate.kind !== "regex" && candidate.size < minElements) {
          return;
        }
        if (!allReferencesAreSafeReads(node)) {
          return;
        }

        context.report({
          node: node.id,
          messageId:
            candidate.kind === "regex" ? "hoistRegex" : "hoistCollection",
          data: { name: node.id.name, kind: candidate.kind },
        });
      },
    };
  },
});
