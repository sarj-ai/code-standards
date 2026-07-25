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
