/**
 * @fileoverview no-log-only-catch — a catch that only logs keeps the program running broken, with a log line as the only signal.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-log-only-catch.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, Scope } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


import {
  createLogMatcher,
  LOGGING_OPTION_PROPERTIES,
  type LoggingOptions,
} from "./_logging.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "noLogOnlyCatch" | "emptyCatch";
type Options = readonly [LoggingOptions?];

export const NO_LOG_ONLY_CATCH_DOCUMENTATION = {
  summary:
    "Disallow `catch` clauses that only log (or silently do nothing) and then swallow the error; rethrow or handle it instead.",
  rationale:
    "Swallowing an exception after logging lets execution continue as if the operation succeeded.",
  remediation:
    "Rethrow the error, return an explicit fallback, or perform concrete recovery.",
  category: "correctness",
  limitations: [
    "Documented intentional ignores, tests, and catches with observable recovery are excluded.",
  ],
  examples: [
    {
      id: "rethrow-after-log",
      title: "Preserve failure after logging",
      outcome: "no-match",
      files: [
        {
          path: "src/task.ts",
          source:
            "try { run(); } catch (error) { console.error(error); throw error; }",
        },
      ],
      focusPath: "src/task.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "log-and-swallow",
      title: "Do not only log a failure",
      outcome: "match",
      files: [
        {
          path: "src/task.ts",
          source: "try { run(); } catch (error) { console.error(error); }",
        },
      ],
      focusPath: "src/task.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

// A micro-benchmark harness swallows the throw it is timing; `_paths` owns the
// test-file question but does not yet know this segment, so it is local.
const BENCHMARK_DIR_RE = /(?:^|[\\/])benchmarks?[\\/]/;

const SINGLE_STATEMENT_HOSTS: ReadonlySet<string> = new Set([
  "DoWhileStatement",
  "ForInStatement",
  "ForOfStatement",
  "ForStatement",
  "IfStatement",
  "WhileStatement",
]);

const FUNCTION_TYPES: ReadonlySet<string> = new Set([
  "ArrowFunctionExpression",
  "FunctionDeclaration",
  "FunctionExpression",
]);

/** The statement list a node sits directly in, plus its index in that list. */
function statementSlot(
  node: ESTree.Node,
): { readonly list: readonly ESTree.Node[]; readonly index: number } | null {
  const parent = node.parent;
  if (parent == null) return null;
  let list: readonly ESTree.Node[];
  switch (parent.type) {
    case "BlockStatement":
    case "Program":
    case "StaticBlock":
      list = parent.body;
      break;
    case "SwitchCase":
      list = parent.consequent;
      break;
    default:
      return null;
  }
  const index = list.indexOf(node);
  return index === -1 ? null : { list, index };
}

/**
 * Class 1 — the try ends in a `return` and something follows the try, so the
 * catch's only job is to let control fall through to that fallback.
 */
function fallbackFollowsTry(tryStatement: ESTree.TryStatement): boolean {
  const body = tryStatement.block.body;
  const last = body.at(-1);
  return (
    last?.type === "ReturnStatement" && hasFollowingStatement(tryStatement)
  );
}

function hasFollowingStatement(node: ESTree.Node): boolean {
  for (
    let current: ESTree.Node | null | undefined = node;
    current != null && !FUNCTION_TYPES.has(current.type);
    current = current.parent
  ) {
    const slot = statementSlot(current);
    if (slot !== null && slot.index < slot.list.length - 1) return true;
  }
  return false;
}

function seededFallbackHandled(
  tryStatement: ESTree.TryStatement,
  scope: Scope,
): boolean {
  const slot = statementSlot(tryStatement);
  if (slot === null || slot.index === 0) return false;
  const previous = slot.list[slot.index - 1];
  if (previous?.type !== "VariableDeclaration" || previous.kind === "const") {
    return false;
  }
  const declarator = previous.declarations[0];
  if (previous.declarations.length !== 1 || declarator === undefined)
    return false;
  if (declarator.id.type !== "Identifier") return false;
  if (declarator.init == null || !isSeedValue(declarator.init)) return false;

  const variable = findVariable(scope, declarator.id.name);
  if (variable === null) return false;
  const [tryStart, tryEnd] = tryStatement.block.range;
  let writtenInTry = false;
  let readAfter = false;
  for (const reference of variable.references) {
    const [start] = reference.identifier.range;
    if (reference.isWrite() && start >= tryStart && start < tryEnd)
      writtenInTry = true;
    if (reference.isRead() && start >= tryStatement.range[1]) readAfter = true;
  }
  return writtenInTry && readAfter;
}

/** An explicit fallback seed: a literal, `undefined`, or an empty array/object. */
function isSeedValue(node: ESTree.Expression): boolean {
  const inner = node.type === "TSAsExpression" ? node.expression : node;
  switch (inner.type) {
    case "Literal":
      return true;
    case "Identifier":
      return inner.name === "undefined";
    case "UnaryExpression":
      return inner.argument.type === "Literal";
    case "ArrayExpression":
      return inner.elements.length === 0;
    case "ObjectExpression":
      return inner.properties.length === 0;
    default:
      return false;
  }
}

