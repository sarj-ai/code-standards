/**
 * @fileoverview no-dynamic-sql — bind runtime values separately from SQL string literals.
 *
 * Port of the 18.x `no-dynamic-sql` rule. The rule is untyped, so the
 * port covers all of it.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { sqlNoiseInfo, stripSqlNoise } from "../utils/sql.js";
import { getPropertyName, staticString } from "../utils/static-string.js";

const NAME = "no-dynamic-sql";

type MessageIds = "dynamicSql" | "dynamicFragment";

interface RuleOptions {
  readonly methods?: readonly string[];
}

const DEFAULT_METHODS: readonly string[] = ["prepare", "exec", "query"];

/** A module-level constant fragment: `CANDIDATE_COLS`, `TABLE_NAME`. */
const CONSTANT_CASE_RE = /^[A-Z][A-Z0-9_]*$/;

interface SqlInterpolation {
  readonly expression: Node;
  readonly messageId: MessageIds;
}

type SqlNoise = ReturnType<typeof sqlNoiseInfo>;

/** Runtime expressions embedded in a quoted value or an unquoted SQL fragment. */
function runtimeInterpolations(
  template: ESTree.TemplateLiteral,
): SqlInterpolation[] {
  const parts = template.quasis.map((quasi) => quasi.value.cooked ?? quasi.value.raw);
  const sql = sqlNoiseInfo(parts.join(RUNTIME_MARKER));
  let offset = 0;
  return template.expressions.flatMap((expression, index) => {
    offset += (parts[index]?.length ?? 0);
    const found = interpolation(expression, offset, sql);
    offset += RUNTIME_MARKER.length;
    return found;
  });
}

function runtimeConcatOperands(node: Node): SqlInterpolation[] {
  if (node.type !== "BinaryExpression" || node.operator !== "+") {
    return [];
  }
  const operands = concatOperands(node);
  const texts = operands.map((operand) => staticString(operand));
  if (texts.every((text) => text === null)) {
    return [];
  }
  const parts = texts.map((text) => text ?? RUNTIME_MARKER);
  const sql = sqlNoiseInfo(parts.join(""));
  let offset = 0;
  return operands.flatMap((operand, index) => {
    const found = interpolation(operand, offset, sql);
    offset += parts[index]?.length ?? 0;
    return found;
  });
}

/** Classify the runtime operand whose text starts at `offset` in the reconstructed statement. */
function interpolation(expression: Node, offset: number, sql: SqlNoise): SqlInterpolation[] {
  if (isStaticFragment(expression)) return [];
  if (sql.singleQuotedRanges.some(([start, end]) => start < offset && offset < end)) {
    return [{ expression, messageId: "dynamicSql" }];
  }
  const unquoted = sql.text.slice(offset, offset + RUNTIME_MARKER.length) === RUNTIME_MARKER;
  return unquoted ? [{ expression, messageId: "dynamicFragment" }] : [];
}

/**
 * True when an interpolated expression is a compile-time SQL fragment rather
 * than runtime data: a CONSTANT_CASE identifier, a member access whose final
 * property is CONSTANT_CASE (`TABLES.USERS`), or a string literal.
 */
function isStaticFragment(expression: Node): boolean {
  expression = unwrapExpression(expression);
  if (expression.type === "Identifier") {
    return CONSTANT_CASE_RE.test(expression.name);
  }
  if (expression.type === "MemberExpression") {
    const name = getPropertyName(expression);
    return name !== null && CONSTANT_CASE_RE.test(name);
  }
  if (expression.type === "Literal") {
    return typeof expression.value === "string";
  }
  if (expression.type === "TemplateLiteral") {
    return expression.expressions.length === 0;
  }
  return false;
}

function concatOperands(node: Node): Node[] {
  const operands: Node[] = [];
  const pending = [node];
  for (let next = pending.pop(); next !== undefined; next = pending.pop()) {
    const value = unwrapExpression(next);
    if (value.type === "BinaryExpression" && value.operator === "+") {
      pending.push(value.right, value.left);
    } else operands.push(value);
  }
  return operands;
}

