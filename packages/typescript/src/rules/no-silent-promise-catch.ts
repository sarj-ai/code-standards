/**
 * @fileoverview Flag `.catch()` handlers that silently swallow the rejection:
 * `promise.catch(() => null)` and friends. These are the promise-chain twin of
 * the empty-`catch`-block anti-pattern already covered by the try/catch rules —
 * the failure vanishes with no log, no metric, no rethrow, and the caller
 * receives a sentinel it usually cannot distinguish from a real value.
 *
 * Only handlers that provably do nothing are flagged: an arrow/function whose
 * entire body is a bare literal (`null`, `undefined`, a number, a string, a
 * boolean), an empty object/array literal, an empty block, or a block that
 * only `return`s one of those. A handler that references its error parameter
 * or calls anything (logging, metrics, rethrow) is never flagged.
 *
 * Two corpus-driven exemptions (5-repo sweep, 2026-07: 11/35 raw hits — 31% —
 * were these deliberate idioms):
 *   - `res.json().catch(() => ({}))` / `res.text().catch(() => '')` — the
 *     body-parse-fallback idiom while composing error diagnostics; the parse
 *     failure itself is not the signal being handled.
 *   - Test files (`.test.` / `.spec.` / `__tests__/`), where silencing a
 *     promise is routine unhandled-rejection suppression.
 *
 * A SECOND SWEEP (2220 files across zod / TanStack Query / react-router / swr /
 * zustand, 2026-07) produced 16 hits, of which 11 were false positives in three
 * families. All three are now exempt:
 *
 *   - **Documented on purpose.** The handler body (or the line above / beside
 *     the call) carries a comment explaining the suppression. The rule's
 *     complaint is that the decision is invisible; a comment is exactly the
 *     thing that makes it visible, and the author has already answered.
 *     `query/packages/query-core/src/thenable.ts:54`
 *     (`thenable.catch(() => { /* prevent unhandled rejection errors *\/ })`) and
 *     `react-router/packages/react-router/lib/router/router.ts:6052-6053`
 *     (`// Prevent unhandled rejection errors - handled inside of \`callLoadOrAction\``
 *     directly above `lazyRoutePromise.catch(() => {})`) are the shape: the
 *     promise is ALSO consumed by the real handler, and this `.catch` exists only
 *     to stop the runtime's unhandled-rejection warning. 7 of the 16 hits.
 *   - **The chain continues.** `p.catch(() => null).then(…)` — the sentinel is
 *     consumed by the very next link, which IS the recovery, so no caller ever
 *     receives an indistinguishable value.
 *     `react-router/integration/helpers/playwright-fixture.ts:318`.
 *   - **Teardown calls.** `.cancel()` / `.close()` / `.abort()` / `.destroy()` /
 *     `.dispose()` / `.unlock()` reject when the resource is already gone, which
 *     is the outcome the caller wanted; the rejection is not the signal, exactly
 *     as for the `res.json()` fallback above.
 *     `react-router/packages/react-router/lib/rsc/html-stream/server.ts:80`
 *     (`await rscReader.cancel(reason).catch(() => {})`, inside the stream's own
 *     abort path). 3 of the 16 hits.
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isTestFile } from "./_paths.js";

type MessageIds = "silentCatch";
type Options = readonly [];

/** True for `x.json()` / `x.text()` — the receiver of a body-parse-fallback catch. */
function isBodyParseCall(node: TSESTree.Expression): boolean {
  return (
    node.type === AST_NODE_TYPES.CallExpression &&
    node.arguments.length === 0 &&
    node.callee.type === AST_NODE_TYPES.MemberExpression &&
    !node.callee.computed &&
    node.callee.property.type === AST_NODE_TYPES.Identifier &&
    (node.callee.property.name === "json" ||
      node.callee.property.name === "text")
  );
}

/**
 * Teardown methods that reject when the resource is already gone — which is the
 * state the caller was asking for. The rejection carries no signal, so silencing
 * it is correct, the same reasoning as the `res.json()` fallback above.
 */
const TEARDOWN_METHODS: ReadonlySet<string> = new Set([
  "cancel",
  "close",
  "abort",
  "destroy",
  "dispose",
  "release",
  "unlock",
  "disconnect",
]);

/**
 * Tooling directives are machinery, not an explanation of the swallow. An
 * `eslint-disable` already suppresses the report through the normal channel, so
 * counting it as documentation would turn every directive into an unused one.
 */
const DIRECTIVE_COMMENT_RE =
  /^\s*(eslint-|@ts-|prettier-ignore|biome-ignore|c8 |v8 |istanbul )/;

const isExplanatory = (comment: { value: string }): boolean =>
  !DIRECTIVE_COMMENT_RE.test(comment.value);

/** True for `reader.cancel(reason)` / `stream.close()` — a teardown receiver. */
function isTeardownCall(node: TSESTree.Expression): boolean {
  return (
    node.type === AST_NODE_TYPES.CallExpression &&
    node.callee.type === AST_NODE_TYPES.MemberExpression &&
    !node.callee.computed &&
    node.callee.property.type === AST_NODE_TYPES.Identifier &&
    TEARDOWN_METHODS.has(node.callee.property.name)
  );
}

