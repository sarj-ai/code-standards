/**
 * @fileoverview no-dynamic-sql — a runtime value interpolated into statement text is SQL injection, and it defeats the prepared-statement cache.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-dynamic-sql.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { stripSqlNoise } from "./_sql.js";

type MessageIds = "dynamicSql";

export interface RuleOptions {
  readonly methods?: readonly string[];
}

type Options = readonly [RuleOptions?];

export const noDynamicSqlDocumentation = {
  summary: "Disallow runtime interpolation or concatenation in SQL passed to statement-execution methods.",
  rationale:
    "Embedding runtime values in SQL bypasses driver parameterization and can introduce injection defects or unstable query plans.",
  remediation: "Use SQL placeholders and pass runtime values through the driver's binding API.",
  category: "security",
  limitations: [
    "The rule recognizes SQL by syntax and configured method names; static fragments and parameterizing tagged templates are exempt.",
  ],
  examples: [
    {
      id: "bound-sql-parameter",
      title: "A runtime value is bound separately",
      outcome: "no-match",
      files: [{ path: "src/users.ts", source: "db.prepare('select * from users where id = ?').bind(userId);" }],
      focusPath: "src/users.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "interpolated-sql-value",
      title: "A runtime value is interpolated into SQL",
      outcome: "match",
      files: [{ path: "src/users.ts", source: "db.prepare(`select * from users where id = '${userId}'`);" }],
      focusPath: "src/users.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

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

function concatOperands(node: TSESTree.Expression): TSESTree.Expression[] {
  if (node.type === AST_NODE_TYPES.BinaryExpression && node.operator === "+") {
    return [...concatOperands(node.left), ...concatOperands(node.right)];
  }
  return [node];
}

const SQL_STATEMENT_RE =
  /\b(?:select\s|insert\s+into\b|insert\s+or\b|update\s+\w|delete\s+from\b|replace\s+into\b|merge\s+into\b|upsert\s+into\b|create\s+(?:temp(?:orary)?\s+)?(?:table|index|view|trigger|schema|database)\b|alter\s+table\b|drop\s+(?:table|index|view|trigger)\b|truncate\s+table\b|pragma\s+\w|with\s+\w+\s+as\s*\(|from\s+\w+\s+where\b)/i;

/** The marker a non-static operand contributes to the reconstructed statement text. */
const RUNTIME_MARKER = " ? ";

/** True when the statement argument reads as SQL rather than as a shell command line. */
function looksLikeSql(node: TSESTree.Node): boolean {
  return SQL_STATEMENT_RE.test(stripSqlNoise(staticStatementText(node)));
}

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
  documentation: noDynamicSqlDocumentation,
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow runtime interpolation or concatenation in SQL passed to statement-execution methods.",
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
