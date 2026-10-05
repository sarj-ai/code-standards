/**
 * @fileoverview no-fat-try-blocks — review broad recovery scopes using a bounded operation-count heuristic.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-fat-try-blocks.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree } from "@oxlint/plugins";


import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "fatTryBlock";
export interface RuleOptions {
  readonly max?: number;
}
type Options = readonly [RuleOptions?];

export const NO_FAT_TRY_BLOCKS_DOCUMENTATION = {
  summary: "Review try blocks exceeding the configured count of syntactically selected operations.",
  rationale:
    "A broad `try` block obscures which operation failed and encourages one catch clause to recover from unrelated errors.",
  remediation:
    "Keep only the operations that share one recovery policy inside the `try` block and move other work outside it.",
  category: "correctness",
  limitations: [
    "The default threshold is three selected top-level operations, not a proof of every possible throw. A shared recovery policy may legitimately cover several operations; generated files, catchless finally blocks, rethrows, and terminal error boundaries are excluded.",
  ],
  examples: [
    {
      id: "focused-try-block",
      title: "Three selected operations stay within the default threshold",
      outcome: "no-match",
      files: [{
        path: "src/load.ts",
        source: "function f() { try { const a = one(); const b = two(); const c = three(); } catch (error) { handle(error); } finish(); }",
      }],
      focusPath: "src/load.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "broad-try-block",
      title: "Review whether four selected operations share one recovery policy",
      outcome: "match",
      files: [{
        path: "src/load.ts",
        source: "function f() { try { const a = one(); const b = two(); const c = three(); const d = four(); } catch (error) { handle(error); } finish(); }",
      }],
      focusPath: "src/load.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

const MAX_TRY_BODY_STATEMENTS = 3;

const NESTED_FUNCTION_TYPES: ReadonlySet<ESTree.Node["type"]> = new Set([
  "FunctionDeclaration",
  "FunctionExpression",
  "ArrowFunctionExpression",
]);

/** Pure method names must not overlap common I/O-client methods such as `get`, `set`, or `find`. */
const PURE_METHODS: ReadonlySet<string> = new Set([
  "map", "filter", "forEach", "reduce", "reduceRight", "findIndex",
  "findLast", "findLastIndex", "some", "every", "push", "pop", "shift",
  "unshift", "slice", "splice", "concat", "flat", "flatMap", "join", "reverse",
  "sort", "fill", "includes", "indexOf", "lastIndexOf", "at", "toString",
  "toLocaleString", "valueOf", "charAt", "charCodeAt", "codePointAt", "split",
  "padStart", "padEnd", "repeat", "trim", "trimStart", "trimEnd", "toUpperCase",
  "toLowerCase", "toFixed", "toPrecision", "startsWith", "endsWith",
]);

/** Pure collection methods that synchronously execute function arguments. */
const SYNC_CALLBACK_METHODS: ReadonlySet<string> = new Set([
  "every", "filter", "findIndex", "findLast", "findLastIndex", "flatMap",
  "forEach", "map", "reduce", "reduceRight", "some", "sort",
]);

/** Non-throwing global namespaces called as `X.method(...)`. */
const PURE_NAMESPACES: ReadonlySet<string> = new Set([
  "Object", "Array", "Math", "JSON", "Number", "String", "Boolean", "console",
]);

/** Namespace exceptions that commonly throw; `JSON.stringify` remains a deliberate recall tradeoff. */
const IMPURE_NAMESPACE_METHODS: ReadonlySet<string> = new Set(["JSON.parse"]);

/** Constructors that do not throw on construction. */
const PURE_CONSTRUCTORS: ReadonlySet<string> = new Set([
  "Map", "Set", "WeakMap", "WeakSet", "Date", "Error", "TypeError",
  "RangeError", "Array", "Object", "Headers", "URLSearchParams", "FormData",
  "TextEncoder", "TextDecoder", "Blob", "ReadableStream", "WritableStream",
  "TransformStream", "Response", "AbortController",
]);

