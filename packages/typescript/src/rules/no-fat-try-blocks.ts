/**
 * @fileoverview Disallow `try` blocks whose body contains more than three
 * top-level statements that can throw (TS port of Python's SARJ007).
 *
 * A fat `try` body obscures which statement is actually expected to throw and
 * widens the blast radius of the `catch` handler: unrelated failures get caught
 * (and often swallowed or mis-reported) by a handler written for a different
 * operation. Keep the `try` skinny — isolate the throwing statement(s) and move
 * the non-throwing setup and follow-up work outside.
 *
 * Only top-level statements that can *throw* are counted. What counts, and the
 * guards that keep the count aligned with intent (tuned against ~5.6k real TS
 * files to drive false positives to ~zero):
 *
 *   - An `await` always counts — awaiting a promise is the canonical throwing
 *     operation in async TS. A statement with an `await` in its same-scope
 *     subtree counts.
 *   - A synchronous call / `new` whose value is *used* (assigned, returned,
 *     branched on, or passed as an argument) counts — e.g. `const x = parse(s)`,
 *     `return build(x)`, `if (!validate(x))`.
 *   - A bare fire-and-forget call statement with no `await` does NOT count. In
 *     idiomatic TS these are side effects — React state setters (`setOpen(false)`),
 *     toasts (`toast.error(...)`), `router.refresh()`, logging, optional
 *     callbacks (`onSuccess?.()`). They are the post-success UI work that
 *     naturally trails the one awaited action; counting them flagged nearly
 *     every event handler. The exemption is applied STRUCTURALLY, recursing
 *     through blocks and `if`/`else` branches, so wrapping the same call in a
 *     guard (`if (!res.ok) { logEvent("http_error", { path }); return null; }`)
 *     does not resurrect it. A guard's TEST is still examined — a call whose
 *     result is branched on (`if (!validate(x))`) still counts.
 *   - Pure, non-throwing array / string / `Map` / `Object` / `Math` / `JSON`
 *     helpers (`.map`, `.filter`, `.push`, `.get`, `.join`, `Object.keys`, ...)
 *     do NOT count — they are data plumbing, not the operation being guarded.
 *   - Calls inside a nested function / arrow body do not run when the `try`
 *     executes, so they are not counted (same-scope walk).
 *
 * Two structural exemptions match the Python rule:
 *
 *   - A `finally` clause is a deliberate cleanup contract that couples the body
 *     to the handler — exempt.
 *   - A `catch` handler guaranteed to re-throw (its body's last statement is a
 *     `throw`) makes the wide body uniform error-context wrapping, not an
 *     over-broad swallow — exempt.
 */

import {
  ESLintUtils,
  type TSESTree,
  AST_NODE_TYPES,
} from "@typescript-eslint/utils";

import { isGeneratedFile } from "./_paths.js";

type MessageIds = "fatTryBlock";
type Options = readonly [];

const MAX_TRY_BODY_STATEMENTS = 3;

const NESTED_FUNCTION_TYPES = new Set<AST_NODE_TYPES>([
  AST_NODE_TYPES.FunctionDeclaration,
  AST_NODE_TYPES.FunctionExpression,
  AST_NODE_TYPES.ArrowFunctionExpression,
]);

/** Non-throwing member methods — array / string / Map / Set data plumbing. */
const PURE_METHODS = new Set<string>([
  "map", "filter", "forEach", "reduce", "reduceRight", "find", "findIndex",
  "findLast", "findLastIndex", "some", "every", "push", "pop", "shift",
  "unshift", "slice", "splice", "concat", "flat", "flatMap", "join", "reverse",
  "sort", "fill", "includes", "indexOf", "lastIndexOf", "at", "keys", "values",
  "entries", "has", "get", "set", "add", "delete", "clear", "toString",
  "toLocaleString", "valueOf", "charAt", "charCodeAt", "codePointAt", "split",
  "padStart", "padEnd", "repeat", "trim", "trimStart", "trimEnd", "toUpperCase",
  "toLowerCase", "toFixed", "toPrecision", "startsWith", "endsWith",
]);

/** Non-throwing global namespaces called as `X.method(...)`. */
const PURE_NAMESPACES = new Set<string>([
  "Object", "Array", "Math", "JSON", "Number", "String", "Boolean", "console",
]);

/** Constructors that do not throw on construction. */
const PURE_CONSTRUCTORS = new Set<string>([
  "Map", "Set", "WeakMap", "WeakSet", "Date", "Error", "TypeError",
  "RangeError", "Array", "Object", "Headers", "URLSearchParams", "FormData",
  "TextEncoder", "TextDecoder", "Blob", "ReadableStream", "WritableStream",
  "TransformStream", "Response", "AbortController",
]);

function isNode(value: unknown): value is TSESTree.Node {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { type?: unknown }).type === "string"
  );
}

/** A call whose value is a known pure, non-throwing helper. */
function isPureCall(node: TSESTree.CallExpression): boolean {
  const callee = node.callee;
  if (callee.type !== AST_NODE_TYPES.MemberExpression) {
    return false;
  }
  const property = callee.property;
  if (property.type !== AST_NODE_TYPES.Identifier) {
    return false;
  }
  if (
    callee.object.type === AST_NODE_TYPES.Identifier &&
    PURE_NAMESPACES.has(callee.object.name)
  ) {
    return true;
  }
  return PURE_METHODS.has(property.name);
}

