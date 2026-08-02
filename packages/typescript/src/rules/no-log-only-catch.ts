/**
 * @fileoverview no-log-only-catch — a catch that only logs keeps the program running broken, with a log line as the only signal.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-log-only-catch.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import {
  createLogMatcher,
  LOGGING_OPTION_PROPERTIES,
  type LoggingOptions,
} from "./_logging.js";
import { createRule } from "./_docs.js";
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

export default createRule<Options, MessageIds>({
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