const SQL_STATEMENT_RE =
  /\b(?:select\s|insert\s+into\b|insert\s+or\b|update\s+\w|delete\s+from\b|replace\s+into\b|merge\s+into\b|upsert\s+into\b|create\s+(?:temp(?:orary)?\s+)?(?:table|index|view|trigger|schema|database)\b|alter\s+table\b|drop\s+(?:table|index|view|trigger)\b|truncate\s+table\b|pragma\s+\w|with\s+\w+\s+as\s*\(|from\s+\w+\s+where\b)/i;

/** The marker a non-static operand contributes to the reconstructed statement text. */
const RUNTIME_MARKER = " ? ";

/** True when the statement argument reads as SQL rather than as a shell command line. */
function looksLikeSql(node: Node): boolean {
  return SQL_STATEMENT_RE.test(stripSqlNoise(staticStatementText(node)));
}

function staticStatementText(node: Node): string {
  node = unwrapExpression(node);
  if (node.type === "TemplateLiteral") {
    return node.quasis.map((quasi) => quasi.value.cooked ?? quasi.value.raw).join(RUNTIME_MARKER);
  }
  if (node.type === "Literal") {
    return typeof node.value === "string" ? node.value : RUNTIME_MARKER;
  }
  if (node.type === "BinaryExpression" && node.operator === "+") {
    return staticStatementText(node.left) + staticStatementText(node.right);
  }
  return RUNTIME_MARKER;
}

/** The inspected method name of `receiver.method(...)`, or null. */
function statementMethodName(
  node: ESTree.CallExpression,
  methods: ReadonlySet<string>,
): string | null {
  const callee = unwrapExpression(node.callee);
  const name = callee.type === "MemberExpression" ? getPropertyName(callee) : null;
  return name !== null && methods.has(name) ? name : null;
}

export default defineRule({
  meta: {
    defaultOptions: [{}],
    type: "problem",
    docs: {
      description: "Disallow runtime values and fragments interpolated into SQL passed to statement-execution methods.",
      url: docsUrl(NAME),
    },
    schema: [
      {
        type: "object",
        properties: {
          methods: {
            type: "array",
            items: { type: "string" },
            description:
              "Statement-taking method names to inspect. Replaces the defaults.",
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      dynamicSql:
        "Runtime value embedded inside a quoted SQL value passed to `{{method}}()`. Replace the quoted interpolation with a placeholder and bind the value separately.",
      dynamicFragment:
        "Runtime fragment interpolated into SQL passed to `{{method}}()`. Bind data values; select non-bindable SQL fragments from fixed, reviewed alternatives.",
    },
  },
  createOnce(context) {
    let methodNames: readonly string[] = DEFAULT_METHODS;
    let methods: ReadonlySet<string> = new Set(DEFAULT_METHODS);
    return {
      before() {
        const options = context.options[0] as RuleOptions | undefined;
        const names = options?.methods ?? DEFAULT_METHODS;
        // Files under one config share the options array; rebuild the set only when it changes.
        if (names !== methodNames) {
          methodNames = names;
          methods = new Set(names);
        }
      },
      CallExpression(node: ESTree.CallExpression): void {
        const method = statementMethodName(node, methods);
        if (method === null) {
          return;
        }

        const statement = node.arguments[0] === undefined ? undefined : unwrapExpression(node.arguments[0]);
        if (statement === undefined || !looksLikeSql(statement)) {
          return;
        }

        const offenders =
          statement.type === "TemplateLiteral"
            ? runtimeInterpolations(statement)
            : runtimeConcatOperands(statement);

        for (const offender of offenders) {
          context.report({
            node: offender.expression,
            messageId: offender.messageId,
            data: { method },
          });
        }
      },
    };
  },
});
