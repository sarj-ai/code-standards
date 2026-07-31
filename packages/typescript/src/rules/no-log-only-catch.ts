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
 * The documented-ignore exemption applies to BOTH message ids. A catch that logs
 * and explains why the failure is survivable is the same deliberate decision as
 * a comment-only empty catch, and the rule's own message ("handle it for real")
 * has nothing to add to it. Measured on 2,186 real TypeScript files (zod /
 * TanStack Query / react-router / swr / zustand): of 10 log-only hits, the one
 * carrying a written rationale was
 * react-router/packages/react-router-dev/vite/styles.ts:104 —
 * `catch { console.warn(...); // this can happen with dynamically imported
 * modules … }` — and it is precisely the case the rule should not litigate. A
 * bare `catch (e) { console.error(e); }` with no comment still fires (9 hits,
 * e.g. react-router/packages/react-router/lib/dom/ssr/fog-of-war.ts:209).
 *
 * A previous version fired the "logging then swallowing" message on empty and
 * comment-only catches that contained no logging call at all — the vast majority
 * of real-world hits — which was factually wrong. The two distinct message ids
 * keep each diagnostic accurate.
 *
 * Scope: this rule owns the `CatchClause` (try/catch) form ONLY. The promise
 * form — `.catch(() => {})`, `.catch(() => null)`, and every other handler that
 * provably does nothing — is owned entirely by `no-silent-promise-catch`, whose
 * detection is a strict superset of what this rule used to do there. Two rules
 * firing on one `.catch()` meant two messages and two suppression comments for
 * a single defect, so the promise path was removed from here.
 *
 * A logging call is recognised by the shared `_logging` matcher: a log method on
 * a logger receiver, plus any project-declared free logging function named in
 * the `logFunctions` option (`logEvent("x", { err })`). Structured loggers are
 * usually free functions, so without that option a catch that only calls one was
 * silently under-reported here — declaring it makes the shape visible.
 *
 * --- 2026-07 corpus audit (25,508 deduped TS/TSX files across 6 first-party
 * repos and zod / trpc / dub / openstatus / formbricks / documenso / unkey /
 * midday / papermark / cal.com / hono) -------------------------------------
 *
 * 780 findings (683 `noLogOnlyCatch`, 97 `emptyCatch`); 44 were read at random
 * and 15 of them (34.1%) were wrong. The three classes each get a guard here.
 *
 *  1. `fallbackFollowsTry` — an empty catch whose recovery is the statement
 *     AFTER the try. 4 of the 44. `hono/src/middleware/timing/timing.ts:30` is
 *     the canonical shape: `try { return performance.now() } catch {} return
 *     Date.now()`. The error IS handled — by the fallback the `return` inside
 *     the try skips over — and an in-body comment cannot express that better
 *     than the code already does. Recall cost: an empty catch whose try does not
 *     end in a `return`, or which nothing follows, still fires.
 *  2. `seededFallbackHandled` — an empty catch over an assignment to a binding
 *     seeded with an explicit fallback one line above and read after the try
 *     (`let msg = "…"; try { msg = (await r.json()).error } catch {} send(msg)`,
 *     cal.com/packages/app-store/jelly/api/callback.ts:28). Bounded four ways so
 *     it cannot widen into "any catch near a `let`": the declaration must be the
 *     IMMEDIATELY preceding statement, must be a single non-`const` binding with
 *     an explicit seed value, must be written inside the try block, and must be
 *     read after it. A bare `let x;` with no seed is not a fallback and still
 *     fires.
 *  3. `hasAdjacentRationale` — the rationale comment sits next to the braces
 *     rather than inside them, so `getCommentsInside` never saw it. 4 of the 44,
 *     e.g. openstatus/packages/api/src/router/page.ts:70 ("best-effort: the page
 *     is gone either way, a leaked Vercel attachment is recoverable while a
 *     failed delete is not") and
 *     dub/apps/web/lib/actions/partners/program-resources/update-program-resource.ts:133.
 *     Both write the rationale above the `if` that guards the try, so the scan
 *     covers the line above the `try`, the line above the `catch`, and — only
 *     when the try is the SOLE statement of its block — the line above the
 *     enclosing `if`/loop. Recall cost is the same one the in-body exemption
 *     already accepts: an unrelated comment above a try exempts its catch.
 *  4. Path drift: the rule shipped its own `\.test\.` / `\.spec\.` /
 *     `__tests__/` list instead of the shared `_paths.isTestFile`, so the
 *     `*-spec.ts` and `*-test.ts` suffix conventions were not exempt — 16 of the
 *     780 sat in files this rule already meant to skip, e.g. a cal.com
 *     `*.e2e-spec.ts` teardown at line 1892. Delegating removes the drift at
 *     zero recall cost. A further 22 sat under a `benchmarks/` directory
 *     (`zod/packages/zod/src/v3/benchmarks/object.ts:45` is `try {
 *     short.parse(null) } catch (_err) {}`, an expected-throw harness); that
 *     segment is handled locally here because `_paths` does not yet know it.
 *
 * DELIBERATELY still firing: 19 of the 44 were fire-and-forget boundaries —
 * telemetry (dub/packages/utils/src/functions/log.ts:47 is the logging helper
 * itself failing to reach Slack), analytics, cleanup, best-effort UI. Writing
 * one line saying so is cheap and makes the intent auditable, which is the whole
 * design of the documented-ignore exemption. The 10 unambiguous true positives
 * are worth the noise: cal.com/packages/app-store/zohocalendar/lib/
 * CalendarService.ts:77 returns stale expired credentials after a failed token
 * refresh, which is the exact failure mode the message describes.
 */

import { AST_NODE_TYPES, ASTUtils, ESLintUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import {
  createLogMatcher,
  LOGGING_OPTION_PROPERTIES,
  type LoggingOptions,
} from "./_logging.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "noLogOnlyCatch" | "emptyCatch";
type Options = readonly [LoggingOptions?];

// A micro-benchmark harness swallows the throw it is timing; `_paths` owns the
// test-file question but does not yet know this segment, so it is local.
const BENCHMARK_DIR_RE = /(?:^|[\\/])benchmarks?[\\/]/;

// Loop and branch bodies a lone try can be the whole content of. Reaching one
// level up through these is what finds the rationale comment that real code
// writes above the guard rather than inside the catch.
const SINGLE_STATEMENT_HOSTS: ReadonlySet<string> = new Set([
  AST_NODE_TYPES.DoWhileStatement,
  AST_NODE_TYPES.ForInStatement,
  AST_NODE_TYPES.ForOfStatement,
  AST_NODE_TYPES.ForStatement,
  AST_NODE_TYPES.IfStatement,
  AST_NODE_TYPES.WhileStatement,
]);

const FUNCTION_TYPES: ReadonlySet<string> = new Set([
  AST_NODE_TYPES.ArrowFunctionExpression,
  AST_NODE_TYPES.FunctionDeclaration,
  AST_NODE_TYPES.FunctionExpression,
]);

/** The statement list a node sits directly in, plus its index in that list. */
function statementSlot(
  node: TSESTree.Node,
): { readonly list: readonly TSESTree.Node[]; readonly index: number } | null {
  const parent = node.parent;
  if (parent === undefined) return null;
  let list: readonly TSESTree.Node[];
  switch (parent.type) {
    case AST_NODE_TYPES.BlockStatement:
    case AST_NODE_TYPES.Program:
    case AST_NODE_TYPES.StaticBlock:
      list = parent.body;
      break;
    case AST_NODE_TYPES.SwitchCase:
      list = parent.consequent;
      break;
    default:
      return null;
  }
  const index = list.indexOf(node);
  return index === -1 ? null : { list, index };
}

/**
 * True when some statement follows `node` once control leaves it — either in its
 * own statement list or in an enclosing one, stopping at the function boundary.
 * `try { return x } catch {}` inside an `if` is still guarded by the `return`
 * that follows the `if` (papermark/components/ui/timestamp-tooltip.tsx:41).
 */
function hasFollowingStatement(node: TSESTree.Node): boolean {
  for (
    let current: TSESTree.Node | undefined = node;
    current !== undefined && !FUNCTION_TYPES.has(current.type);
    current = current.parent
  ) {
    const slot = statementSlot(current);
    if (slot !== null && slot.index < slot.list.length - 1) return true;
  }
  return false;
}

/**
 * Class 1 — the try ends in a `return` and something follows the try, so the
 * catch's only job is to let control fall through to that fallback.
 */
function fallbackFollowsTry(tryStatement: TSESTree.TryStatement): boolean {
  const body = tryStatement.block.body;
  const last = body.at(-1);
  return last?.type === AST_NODE_TYPES.ReturnStatement && hasFollowingStatement(tryStatement);
}

/** An explicit fallback seed: a literal, `undefined`, or an empty array/object. */
function isSeedValue(node: TSESTree.Expression): boolean {
  const inner = node.type === AST_NODE_TYPES.TSAsExpression ? node.expression : node;
  switch (inner.type) {
    case AST_NODE_TYPES.Literal:
      return true;
    case AST_NODE_TYPES.Identifier:
      return inner.name === "undefined";
    case AST_NODE_TYPES.UnaryExpression:
      return inner.argument.type === AST_NODE_TYPES.Literal;
    case AST_NODE_TYPES.ArrayExpression:
      return inner.elements.length === 0;
    case AST_NODE_TYPES.ObjectExpression:
      return inner.properties.length === 0;
    default:
      return false;
  }
}

/**
 * Class 2 — `let x = <seed>;` immediately above the try, written inside it, read
 * after it. The seed IS the recovery value, so an empty catch is the whole
 * handler and there is nothing left for a comment to add.
 */
function seededFallbackHandled(
  tryStatement: TSESTree.TryStatement,
  scope: TSESLint.Scope.Scope,
): boolean {
  const slot = statementSlot(tryStatement);
  if (slot === null || slot.index === 0) return false;
  const previous = slot.list[slot.index - 1];
  if (previous?.type !== AST_NODE_TYPES.VariableDeclaration || previous.kind === "const") {
    return false;
  }
  const declarator = previous.declarations[0];
  if (previous.declarations.length !== 1 || declarator === undefined) return false;
  if (declarator.id.type !== AST_NODE_TYPES.Identifier) return false;
  if (declarator.init == null || !isSeedValue(declarator.init)) return false;

  const variable = ASTUtils.findVariable(scope, declarator.id.name);
  if (variable === null) return false;
  const [tryStart, tryEnd] = tryStatement.block.range;
  let writtenInTry = false;
  let readAfter = false;
  for (const reference of variable.references) {
    const [start] = reference.identifier.range;
    if (reference.isWrite() && start >= tryStart && start < tryEnd) writtenInTry = true;
    if (reference.isRead() && start >= tryStatement.range[1]) readAfter = true;
  }
  return writtenInTry && readAfter;
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
    const sourceCode = context.sourceCode;

    /** True when a statement is exactly a bare logging call, e.g. `console.error(err);`. */
    function isLoggingCallStatement(statement: TSESTree.Statement): boolean {
      if (statement.type !== "ExpressionStatement") {
        return false;
      }
      return matcher.isLoggingCall(statement.expression);
    }

    /** True when a `//`/`/* *\/` run ends on the line directly above `node`. */
    function hasCommentDirectlyAbove(node: TSESTree.Node): boolean {
      const above = sourceCode.getCommentsBefore(node).at(-1);
      return above !== undefined && above.loc.end.line === node.loc.start.line - 1;
    }

    /**
     * Class 3 — a rationale written next to the braces instead of inside them.
     */
    function hasAdjacentRationale(node: TSESTree.CatchClause): boolean {
      const tryStatement = node.parent;
      if (hasCommentDirectlyAbove(tryStatement) || hasCommentDirectlyAbove(node)) return true;
      const block = tryStatement.parent;
      if (
        block?.type !== AST_NODE_TYPES.BlockStatement ||
        block.body.length !== 1 ||
        block.parent === undefined ||
        !SINGLE_STATEMENT_HOSTS.has(block.parent.type)
      ) {
        return false;
      }
      return hasCommentDirectlyAbove(block.parent);
    }

    if (isTestFile(filename) || BENCHMARK_DIR_RE.test(filename.replaceAll("\\", "/"))) {
      return {};
    }

    return {
      CatchClause(node: TSESTree.CatchClause): void {
        const statements = node.body.body;

        // A comment inside the block documents an intentional ignore — for a
        // silent swallow and for a log-and-continue alike.
        const isDocumented =
          sourceCode.getCommentsInside(node.body).length > 0 || hasAdjacentRationale(node);

        if (statements.length === 0) {
          if (isDocumented) {
            return;
          }
          // The recovery can live outside the catch, where no comment can
          // describe it better than the code already does.
          if (
            fallbackFollowsTry(node.parent) ||
            seededFallbackHandled(node.parent, sourceCode.getScope(node))
          ) {
            return;
          }
          context.report({ node, messageId: "emptyCatch" });
          return;
        }

        if (isDocumented) {
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