/** A call whose value is a known pure, non-throwing helper. */
function isPureCall(node: ESTree.CallExpression): boolean {
  const callee = node.callee;
  if (callee.type !== "MemberExpression") {
    return false;
  }
  const property = callee.property;
  if (property.type !== "Identifier") {
    return false;
  }
  if (
    callee.object.type === "Identifier" &&
    PURE_NAMESPACES.has(callee.object.name)
  ) {
    return !IMPURE_NAMESPACE_METHODS.has(`${callee.object.name}.${property.name}`);
  }
  return (
    PURE_METHODS.has(property.name) &&
    (!SYNC_CALLBACK_METHODS.has(property.name) || !synchronousCallbackCanThrow(node))
  );
}

function synchronousCallbackCanThrow(node: ESTree.CallExpression): boolean {
  return node.arguments.some((argument) => {
    if (
      argument.type !== "ArrowFunctionExpression" &&
      argument.type !== "FunctionExpression"
    ) return false;
    if (argument.async || argument.body === null) return false;
    return subtreeMatches(
      argument.body,
      (current) =>
        current.type === "ThrowStatement" ||
        (current.type === "CallExpression" &&
          current.callee.type === "MemberExpression" &&
          !current.callee.computed &&
          current.callee.object.type === "Identifier" &&
          current.callee.object.name === "JSON" &&
          current.callee.property.type === "Identifier" &&
          current.callee.property.name === "parse"),
    );
  });
}

function isPureNew(node: ESTree.NewExpression): boolean {
  return (
    node.callee.type === "Identifier" &&
    PURE_CONSTRUCTORS.has(node.callee.name)
  );
}

function subtreeMatches(
  stmt: ESTree.Node,
  predicate: (node: ESTree.Node) => boolean,
  descendIntoFunctions = false,
): boolean {
  let found = false;

  const visit = (current: ESTree.Node): void => {
    if (found) {
      return;
    }
    if (predicate(current)) {
      found = true;
      return;
    }
    forEachOwnAstChild(current, visit, key =>
      descendIntoFunctions || !NESTED_FUNCTION_TYPES.has(current.type) || key !== "body");
  };

  visit(stmt);
  return found;
}

/** Unwrap `await` / optional-chain / non-null wrappers to the core expression. */
function unwrap(expr: ESTree.Expression): ESTree.Expression {
  let current = expr;
  while (
    current.type === "ChainExpression" ||
    current.type === "TSNonNullExpression"
  ) {
    current = current.expression;
  }
  return current;
}

/** `await` and used calls count; bare calls do not, including inside blocks and branches. */
function canThrow(stmt: ESTree.Statement): boolean {
  if (hasAwait(stmt)) {
    return true;
  }
  if (isBareCallStatement(stmt)) {
    return false;
  }
  if (stmt.type === "BlockStatement") {
    return stmt.body.some(canThrow);
  }
  if (stmt.type === "IfStatement") {
    return (
      hasThrowingCallOrNew(stmt.test) ||
      canThrow(stmt.consequent) ||
      (stmt.alternate !== null && canThrow(stmt.alternate))
    );
  }
  return hasThrowingCallOrNew(stmt);
}

const hasAwait = (node: ESTree.Node): boolean =>
  subtreeMatches(node, (n) => n.type === "AwaitExpression");

const hasThrowingCallOrNew = (node: ESTree.Node): boolean =>
  subtreeMatches(
    node,
    (n) =>
      (n.type === "CallExpression" && !isPureCall(n)) ||
      (n.type === "NewExpression" && !isPureNew(n)),
  );

/** A bare fire-and-forget call statement — `toast("done");`, `logEvent(...);`. */
function isBareCallStatement(stmt: ESTree.Statement): boolean {
  return (
    stmt.type === "ExpressionStatement" &&
    unwrap(stmt.expression).type === "CallExpression"
  );
}

/** UI-style failure/final-state signaling applies one uniform policy to the whole operation. */
function isSimpleCatchFinallyOrchestration(node: ESTree.TryStatement): boolean {
  const handler = node.handler;
  const finalizer = node.finalizer;
  return (
    handler !== null &&
    handler.param === null &&
    isSingleSimpleCall(handler.body.body) &&
    finalizer !== null &&
    isSingleSimpleCall(finalizer.body)
  );
}

