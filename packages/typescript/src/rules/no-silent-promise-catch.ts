/**
 * @fileoverview no-silent-promise-catch — a silent `.catch` or second `.then` handler deletes the rejection and returns a sentinel.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-silent-promise-catch.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "silentCatch";
type Options = readonly [];

export const noSilentPromiseCatchDocumentation = {
  summary: "Disallow `.catch()` and second-argument `.then()` handlers that silently swallow a rejection; log, rethrow, or handle the error.",
  rationale: "A swallowed rejection hides failures and gives callers an indistinguishable fallback value.",
  remediation: "Log, rethrow, or explicitly recover from the rejection; explain intentional teardown suppression.",
  category: "correctness",
  limitations: ["Test files, teardown calls, explanatory comments, non-function handlers, and handlers that consume or report the error are excluded."],
  examples: [
    { id: "reported-rejection", title: "Report the rejection", outcome: "no-match", files: [{ path: "src/load.ts", source: "load().catch((error) => logger.error({ error }, 'load failed'));" }], focusPath: "src/load.ts", expectedCount: 0, public: true },
    { id: "silent-rejection", title: "Do not swallow the rejection", outcome: "match", files: [{ path: "src/load.ts", source: "load().catch(() => null);" }], focusPath: "src/load.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

const BODY_PARSE_METHODS: ReadonlySet<string> = new Set([
  "arrayBuffer",
  "blob",
  "bytes",
  "formData",
  "json",
  "text",
]);

/** True for a standard Fetch body parser — the receiver of a parse-fallback catch. */
function isBodyParseCall(node: TSESTree.Expression): boolean {
  return (
    node.type === AST_NODE_TYPES.CallExpression &&
    node.arguments.length === 0 &&
    node.callee.type === AST_NODE_TYPES.MemberExpression &&
    !node.callee.computed &&
    node.callee.property.type === AST_NODE_TYPES.Identifier &&
    BODY_PARSE_METHODS.has(node.callee.property.name)
  );
}

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

export default createRule<Options, MessageIds>({
  name: "no-silent-promise-catch",
  documentation: noSilentPromiseCatchDocumentation,
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow `.catch()` and second-argument `.then()` handlers that silently swallow a rejection; log, rethrow, or handle the error.",
    },
    schema: [],
    messages: {
      silentCatch:
        "This rejection handler swallows the error without logging, rethrowing, or handling it — failures become invisible and callers get an indistinguishable sentinel. Log the error (and only then map to a fallback), or let it propagate.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename)) {
      return {};
    }

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
          node.callee.property.type !== AST_NODE_TYPES.Identifier
        ) {
          return;
        }

        const method = node.callee.property.name;
        const handlerIndex = method === "catch" ? 0 : method === "then" ? 1 : null;
        if (handlerIndex === null) return;

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

        const expectedArguments = method === "catch" ? 1 : 2;
        if (node.arguments.length !== expectedArguments) {
          return;
        }
        const handler = node.arguments[handlerIndex];
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