export default createRule<Options, MessageIds>({
  name: "no-log-only-catch",
  documentation: NO_LOG_ONLY_CATCH_DOCUMENTATION,
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
    const filename = sourceOrigin(context).filename;
    const sourceCode = context.sourceCode;

    function hasCoercionValidation(node: ESTree.CatchClause): boolean {
      const owner = node.parent;
      if (owner?.type !== "TryStatement") return false;
      const statement = owner.block.body[0];
      if (
        node.body.body.length !== 0 ||
        owner.finalizer !== null ||
        owner.block.body.length !== 1 ||
        statement?.type !== "ExpressionStatement" ||
        statement.expression.type !== "AssignmentExpression" ||
        statement.expression.operator !== "="
      )
        return false;
      const { left, right } = statement.expression;
      if (
        left.type !== "MemberExpression" ||
        left.computed ||
        left.object.type !== "Identifier" ||
        right.type !== "CallExpression" ||
        right.optional ||
        right.callee.type !== "Identifier" ||
        !["String", "Number", "Boolean", "BigInt"].includes(
          right.callee.name,
        ) ||
        right.arguments.length !== 1
      )
        return false;
      const argument = right.arguments[0];
      if (
        argument === undefined ||
        sourceCode.getText(left) !== sourceCode.getText(argument)
      )
        return false;
      const global = findVariable(
        sourceCode.getScope(right.callee),
        right.callee.name,
      );
      if (global !== null && global.defs.length > 0) return false;
      const root = findVariable(
        sourceCode.getScope(left.object),
        left.object.name,
      );
      if (
        root === null ||
        root.references.some(
          (reference) => reference.isWrite() && !reference.init,
        )
      )
        return false;
      return hasFollowingCoercionCheck(owner, left, right.callee.name);
    }

    function hasFollowingCoercionCheck(
      owner: ESTree.TryStatement,
      left: ESTree.MemberExpression,
      coercion: string,
    ): boolean {
      let current: ESTree.Node = owner;
      let slot = statementSlot(current);
      while (
        slot === null &&
        current.parent != null &&
        !FUNCTION_TYPES.has(current.parent?.type)
      ) {
        current = current.parent;
        slot = statementSlot(current);
      }
      let next = slot?.list[slot.index + 1];
      let target = sourceCode.getText(left);
      if (
        next?.type === "VariableDeclaration" &&
        next.kind === "const" &&
        next.declarations.length === 1
      ) {
        const alias = next.declarations[0];
        if (
          alias?.id.type !== "Identifier" ||
          alias.init === null ||
          sourceCode.getText(alias.init) !== target
        )
          return false;
        target = alias.id.name;
        next = slot?.list[slot.index + 2];
      }
      if (next?.type !== "IfStatement") return false;
      let condition = next.test;
      while (
        condition.type === "LogicalExpression" &&
        condition.operator === "&&"
      )
        condition = condition.left;
      if (
        condition.type !== "BinaryExpression" ||
        !["==", "==="].includes(condition.operator)
      )
        return false;
      const test = condition.left;
      return (
        test.type === "UnaryExpression" &&
        test.operator === "typeof" &&
        sourceCode.getText(test.argument) === target &&
        condition.right.type === "Literal" &&
        condition.right.value === coercion.toLowerCase()
      );
    }

    /** True when a statement is exactly a bare logging call, e.g. `console.error(err);`. */
    function isLoggingCallStatement(statement: ESTree.Statement): boolean {
      if (statement.type !== "ExpressionStatement") {
        return false;
      }
      return matcher.isLoggingCall(statement.expression);
    }

    /**
     * Class 3 — a rationale written next to the braces instead of inside them.
     */
    function hasAdjacentRationale(node: ESTree.CatchClause): boolean {
      const tryStatement = node.parent;
      if (tryStatement?.type !== "TryStatement") return false;
      if (
        hasCommentDirectlyAbove(tryStatement) ||
        hasCommentDirectlyAbove(node)
      )
        return true;
      const block = tryStatement.parent;
      if (
        block?.type !== "BlockStatement" ||
        block.body.length !== 1 ||
        block.parent == null ||
        !SINGLE_STATEMENT_HOSTS.has(block.parent?.type)
      ) {
        return false;
      }
      return hasCommentDirectlyAbove(block.parent);
    }

    /** True when a `//`/`/* *\/` run ends on the line directly above `node`. */
    function hasCommentDirectlyAbove(node: ESTree.Node): boolean {
      const above = sourceCode.getCommentsBefore(node).at(-1);
      return (
        above !== undefined && above.loc.end.line === node.loc.start.line - 1
      );
    }

    if (
      isTestFile(filename) ||
      BENCHMARK_DIR_RE.test(filename.replaceAll("\\", "/"))
    ) {
      return {};
    }

    return {
      CatchClause(node: ESTree.CatchClause): void {
        const statements = node.body.body;

        // A comment inside the block documents an intentional ignore — for a
        // silent swallow and for a log-and-continue alike.
        const isDocumented =
          sourceCode.getCommentsInside(node.body).length > 0 ||
          hasAdjacentRationale(node);

        if (
          isDocumented ||
          hasCoercionValidation(node) ||
          (node.parent?.type === "TryStatement" &&
            (fallbackFollowsTry(node.parent) ||
              seededFallbackHandled(node.parent, sourceCode.getScope(node))))
        ) {
          return;
        }

        if (statements.length === 0) {
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
