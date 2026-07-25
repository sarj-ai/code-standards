/**
 * @fileoverview Disallow `catch` clauses that only log (via `console.*` or a
 * logger receiver such as `logger.warn(...)` / `Log.error(...)`) and then
 * swallow the error. A catch that logs and falls through — with no `throw`, no
 * `return`, and no real recovery — hides failures: the program keeps running in
 * a broken state while the only signal is a log line that is easy to miss.
 * Either rethrow the error or handle it for real.
 *
 * This rule is deliberately conservative and fires in exactly two shapes:
 *   - `noLogOnlyCatch`: the catch body is non-empty and *every* statement is a
 *     logging call (`console.*` or a call on a logger-named receiver). Any other
 *     statement (a `throw`, a `return`, a fallback assignment, a non-logging
 *     call, etc.) means the catch is doing something and is left alone.
 *   - `emptyCatch`: the catch body is genuinely empty AND carries no comment.
 *     A comment-only catch (`catch { /* ignore, safe because … *\/ }`) is treated
 *     as an intentional, documented ignore and is exempt.
 *
 * A previous version fired the "logging then swallowing" message on empty and
 * comment-only catches that contained no logging call at all — the vast majority
 * of real-world hits — which was factually wrong. The two distinct message ids
 * keep each diagnostic accurate.
 *
 * The promise form of a totally empty catch — `.catch(() => {})` — is handled
 * too, and reported as `emptyCatch`. Only the genuinely empty, comment-free
 * handler is flagged: a promise `.catch` that logs is often a legitimate
 * terminal handler at the end of a chain, so unlike the `CatchClause` case the
 * log-only shape is NOT flagged in promise form. The sentinel-returning promise
 * form (`.catch(() => [])`) belongs to `no-sentinel-return-on-catch`.
 *
 * Test files opt out by default (filenames containing `.test.`, `.spec.`, or a
 * `__tests__/` path segment) since swallow-and-log is common and acceptable in
 * test scaffolding.
 *
 * A logging call is recognised by the shared `_logging` matcher: a log method on
 * a logger receiver, plus any project-declared free logging function named in
 * the `logFunctions` option (`logEvent("x", { err })`). Structured loggers are
 * usually free functions, so without that option a catch that only calls one was
 * silently under-reported here — declaring it makes the shape visible.
 */

import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import {
  createLogMatcher,
  LOGGING_OPTION_PROPERTIES,
  type LoggingOptions,
} from "./_logging.js";

type MessageIds = "noLogOnlyCatch" | "emptyCatch";
type Options = readonly [LoggingOptions?];

const DEFAULT_IGNORE_PATTERNS: readonly RegExp[] = [
  /\.test\./,
  /\.spec\./,
  /[\\/]__tests__[\\/]/,
];

/**
 * The inline handler of a promise `.catch(fn)` whose body is an entirely empty
 * block, or null. A named handler (`.catch(onError)`) is reviewable on its own
 * terms and an expression body (`.catch(() => [])`) is a sentinel return, which
 * `no-sentinel-return-on-catch` owns.
 */
function emptyPromiseCatchHandler(
  node: TSESTree.CallExpression,
): TSESTree.BlockStatement | null {
  const callee = node.callee;
  if (
    callee.type !== "MemberExpression" ||
    callee.computed ||
    callee.property.type !== "Identifier" ||
    callee.property.name !== "catch"
  ) {
    return null;
  }
  const handler = node.arguments[0];
  if (
    handler === undefined ||
    (handler.type !== "ArrowFunctionExpression" &&
      handler.type !== "FunctionExpression")
  ) {
    return null;
  }
  if (handler.body.type !== "BlockStatement" || handler.body.body.length > 0) {
    return null;
  }
  return handler.body;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-log-only-catch",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow `catch` clauses that only log (or silently do nothing) and then swallow the error; rethrow or handle it instead.",
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: { ...LOGGING_OPTION_PROPERTIES },
      },
    ],
    messages: {
      noLogOnlyCatch:
        "Logging then swallowing the error hides failures. Rethrow the error or handle it for real.",
      emptyCatch:
        "Empty catch silently swallows the error. Rethrow it, handle it, or add a comment explaining why it is safe to ignore.",
    },
  },
  defaultOptions: [{}],
  create(context, [loggingOptions]) {
    const matcher = createLogMatcher(loggingOptions);
    const filename = context.filename;

    /** True when a statement is exactly a bare logging call, e.g. `console.error(err);`. */
    function isLoggingCallStatement(statement: TSESTree.Statement): boolean {
      if (statement.type !== "ExpressionStatement") {
        return false;
      }
      return matcher.isLoggingCall(statement.expression);
    }

    const isIgnoredByDefault = DEFAULT_IGNORE_PATTERNS.some((re) =>
      re.test(filename),
    );

    if (isIgnoredByDefault) {
      return {};
    }

    return {
      CallExpression(node: TSESTree.CallExpression): void {
        const body = emptyPromiseCatchHandler(node);
        if (body === null) {
          return;
        }
        // A comment inside the handler documents an intentional ignore.
        if (context.sourceCode.getCommentsInside(body).length > 0) {
          return;
        }
        context.report({ node, messageId: "emptyCatch" });
      },
      CatchClause(node: TSESTree.CatchClause): void {
        const statements = node.body.body;

        if (statements.length === 0) {
          // A comment inside the block documents an intentional ignore; only a
          // truly empty catch is an unexplained silent swallow.
          if (context.sourceCode.getCommentsInside(node.body).length > 0) {
            return;
          }
          context.report({ node, messageId: "emptyCatch" });
          return;
        }

        const everyStatementIsLogging = statements.every((statement) =>
          isLoggingCallStatement(statement),
        );

        if (everyStatementIsLogging) {
          context.report({ node, messageId: "noLogOnlyCatch" });
        }
      },
    };
  },
});
