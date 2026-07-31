/**
 * @fileoverview no-dynamic-sql — a runtime value interpolated into statement text is SQL injection, and it defeats the prepared-statement cache.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-dynamic-sql.test.ts
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/no-dynamic-sql.md
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { stripSqlNoise } from "./_sql.js";

type MessageIds = "dynamicSql";

export interface RuleOptions {
  /** Statement-taking method names to inspect. Replaces the defaults. */
  readonly methods?: readonly string[];
}

type Options = readonly [RuleOptions?];

const DEFAULT_METHODS: readonly string[] = ["prepare", "exec", "query"];

/** A module-level constant fragment: `CANDIDATE_COLS`, `TABLE_NAME`. */
const CONSTANT_CASE_RE = /^[A-Z][A-Z0-9_]*$/;

/**
 * True when an interpolated expression is a compile-time SQL fragment rather
 * than runtime data: a CONSTANT_CASE identifier, a member access whose final
 * property is CONSTANT_CASE (`TABLES.USERS`), or a string literal.
 */
function isStaticFragment(expression: TSESTree.Expression): boolean {
  if (expression.type === AST_NODE_TYPES.Identifier) {
    return CONSTANT_CASE_RE.test(expression.name);
  }
  if (
    expression.type === AST_NODE_TYPES.MemberExpression &&
    !expression.computed &&
    expression.property.type === AST_NODE_TYPES.Identifier
  ) {
    return CONSTANT_CASE_RE.test(expression.property.name);
  }
  if (expression.type === AST_NODE_TYPES.Literal) {
    return typeof expression.value === "string";
  }
  return false;
}

/** The interpolated runtime expressions in a template literal. */
function runtimeInterpolations(
  template: TSESTree.TemplateLiteral,
): TSESTree.Expression[] {
  return template.expressions.filter(
    (expression) => !isStaticFragment(expression),
  );
}

/**
 * Flatten a `+` chain into its operands. `"a" + b + "c"` yields three nodes so
 * each can be judged independently.
 */
function concatOperands(node: TSESTree.Expression): TSESTree.Expression[] {
  if (node.type === AST_NODE_TYPES.BinaryExpression && node.operator === "+") {
    return [...concatOperands(node.left), ...concatOperands(node.right)];
  }
  return [node];
}

/**
 * The runtime operands of a string-concatenation chain, or an empty array when
 * the node is not a concatenation that mixes a literal with a runtime value.
 * Requiring at least one string literal is what distinguishes statement
 * building from ordinary arithmetic.
 */
function runtimeConcatOperands(node: TSESTree.Node): TSESTree.Expression[] {
  if (node.type !== AST_NODE_TYPES.BinaryExpression || node.operator !== "+") {
    return [];
  }
  const operands = concatOperands(node);
  const hasStringLiteral = operands.some(
    (operand) =>
      operand.type === AST_NODE_TYPES.Literal &&
      typeof operand.value === "string",
  );
  if (!hasStringLiteral) {
    return [];
  }
  return operands.filter(
    (operand) =>
      operand.type !== AST_NODE_TYPES.Literal && !isStaticFragment(operand),
  );
}

/**
 * A SQL data/DDL statement keyword. `exec` and `query` are generic method names
 * — `child_process.exec` shares them — so the statement text itself has to prove
 * it is SQL before an interpolation into it can be an injection.
 */
const SQL_STATEMENT_RE =
  /\b(?:select\s|insert\s+into\b|insert\s+or\b|update\s+\w|delete\s+from\b|replace\s+into\b|merge\s+into\b|upsert\s+into\b|create\s+(?:temp(?:orary)?\s+)?(?:table|index|view|trigger|schema|database)\b|alter\s+table\b|drop\s+(?:table|index|view|trigger)\b|truncate\s+table\b|pragma\s+\w|with\s+\w+\s+as\s*\(|from\s+\w+\s+where\b)/i;

/** The marker a non-static operand contributes to the reconstructed statement text. */
const RUNTIME_MARKER = " ? ";

/**
 * The statically known text of a statement argument, with every runtime operand
 * replaced by a placeholder. Enough to answer "is this SQL?" for both the
 * template-literal and the `+`-concatenation shape.
 */
function staticStatementText(node: TSESTree.Node): string {
  if (node.type === AST_NODE_TYPES.TemplateLiteral) {
    return node.quasis.map((quasi) => quasi.value.cooked ?? quasi.value.raw).join(RUNTIME_MARKER);
  }
  if (node.type === AST_NODE_TYPES.Literal) {
    return typeof node.value === "string" ? node.value : RUNTIME_MARKER;
  }
  if (node.type === AST_NODE_TYPES.BinaryExpression && node.operator === "+") {
    return staticStatementText(node.left) + staticStatementText(node.right);
  }
  return RUNTIME_MARKER;
}

/** True when the statement argument reads as SQL rather than as a shell command line. */
function looksLikeSql(node: TSESTree.Node): boolean {
  return SQL_STATEMENT_RE.test(stripSqlNoise(staticStatementText(node)));
}

/** The inspected method name of `receiver.method(...)`, or null. */
function statementMethodName(
  node: TSESTree.CallExpression,
  methods: ReadonlySet<string>,
): string | null {
  const callee = node.callee;
  if (
    callee.type !== AST_NODE_TYPES.MemberExpression ||
    callee.computed ||
    callee.property.type !== AST_NODE_TYPES.Identifier
  ) {
    return null;
  }
  const name = callee.property.name;
  return methods.has(name) ? name : null;
}

export default createRule<Options, MessageIds>({
  name: "no-dynamic-sql",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow interpolating or concatenating a runtime value into a SQL statement passed to `prepare`/`exec`/`query`; use a placeholder and bind the value.",
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
        "Runtime value built into a SQL statement passed to `{{method}}()`. Use a `?` placeholder and pass the value through `.bind(...)` so the driver parameterises it.",
    },
  },
  defaultOptions: [{}],
  create(context, [options]) {
    const methods = new Set(options?.methods ?? DEFAULT_METHODS);

    return {
      CallExpression(node: TSESTree.CallExpression): void {
        const method = statementMethodName(node, methods);
        if (method === null) {
          return;
        }

        const statement = node.arguments[0];
        if (statement === undefined || !looksLikeSql(statement)) {
          return;
        }

        const offenders =
          statement.type === AST_NODE_TYPES.TemplateLiteral
            ? runtimeInterpolations(statement)
            : runtimeConcatOperands(statement);

        for (const offender of offenders) {
          context.report({
            node: offender,
            messageId: "dynamicSql",
            data: { method },
          });
        }
      },
    };
  },
});
