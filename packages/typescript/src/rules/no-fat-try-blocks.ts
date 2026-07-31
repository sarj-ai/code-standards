/**
 * @fileoverview no-fat-try-blocks — a `try` holding more than three throwing statements catches failures its handler was never written for.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-fat-try-blocks.test.ts
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/no-fat-try-blocks.md
 */

import { type TSESTree, AST_NODE_TYPES } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "fatTryBlock";
type Options = readonly [];

const MAX_TRY_BODY_STATEMENTS = 3;

const NESTED_FUNCTION_TYPES = new Set<AST_NODE_TYPES>([
  AST_NODE_TYPES.FunctionDeclaration,
  AST_NODE_TYPES.FunctionExpression,
  AST_NODE_TYPES.ArrowFunctionExpression,
]);

/**
 * Non-throwing member methods, recognised by NAME ALONE — so the set may hold
 * only names that are not also the vocabulary of an I/O client.
 *
 * `get`, `set`, `add`, `delete`, `has`, `clear`, `find`, `keys`, `values` and
 * `entries` are the `Map` / `Set` API, and they are equally `client.get(url)`,
 * `redis.set(k, v)`, `repo.find(where)` and `api.delete(id)`. A name-only test
 * cannot tell those apart, and resolving the ambiguity towards "pure" blinds
 * the rule to the exact swallow it exists to catch, so they are not here.
 * `isBareCallStatement` still exempts fire-and-forget `cache.set(k, v);`
 * structurally, which is the common non-I/O use of the names left out.
 *
 * What remains are Array / String / Number members with no I/O reading: nothing
 * calls `.padStart()` on a database handle.
 */
const PURE_METHODS = new Set<string>([
  "map", "filter", "forEach", "reduce", "reduceRight", "findIndex",
  "findLast", "findLastIndex", "some", "every", "push", "pop", "shift",
  "unshift", "slice", "splice", "concat", "flat", "flatMap", "join", "reverse",
  "sort", "fill", "includes", "indexOf", "lastIndexOf", "at", "toString",
  "toLocaleString", "valueOf", "charAt", "charCodeAt", "codePointAt", "split",
  "padStart", "padEnd", "repeat", "trim", "trimStart", "trimEnd", "toUpperCase",
  "toLowerCase", "toFixed", "toPrecision", "startsWith", "endsWith",
]);

/** Non-throwing global namespaces called as `X.method(...)`. */
const PURE_NAMESPACES = new Set<string>([
  "Object", "Array", "Math", "JSON", "Number", "String", "Boolean", "console",
]);

/**
 * `Namespace.method` pairs that throw despite the namespace being pure.
 *
 * `JSON.parse` is the canonical throwing call in JavaScript and the canonical
 * reason anybody writes `try`/`catch`; calling it non-throwing blinded the rule
 * to its most common subject. `JSON.stringify` also throws — circular
 * structures, `BigInt` — but is overwhelmingly called on a value the same
 * function just built, so it stays pure. That is a recall choice, stated rather
 * than hidden.
 */
const IMPURE_NAMESPACE_METHODS = new Set<string>(["JSON.parse"]);

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
    return !IMPURE_NAMESPACE_METHODS.has(`${callee.object.name}.${property.name}`);
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
 * Walk `stmt`'s subtree until `predicate` matches a node. By default the walk
 * stays in the same scope (it does not descend into nested function/arrow
 * bodies); pass `descendIntoFunctions` to visit those too.
 */
