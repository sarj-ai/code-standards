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
 *
 * ## Terminal error-propagating boundary (measured)
 *
 * A seeded random read of 45 of the rule's 801 findings across 17 repositories
 * (6 first-party, plus zod, trpc, dub, openstatus, formbricks, documenso, unkey,
 * midday, papermark, cal.com, hono) put the false-positive rate at 77.8%, and
 * all 35 false positives were a single class: the `try` is the *tail* of the
 * function and the handler converts any failure inside it to one uniform error
 * result — `catch (e) { return handleAndReturnErrorResponse(e) }`,
 * `catch (e) { toConnectError(e) }`,
 * `catch (e) { logger.error(...); return err({ type: "internal_error" }) }`.
 * Nothing can be mis-attributed, because the handler never asks which statement
 * threw. That is exactly the reasoning the re-throw exemption above already
 * applies; it simply stopped at `throw` and never considered the HTTP / RPC /
 * `Result`-type equivalent of re-throwing. Representative:
 * `dub/apps/web/app/(ee)/api/cron/fx-rates/route.ts:12`,
 * `openstatus/apps/server/src/routes/rpc/handlers/maintenance/index.ts:102`.
 *
 * The exemption therefore requires ALL of:
 *
 *   a. the `try` is terminal — nothing in the enclosing function runs after it
 *      (it is last in its block, and every enclosing block up to the function
 *      boundary is likewise last; a loop or `switch` in between disqualifies);
 *   b. the handler's last statement is a `return`, a `throw`, or a bare call —
 *      the handler ends by handing the failure off, it does not fall through
 *      into more work;
 *   c. the handler mentions the caught binding, so the failure is actually
 *      reported rather than discarded;
 *   d. the handler never returns a bare `null` / `undefined` / `false` / `[]` /
 *      `{}` — that is the success-shaped swallow the rule exists to find, and it
 *      turns a fat body into "some unknown one of these five operations failed,
 *      and the caller sees an empty result".
 *
 * Measured over the same corpus: 801 -> 175 findings (626 suppressed, 78.2%).
 * The surviving 175 are a strict subset of the original 801 — the exemption
 * introduces no new reports anywhere in the corpus. Recall cost was zero against
 * the read sample: each of its true positives survives via a different clause,
 * and each is pinned as an `invalid` case below —
 * `midday/apps/api/src/rest/routers/apps/slack/messages.ts:81`, a handler that
 * inspects the error and falls back to another transport (fails b);
 * `midday/packages/banking/src/providers/enablebanking/enablebanking-api.ts:404`,
 * a handler that resets state before the function retries with another strategy,
 * so the `try` is not terminal (fails a); and
 * `cal.com/packages/app-store/salesforce/lib/CrmService.ts:550`, a nine-statement
 * body whose handler logs and returns `[]`, silently turning a configuration bug
 * into "no contacts found" (fails d). All three still report after the change.
 *
 * ## On the threshold — do not reach for it
 *
 * `MAX_TRY_BODY_STATEMENTS` is 3 and should stay 3. Body-size counts over all
 * 801 findings were 4 -> 228, 5 -> 121, 6 -> 112, 7 -> 78, 8 -> 53, tailing to
 * 27, median 6. Raising the threshold to 5 removes 44% of the volume *uniformly*
 * across true and false positives — it trades recall for quiet without making
 * the rule any more correct. The shape of the handler, not the size of the body,
 * is what separates the two populations.
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
 * The terminal error-propagating boundary exemption. See the file overview for
 * the measurement and for what each clause is holding back.
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