/** True for expressions that provably discard the error: bare literals,
 * `undefined`, empty object/array literals. */
function isSilentExpression(node: TSESTree.Expression): boolean {
  switch (node.type) {
    case AST_NODE_TYPES.Literal:
      // null / number / string / boolean literals (regex literals excluded —
      // nobody writes `.catch(() => /x/)` and they are not sentinel values).
      return !("regex" in node);
    case AST_NODE_TYPES.Identifier:
      return node.name === "undefined";
    case AST_NODE_TYPES.UnaryExpression:
      // `void 0` — the other spelling of undefined.
      return (
        node.operator === "void" &&
        node.argument.type === AST_NODE_TYPES.Literal
      );
    case AST_NODE_TYPES.ObjectExpression:
      return node.properties.length === 0;
    case AST_NODE_TYPES.ArrayExpression:
      return node.elements.length === 0;
    case AST_NODE_TYPES.TSAsExpression:
      // `.catch(() => null as Foo | null)` is still silent.
      return isSilentExpression(node.expression);
    default:
      return false;
  }
}

/** True when the handler's whole body provably does nothing with the error. */
function isSilentHandler(
  handler: TSESTree.ArrowFunctionExpression | TSESTree.FunctionExpression,
): boolean {
  const body = handler.body;

  if (body.type !== AST_NODE_TYPES.BlockStatement) {
    // Arrow expression body: `.catch(() => null)`
    return isSilentExpression(body);
  }

  if (body.body.length === 0) {
    // `.catch(() => {})` / `.catch(function () {})`
    return true;
  }

  if (body.body.length === 1) {
    const only = body.body[0];
    if (only !== undefined && only.type === AST_NODE_TYPES.ReturnStatement) {
      // `.catch(() => { return null; })`
      return only.argument === null || isSilentExpression(only.argument);
    }
  }

  return false;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-silent-promise-catch",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow `.catch()` handlers that silently swallow the rejection (e.g. `.catch(() => null)`); log, rethrow, or handle the error.",
    },
    schema: [],
    messages: {
      silentCatch:
        "This `.catch()` swallows the rejection without logging, rethrowing, or handling it — failures become invisible and callers get an indistinguishable sentinel. Log the error (and only then map to a fallback), or let it propagate.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename)) {
      return {};
    }

    /**
     * True when the suppression is DOCUMENTED: a comment inside the handler
     * body, trailing the call on the same line, or on the line(s) directly above
     * the statement the call belongs to. The rule's complaint is that the
     * decision to discard the error is invisible — a comment is precisely what
     * makes it visible, so there is nothing left to report.
     */
    const hasExplanatoryComment = (
      call: TSESTree.CallExpression,
      handler: TSESTree.ArrowFunctionExpression | TSESTree.FunctionExpression,
    ): boolean => {
      const sourceCode = context.sourceCode;
      if (sourceCode.getCommentsInside(handler).some(isExplanatory)) {
        return true;
      }
      // Walk out to the enclosing statement so a comment above or beside
      // `lazyRoutePromise.catch(() => {});` is found rather than one sitting
      // between the receiver and `.catch`.
      let statement: TSESTree.Node = call;
      while (
        statement.parent !== undefined &&
        statement.parent !== null &&
        !statement.type.endsWith("Statement") &&
        statement.type !== AST_NODE_TYPES.VariableDeclaration
      ) {
        statement = statement.parent;
      }
      if (sourceCode.getCommentsBefore(statement).some(isExplanatory)) {
        return true;
      }
      return sourceCode
        .getCommentsAfter(statement)
        .some(
          (c) => isExplanatory(c) && c.loc.start.line === statement.loc.end.line,
        );
    };

    return {
      CallExpression(node: TSESTree.CallExpression): void {
        if (
          node.callee.type !== AST_NODE_TYPES.MemberExpression ||
          node.callee.computed ||
          node.callee.property.type !== AST_NODE_TYPES.Identifier ||
          node.callee.property.name !== "catch"
        ) {
          return;
        }

        if (isBodyParseCall(node.callee.object)) {
          return;
        }

        if (isTeardownCall(node.callee.object)) {
          return;
        }

        // `p.catch(() => null).then(...)` — the next link consumes the fallback,
        // so it is a recovery step, not a value handed back to an outside caller.
        if (
          node.parent.type === AST_NODE_TYPES.MemberExpression &&
          node.parent.object === node
        ) {
          return;
        }

        if (node.arguments.length !== 1) {
          return;
        }
        const handler = node.arguments[0];
        if (
          handler === undefined ||
          (handler.type !== AST_NODE_TYPES.ArrowFunctionExpression &&
            handler.type !== AST_NODE_TYPES.FunctionExpression)
        ) {
          return;
        }

        if (hasExplanatoryComment(node, handler)) {
          return;
        }

        if (isSilentHandler(handler)) {
          // Anchor on the CallExpression, not the handler: when the handler
          // sits on a later line than the call (multi-line `.catch(`), a
          // handler-anchored report escapes an `eslint-disable-next-line`
          // above the call AND marks that directive as unused.
          context.report({ node, messageId: "silentCatch" });
        }
      },
    };
  },
});