function isSingleSimpleCall(body: readonly ESTree.Statement[]): boolean {
  const statement = body[0];
  return body.length === 1 && statement !== undefined && isSimpleBareCallStatement(statement);
}

/** A single call with no hidden control flow or mutation inside its arguments. */
function isSimpleBareCallStatement(stmt: ESTree.Statement): boolean {
  if (!isBareCallStatement(stmt)) {
    return false;
  }
  return !subtreeMatches(
    stmt,
    (node) =>
      node.type === "ArrowFunctionExpression" ||
      node.type === "FunctionExpression" ||
      node.type === "AssignmentExpression" ||
      node.type === "UpdateExpression" ||
      node.type === "AwaitExpression",
    true,
  );
}

function handlerRethrows(handler: ESTree.CatchClause | null): boolean {
  if (handler === null) {
    return false;
  }
  const body = handler.body.body;
  const last = body[body.length - 1];
  return last !== undefined && last.type === "ThrowStatement";
}

/** Statements that hand control straight through to their own parent. */
const PASS_THROUGH_PARENTS: ReadonlySet<ESTree.Node["type"]> = new Set([
  "IfStatement",
  "TryStatement",
  "CatchClause",
  "LabeledStatement",
]);

/** A member property / object key spelled `x` is not a reference to `x`. */
function isPropertyName(node: ESTree.BindingIdentifier): boolean {
  const parent = node.parent;
  if (parent.type === "MemberExpression") {
    return parent.property === node && !parent.computed;
  }
  if (parent.type === "Property") {
    return parent.key === node && !parent.computed;
  }
  return false;
}

/** `null`, `undefined`, `false`, `void 0`, `[]`, `{}` — a success-shaped value. */
function isSuccessShapedValue(expr: ESTree.Expression): boolean {
  let current: ESTree.Expression = expr;
  while (
    current.type === "TSAsExpression" ||
    current.type === "TSNonNullExpression"
  ) {
    current = current.expression;
  }
  if (current.type === "Literal") {
    return current.value === null || current.value === false;
  }
  if (current.type === "Identifier") {
    return current.name === "undefined";
  }
  if (current.type === "UnaryExpression") {
    return current.operator === "void";
  }
  if (current.type === "ArrayExpression") {
    return current.elements.length === 0;
  }
  if (current.type === "ObjectExpression") {
    return current.properties.length === 0;
  }
  return false;
}

/** Exempt terminal boundaries that propagate the caught error without fabricating success. */
function isTerminalErrorBoundary(node: ESTree.TryStatement): boolean {
  const handler = node.handler;
  return (
    handler !== null &&
    isTerminalInFunction(node) &&
    handlerEndsByHandingOff(handler) &&
    handlerMentionsCaughtBinding(handler) &&
    !handlerReturnsSuccessShaped(handler)
  );
}

/** A terminal node is last through every enclosing block up to its function, without a loop or switch. */
function isTerminalInFunction(node: ESTree.Node): boolean {
  let current: ESTree.Node = node;
  let parent: ESTree.Node | null | undefined = current.parent;

  while (parent != null) {
    if (parent.type === "BlockStatement") {
      if (parent.body[parent.body.length - 1] !== current) {
        return false;
      }
    } else if (parent.type === "Program") {
      return parent.body[parent.body.length - 1] === current;
    } else if (NESTED_FUNCTION_TYPES.has(parent.type)) {
      return true;
    } else if (!PASS_THROUGH_PARENTS.has(parent.type)) {
      return false;
    }
    current = parent;
    parent = current.parent;
  }
  return false;
}

/** A propagating handler ends with `return`, `throw`, or a bare call. */
function handlerEndsByHandingOff(handler: ESTree.CatchClause): boolean {
  const body = handler.body.body;
  const last = body[body.length - 1];
  if (last === undefined) {
    return false;
  }
  if (
    last.type === "ReturnStatement" ||
    last.type === "ThrowStatement"
  ) {
    return true;
  }
  return (
    last.type === "ExpressionStatement" &&
    unwrapAwait(last.expression).type === "CallExpression"
  );
}