function isPureNew(node: TSESTree.NewExpression): boolean {
  return (
    node.callee.type === AST_NODE_TYPES.Identifier &&
    PURE_CONSTRUCTORS.has(node.callee.name)
  );
}

/**
 * Walk `stmt`'s same-scope subtree (not descending into nested function/arrow
 * bodies) until `predicate` matches a node.
 */
function subtreeMatches(
  stmt: TSESTree.Node,
  predicate: (node: TSESTree.Node) => boolean,
): boolean {
  let found = false;

  const visit = (current: TSESTree.Node): void => {
    if (found) {
      return;
    }
    if (predicate(current)) {
      found = true;
      return;
    }
    for (const key of Object.keys(current)) {
      if (key === "parent") {
        continue;
      }
      if (NESTED_FUNCTION_TYPES.has(current.type) && key === "body") {
        continue;
      }
      const value = (current as unknown as Record<string, unknown>)[key];
      if (Array.isArray(value)) {
        for (const child of value) {
          if (isNode(child)) {
            visit(child);
          }
        }
      } else if (isNode(value)) {
        visit(value);
      }
      if (found) {
        return;
      }
    }
  };

  visit(stmt);
  return found;
}

const hasAwait = (node: TSESTree.Node): boolean =>
  subtreeMatches(node, (n) => n.type === AST_NODE_TYPES.AwaitExpression);

const hasThrowingCallOrNew = (node: TSESTree.Node): boolean =>
  subtreeMatches(
    node,
    (n) =>
      (n.type === AST_NODE_TYPES.CallExpression && !isPureCall(n)) ||
      (n.type === AST_NODE_TYPES.NewExpression && !isPureNew(n)),
  );

/** Unwrap `await` / optional-chain / non-null wrappers to the core expression. */
function unwrap(expr: TSESTree.Expression): TSESTree.Expression {
  let current = expr;
  while (
    current.type === AST_NODE_TYPES.ChainExpression ||
    current.type === AST_NODE_TYPES.TSNonNullExpression
  ) {
    current = current.expression;
  }
  return current;
}

/** A bare fire-and-forget call statement — `toast("done");`, `logEvent(...);`. */
function isBareCallStatement(stmt: TSESTree.Statement): boolean {
  return (
    stmt.type === AST_NODE_TYPES.ExpressionStatement &&
    unwrap(stmt.expression).type === AST_NODE_TYPES.CallExpression
  );
}

/**
 * Whether a top-level try-body statement can plausibly throw when the `try`
 * runs. See the file overview for the guards; the key ones are: `await` always
 * counts, and a bare fire-and-forget call statement (no `await`) does not.
 *
 * Blocks and `if`/`else` branches recurse so the bare-call exemption survives a
 * guard — a fire-and-forget call is no more throwing for sitting inside an
 * `if`. The guard's own TEST is still checked for a throwing call, keeping
 * `if (!validate(x))` counted. A compound statement still contributes at most
 * ONE to the caller's count; this predicate only decides whether it counts.
 */
function canThrow(stmt: TSESTree.Statement): boolean {
  if (hasAwait(stmt)) {
    return true;
  }
  if (isBareCallStatement(stmt)) {
    return false;
  }
  if (stmt.type === AST_NODE_TYPES.BlockStatement) {
    return stmt.body.some(canThrow);
  }
  if (stmt.type === AST_NODE_TYPES.IfStatement) {
    return (
      hasThrowingCallOrNew(stmt.test) ||
      canThrow(stmt.consequent) ||
      (stmt.alternate !== null && canThrow(stmt.alternate))
    );
  }
  return hasThrowingCallOrNew(stmt);
}

/**
 * Conservative: is the `catch` handler guaranteed to re-throw? True when a
 * handler is present and its body's last statement is a `throw`.
 */
function handlerRethrows(handler: TSESTree.CatchClause | null): boolean {
  if (handler === null) {
    return false;
  }
  const body = handler.body.body;
  const last = body[body.length - 1];
  return last !== undefined && last.type === AST_NODE_TYPES.ThrowStatement;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-fat-try-blocks",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow `try` blocks with more than three top-level statements that can throw — isolate the throwing statement and move non-throwing work outside.",
    },
    schema: [],
    messages: {
      fatTryBlock:
        "This `try` block has {{count}} statements that can throw (max {{max}}). Isolate the throwing statement(s); move non-throwing work outside the `try`.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }

    const sourceCode = context.sourceCode;

    return {
      TryStatement(node: TSESTree.TryStatement): void {
        if (node.finalizer !== null) {
          return;
        }
        if (handlerRethrows(node.handler)) {
          return;
        }

        const count = node.block.body.filter(canThrow).length;
        if (count <= MAX_TRY_BODY_STATEMENTS) {
          return;
        }

        const tryKeyword = sourceCode.getFirstToken(node);
        context.report({
          node: tryKeyword ?? node,
          messageId: "fatTryBlock",
          data: { count, max: MAX_TRY_BODY_STATEMENTS },
        });
      },
    };
  },
});
