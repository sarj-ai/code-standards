/**
 * @fileoverview no-log-only-catch — a catch that only logs keeps the program running broken, with a log line as the only signal.
 *
 * Port of the 18.x `no-log-only-catch` rule. Same algorithm; test and
 * benchmark files are skipped in `before()`, and parents are read with
 * `parentOf()` because Oxlint's `Program.parent` is `null`.
 */

import { defineRule, type ESTree, type Node, type Scope, type SourceCode } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { createLogMatcher, LOGGING_OPTION_PROPERTIES, type LoggingOptions, type LogMatcher } from "../utils/logging.js";
import { isTestFile } from "../utils/paths.js";
import { findVariable } from "../utils/static-string.js";

const NAME = "no-log-only-catch";

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

const COERCIONS: ReadonlySet<string> = new Set(["String", "Number", "Boolean", "BigInt"]);
const LOOSE_OR_STRICT_EQUALITY: ReadonlySet<string> = new Set(["==", "==="]);

const FUNCTION_TYPES: ReadonlySet<string> = new Set([
  "ArrowFunctionExpression",
  "FunctionDeclaration",
  "FunctionExpression",
]);

interface StatementSlot {
  readonly list: readonly Node[];
  readonly index: number;
}

/** The statement list a node sits directly in, plus its index in that list. */
function statementSlot(node: Node): StatementSlot | null {
  const parent = parentOf(node);
  if (parent === null) return null;
  let list: readonly Node[];
  switch (parent.type) {
    case "BlockStatement":
    case "Program":
    case "StaticBlock":
      list = parent.body as readonly Node[];
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
  return last?.type === "ReturnStatement" && hasFollowingStatement(tryStatement);
}

function hasFollowingStatement(node: Node): boolean {
  for (
    let current: Node | null = node;
    current !== null && !FUNCTION_TYPES.has(current.type);
    current = parentOf(current)
  ) {
    const slot = statementSlot(current);
    if (slot !== null && slot.index < slot.list.length - 1) return true;
  }
  return false;
}

function seededFallbackHandled(tryStatement: ESTree.TryStatement, scope: Scope): boolean {
  const name = seedDeclaredBefore(tryStatement);
  const variable = name === null ? null : findVariable(scope, name);
  if (variable === null) return false;
  const [tryStart, tryEnd] = tryStatement.block.range;
  const end = tryStatement.range[1];
  return variable.references.some((reference) =>
    reference.isWrite() && reference.identifier.range[0] >= tryStart && reference.identifier.range[0] < tryEnd) &&
    variable.references.some((reference) => reference.isRead() && reference.identifier.range[0] >= end);
}

/** The name of a lone `let`/`var` declarator, with a seed value, directly before the try. */
function seedDeclaredBefore(tryStatement: ESTree.TryStatement): string | null {
  const slot = statementSlot(tryStatement);
  const previous = slot === null ? undefined : slot.list[slot.index - 1];
  if (previous?.type !== "VariableDeclaration" || previous.kind === "const" || previous.declarations.length !== 1) return null;
  const declarator = previous.declarations[0];
  return declarator?.id.type === "Identifier" && declarator.init != null && isSeedValue(declarator.init)
    ? declarator.id.name : null;
}

/** The statement slot of `node` or of its nearest ancestor with one inside the same function. */
function enclosingStatementSlot(node: Node): StatementSlot | null {
  let current = node;
  let slot = statementSlot(current);
  for (let parent = parentOf(current); slot === null && parent !== null && !FUNCTION_TYPES.has(parent.type); parent = parentOf(current)) {
    current = parent;
    slot = statementSlot(current);
  }
  return slot;
}

/** The only statement of a try without finally, when it is a plain `=` assignment. */
function soleAssignment(tryStatement: ESTree.TryStatement): ESTree.AssignmentExpression | null {
  const statement = tryStatement.block.body.length === 1 ? tryStatement.block.body[0] : undefined;
  return tryStatement.finalizer === null && statement?.type === "ExpressionStatement" &&
    statement.expression.type === "AssignmentExpression" && statement.expression.operator === "=" ? statement.expression : null;
}

/** An explicit fallback seed: a literal, `undefined`, or an empty array/object. */
function isSeedValue(node: Node): boolean {
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

export default defineRule({
  meta: {
    defaultOptions: [{}],
    type: "problem",
    docs: {
      description:
        "Disallow `catch` clauses that only log (or silently do nothing) and then swallow the error; rethrow or handle it instead.",
      url: docsUrl(NAME),
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
  createOnce(context) {
    let matcher: LogMatcher;
    let sourceCode: SourceCode;
    // Options arrive per file; rebuild the matcher only when they change.
    let matcherOptions: unknown;

    function hasCoercionValidation(node: ESTree.CatchClause): boolean {
      const owner = parentOf(node) as ESTree.TryStatement;
      const assignment = node.body.body.length === 0 ? soleAssignment(owner) : null;
      if (assignment === null) return false;
      const { left, right } = assignment;
      if (left.type !== "MemberExpression" || left.computed || left.object.type !== "Identifier") return false;
      const coercion = selfCoercion(left, right);
      if (coercion === null) return false;
      const root = findVariable(sourceCode.getScope(left.object), left.object.name);
      if (root === null || root.references.some((reference) => reference.isWrite() && !reference.init)) return false;
      return hasFollowingCoercionCheck(owner, left, coercion);
    }

    /** The unshadowed global coercion that `right` applies to `left` itself, as in `String(left)`. */
    function selfCoercion(left: Node, right: Node): string | null {
      if (right.type !== "CallExpression" || right.optional || right.callee.type !== "Identifier" ||
        !COERCIONS.has(right.callee.name) || right.arguments.length !== 1) return null;
      const argument = right.arguments[0];
      if (argument === undefined || sourceCode.getText(left) !== sourceCode.getText(argument)) return null;
      const global = findVariable(sourceCode.getScope(right.callee), right.callee.name);
      return global !== null && global.defs.length > 0 ? null : right.callee.name;
    }

    function hasFollowingCoercionCheck(owner: ESTree.TryStatement, left: ESTree.MemberExpression, coercion: string): boolean {
      const slot = enclosingStatementSlot(owner);
      if (slot === null) return false;
      let next = slot.list[slot.index + 1];
      let target = sourceCode.getText(left);
      if (next?.type === "VariableDeclaration" && next.kind === "const" && next.declarations.length === 1) {
        const alias = next.declarations[0];
        if (alias?.id.type !== "Identifier" || alias.init === null || sourceCode.getText(alias.init) !== target) return false;
        target = alias.id.name;
        next = slot.list[slot.index + 2];
      }
      return next?.type === "IfStatement" && checksCoercedType(next.test, target, coercion);
    }

    /** `typeof target == "<coercion>"`, alone or leading an `&&` chain. */
    function checksCoercedType(test: Node, target: string, coercion: string): boolean {
      let condition = test;
      while (condition.type === "LogicalExpression" && condition.operator === "&&") condition = condition.left;
      if (condition.type !== "BinaryExpression" || !LOOSE_OR_STRICT_EQUALITY.has(condition.operator)) return false;
      const operand = condition.left;
      return operand.type === "UnaryExpression" && operand.operator === "typeof" &&
        sourceCode.getText(operand.argument) === target &&
        condition.right.type === "Literal" && condition.right.value === coercion.toLowerCase();
    }

    /**
     * Class 3 — a rationale written next to the braces instead of inside them.
     */
    function hasAdjacentRationale(node: ESTree.CatchClause): boolean {
      const tryStatement = parentOf(node) as ESTree.TryStatement;
      if (hasCommentDirectlyAbove(tryStatement) || hasCommentDirectlyAbove(node)) return true;
      const block = parentOf(tryStatement);
      const host = block === null ? null : parentOf(block);
      if (
        block?.type !== "BlockStatement" ||
        block.body.length !== 1 ||
        host === null ||
        !SINGLE_STATEMENT_HOSTS.has(host.type)
      ) {
        return false;
      }
      return hasCommentDirectlyAbove(host);
    }

    /** True when a `//`/`/* *\/` run ends on the line directly above `node`. */
    function hasCommentDirectlyAbove(node: Node): boolean {
      const above = sourceCode.getCommentsBefore(node).at(-1);
      return above !== undefined && above.loc.end.line === node.loc.start.line - 1;
    }

    return {
      before(): boolean | void {
        if (isTestFile({ filename: context.filename, cwd: context.cwd }) ||
          BENCHMARK_DIR_RE.test(context.filename.replaceAll("\\", "/"))) {
          return false;
        }
        sourceCode = context.sourceCode;
        const [loggingOptions] = context.options as unknown as readonly [LoggingOptions?];
        if (matcher === undefined || loggingOptions !== matcherOptions) {
          matcher = createLogMatcher(loggingOptions);
          matcherOptions = loggingOptions;
        }
      },
      CatchClause(node: ESTree.CatchClause): void {
        const statements = node.body.body;
        // Every statement is a bare logging call, e.g. `console.error(err);`.
        const messageId = statements.length === 0 ? "emptyCatch"
          : statements.every((statement) => statement.type === "ExpressionStatement" && matcher.isLoggingCall(statement.expression))
            ? "noLogOnlyCatch" : null;
        if (messageId === null) return;
        const tryStatement = parentOf(node) as ESTree.TryStatement;
        // A comment inside the block documents an intentional ignore — for a
        // silent swallow and for a log-and-continue alike.
        if (sourceCode.getCommentsInside(node.body).length > 0 || hasAdjacentRationale(node) ||
          hasCoercionValidation(node) || fallbackFollowsTry(tryStatement) ||
          seededFallbackHandled(tryStatement, sourceCode.getScope(node))) return;
        context.report({ node, messageId });
      },
    };
  },
});