/** `await f()` unwrapped to `f()`; everything else unwrapped as usual. */
function unwrapAwait(expr: ESTree.Expression): ESTree.Expression {
  const inner = unwrap(expr);
  return inner.type === "AwaitExpression"
    ? unwrap(inner.argument)
    : inner;
}

/** A boundary must reference its caught error, including through nested callbacks. */
function handlerMentionsCaughtBinding(handler: ESTree.CatchClause): boolean {
  const names = caughtBindingNames(handler);
  if (names.size === 0) {
    return false;
  }
  return subtreeMatches(
    handler.body,
    (n) =>
      n.type === "Identifier" &&
      names.has(n.name) &&
      !isPropertyName(n),
    true,
  );
}

function caughtBindingNames(handler: ESTree.CatchClause): ReadonlySet<string> {
  const names = new Set<string>();
  if (handler.param !== null) {
    collectBindingNames(handler.param, names);
  }
  return names;
}

/** Collect identifiers bound by a catch pattern, excluding type annotations. */
function collectBindingNames(
  pattern: ESTree.Node,
  names: Set<string>,
): void {
  if (pattern.type === "Identifier") {
    names.add(pattern.name);
    return;
  }
  if (pattern.type === "ObjectPattern") {
    for (const property of pattern.properties) {
      collectBindingNames(
        property.type === "RestElement"
          ? property.argument
          : property.value,
        names,
      );
    }
    return;
  }
  if (pattern.type === "ArrayPattern") {
    for (const element of pattern.elements) {
      if (element !== null) {
        collectBindingNames(element, names);
      }
    }
    return;
  }
  if (
    pattern.type === "AssignmentPattern" ||
    pattern.type === "RestElement"
  ) {
    collectBindingNames(
      pattern.type === "AssignmentPattern"
        ? pattern.left
        : pattern.argument,
      names,
    );
  }
}

/** Empty or false results hide which operation failed and are not error propagation. */
const handlerReturnsSuccessShaped = (handler: ESTree.CatchClause): boolean =>
  subtreeMatches(
    handler.body,
    (n) =>
      n.type === "ReturnStatement" &&
      n.argument !== null &&
      isSuccessShapedValue(n.argument),
  );

export default createRule<Options, MessageIds>({
  name: "no-fat-try-blocks",
  documentation: NO_FAT_TRY_BLOCKS_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description: "Review try blocks exceeding the configured count of syntactically selected operations.",
    },
    schema: [
      {
        type: "object",
        properties: {
          max: { type: "integer", minimum: 1 },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      fatTryBlock:
        "This `try` block has {{count}} syntactically selected operations (max {{max}}). Review whether they share one recovery policy; move unrelated work outside the boundary.",
    },
  },
  defaultOptions: [{ max: MAX_TRY_BODY_STATEMENTS }],
  create(context, [options]) {
    if (isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)) {
      return {};
    }

    const sourceCode = context.sourceCode;

    return {
      TryStatement(node: ESTree.TryStatement): void {
        // A catchless try/finally is normally resource cleanup. A catch plus a
        // finally is still an error boundary and must not evade this rule.
        if (node.finalizer !== null && node.handler === null) {
          return;
        }
        if (handlerRethrows(node.handler)) {
          return;
        }
        if (isSimpleCatchFinallyOrchestration(node)) {
          return;
        }
        if (isTerminalErrorBoundary(node)) {
          return;
        }

        const count = node.block.body.filter(canThrow).length;
        const max = options?.max ?? MAX_TRY_BODY_STATEMENTS;
        if (count <= max) {
          return;
        }

        const tryKeyword = sourceCode.getFirstToken(node);
        context.report({
          node: tryKeyword ?? node,
          messageId: "fatTryBlock",
          data: { count, max },
        });
      },
    };
  },
});