function subtreeMatches(
  stmt: TSESTree.Node,
  predicate: (node: TSESTree.Node) => boolean,
  descendIntoFunctions = false,
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
      if (
        !descendIntoFunctions &&
        NESTED_FUNCTION_TYPES.has(current.type) &&
        key === "body"
      ) {
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
 * runs. `await` always counts; a bare fire-and-forget call statement does not.
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

/** Statements that hand control straight through to their own parent. */
const PASS_THROUGH_PARENTS = new Set<AST_NODE_TYPES>([
  AST_NODE_TYPES.IfStatement,
  AST_NODE_TYPES.TryStatement,
  AST_NODE_TYPES.CatchClause,
  AST_NODE_TYPES.LabeledStatement,
]);

/**
 * Clause (a): nothing in the enclosing function runs after `node`. The node must
 * be last in its block, and every enclosing block must itself be last, up to the
 * function boundary. A loop, `switch`, or any other construct in between means
 * the statement can be followed by more work, so it is not terminal.
 */
function isTerminalInFunction(node: TSESTree.Node): boolean {
  let current: TSESTree.Node = node;
  let parent: TSESTree.Node | undefined = current.parent;

  while (parent !== undefined) {
    if (parent.type === AST_NODE_TYPES.BlockStatement) {
      if (parent.body[parent.body.length - 1] !== current) {
        return false;
      }
    } else if (parent.type === AST_NODE_TYPES.Program) {
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

/** `await f()` unwrapped to `f()`; everything else unwrapped as usual. */
function unwrapAwait(expr: TSESTree.Expression): TSESTree.Expression {
  const inner = unwrap(expr);
  return inner.type === AST_NODE_TYPES.AwaitExpression
    ? unwrap(inner.argument)
    : inner;
}

/**
 * Clause (b): the handler ends by handing the failure off — a `return`, a
 * `throw`, or a bare call (`errorHandler(e, res);`). A handler that ends on
 * anything else (a branch, an assignment, a loop) is doing recovery work whose
 * correctness depends on which statement threw.
 */
function handlerEndsByHandingOff(handler: TSESTree.CatchClause): boolean {
  const body = handler.body.body;
  const last = body[body.length - 1];
  if (last === undefined) {
    return false;
  }
  if (
    last.type === AST_NODE_TYPES.ReturnStatement ||
    last.type === AST_NODE_TYPES.ThrowStatement
  ) {
    return true;
  }
  return (
    last.type === AST_NODE_TYPES.ExpressionStatement &&
    unwrapAwait(last.expression).type === AST_NODE_TYPES.CallExpression
  );
}

/**
 * Every identifier bound by a `catch` parameter pattern. Type annotations are
 * skipped — `catch (e: Error)` binds `e`, not `Error`, and counting the type
 * would let a handler that merely constructs an `Error` pass clause (c).
 */
function collectBindingNames(
  pattern: TSESTree.Node,
  names: Set<string>,
): void {
  if (pattern.type === AST_NODE_TYPES.Identifier) {
    names.add(pattern.name);
    return;
  }
  if (pattern.type === AST_NODE_TYPES.ObjectPattern) {
    for (const property of pattern.properties) {
      collectBindingNames(
        property.type === AST_NODE_TYPES.RestElement
          ? property.argument
          : property.value,
        names,
      );
    }
    return;
  }
  if (pattern.type === AST_NODE_TYPES.ArrayPattern) {
    for (const element of pattern.elements) {
      if (element !== null) {
        collectBindingNames(element, names);
      }
    }
    return;
  }
  if (
    pattern.type === AST_NODE_TYPES.AssignmentPattern ||
    pattern.type === AST_NODE_TYPES.RestElement
  ) {
    collectBindingNames(
      pattern.type === AST_NODE_TYPES.AssignmentPattern
        ? pattern.left
        : pattern.argument,
      names,
    );
  }
}

function caughtBindingNames(handler: TSESTree.CatchClause): ReadonlySet<string> {
  const names = new Set<string>();
  if (handler.param !== null) {
    collectBindingNames(handler.param, names);
  }
  return names;
}

/** A member property / object key spelled `x` is not a reference to `x`. */
function isPropertyName(node: TSESTree.Identifier): boolean {
  const parent = node.parent;
  if (parent.type === AST_NODE_TYPES.MemberExpression) {
    return parent.property === node && !parent.computed;
  }
  if (parent.type === AST_NODE_TYPES.Property) {
    return parent.key === node && !parent.computed;
  }
  return false;
}

/**
 * Clause (c): the handler references the caught error somewhere — it reports the
 * failure rather than discarding it. Nested callbacks count; a handler that logs
 * the error from inside a `.then()` still reports it.
 */
function handlerMentionsCaughtBinding(handler: TSESTree.CatchClause): boolean {
  const names = caughtBindingNames(handler);
  if (names.size === 0) {
    return false;
  }
  return subtreeMatches(
    handler.body,
    (n) =>
      n.type === AST_NODE_TYPES.Identifier &&
      names.has(n.name) &&
      !isPropertyName(n),
    true,
  );
}

/** `null`, `undefined`, `false`, `void 0`, `[]`, `{}` — a success-shaped value. */
function isSuccessShapedValue(expr: TSESTree.Expression): boolean {
  let current: TSESTree.Expression = expr;
  while (
    current.type === AST_NODE_TYPES.TSAsExpression ||
    current.type === AST_NODE_TYPES.TSNonNullExpression
  ) {
    current = current.expression;
  }
  if (current.type === AST_NODE_TYPES.Literal) {
    return current.value === null || current.value === false;
  }
  if (current.type === AST_NODE_TYPES.Identifier) {
    return current.name === "undefined";
  }
  if (current.type === AST_NODE_TYPES.UnaryExpression) {
    return current.operator === "void";
  }
  if (current.type === AST_NODE_TYPES.ArrayExpression) {
    return current.elements.length === 0;
  }
  if (current.type === AST_NODE_TYPES.ObjectExpression) {
    return current.properties.length === 0;
  }
  return false;
}

/**
 * Clause (d): the handler fabricates a success-shaped result. This is the shape
 * the rule exists for — an unknown one of N operations failed and the caller is
 * told "nothing found".
 */
const handlerReturnsSuccessShaped = (handler: TSESTree.CatchClause): boolean =>
  subtreeMatches(
    handler.body,
    (n) =>
      n.type === AST_NODE_TYPES.ReturnStatement &&
      n.argument !== null &&
      isSuccessShapedValue(n.argument),
  );

/**
 * The terminal error-propagating boundary exemption.
 */
function isTerminalErrorBoundary(node: TSESTree.TryStatement): boolean {
  const handler = node.handler;
  return (
    handler !== null &&
    isTerminalInFunction(node) &&
    handlerEndsByHandingOff(handler) &&
    handlerMentionsCaughtBinding(handler) &&
    !handlerReturnsSuccessShaped(handler)
  );
}

export default createRule<Options, MessageIds>({
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
        if (isTerminalErrorBoundary(node)) {
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
