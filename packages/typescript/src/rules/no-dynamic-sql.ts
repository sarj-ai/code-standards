/**
 * @fileoverview no-dynamic-sql — bind runtime values separately from SQL string literals.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-dynamic-sql.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { sqlSingleQuotedRanges, stripSqlNoise } from "./_sql.js";

type MessageIds = "dynamicSql";

export interface RuleOptions {
  readonly methods?: readonly string[];
}

type Options = readonly [RuleOptions?];

export const NO_DYNAMIC_SQL_DOCUMENTATION = {
  summary: "Disallow runtime values embedded inside quoted SQL values passed to statement-execution methods.",
  rationale:
    "Embedding runtime values in SQL bypasses driver parameterization and can introduce injection defects or unstable query plans.",
  remediation: "Use SQL placeholders and pass runtime values through the driver's binding API.",
  category: "security",
  limitations: [
    "Only single-quoted SQL values are inspected. Double-quoted identifiers, comments, dollar strings, and unquoted fragments are excluded; this is not a general SQL injection detector.",
    "Literal fragments, legacy uppercase fragment names, and parameterizing tagged templates are exempt; uppercase spelling does not prove a value is static.",
    "The bounded lexer recognizes doubled quotes, comments, and PostgreSQL dollar strings; dialect-specific escape modes and SQL generated through other APIs require separate security review.",
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
  if (expression.type === AST_NODE_TYPES.TemplateLiteral) {
    return expression.expressions.length === 0;
  }
  return false;
}

/** Runtime expressions visibly embedded inside a quoted SQL value. */
function runtimeInterpolations(
  template: TSESTree.TemplateLiteral,
): TSESTree.Expression[] {
  const parts = template.quasis.map((quasi) => quasi.value.cooked ?? quasi.value.raw);
  const ranges = sqlSingleQuotedRanges(parts.join(RUNTIME_MARKER));
  let offset = 0;
  return template.expressions.filter(
    (expression, index) => {
      offset += (parts[index]?.length ?? 0);
      const inValue = ranges.some(([start, end]) => start < offset && offset < end);
      offset += RUNTIME_MARKER.length;
      return inValue && !isStaticFragment(expression) &&
        endsWithSqlQuote(parts[index] ?? "") && startsWithSqlQuote(parts[index + 1] ?? "");
    },
  );
}

function endsWithSqlQuote(text: string): boolean {
  return /'\s*$/u.test(text);
}

function startsWithSqlQuote(text: string): boolean {
  return /^\s*'/u.test(text);
}

function staticLiteralText(node: TSESTree.Expression): string | undefined {
  if (node.type === AST_NODE_TYPES.Literal && typeof node.value === "string") {
    return node.value;
  }
  if (
    node.type === AST_NODE_TYPES.TemplateLiteral &&
    node.expressions.length === 0
  ) {
    return node.quasis[0]?.value.raw;
  }
  return undefined;
}

function runtimeConcatOperands(node: TSESTree.Node): TSESTree.Expression[] {
  if (node.type !== AST_NODE_TYPES.BinaryExpression || node.operator !== "+") {
    return [];
  }
  const operands = concatOperands(node);
  const hasStringLiteral = operands.some(
    (operand) =>
      (operand.type === AST_NODE_TYPES.Literal &&
        typeof operand.value === "string") ||
      (operand.type === AST_NODE_TYPES.TemplateLiteral &&
        operand.expressions.length === 0),
  );
  if (!hasStringLiteral) {
    return [];
  }
  const parts = operands.map((operand) => staticLiteralText(operand) ?? RUNTIME_MARKER);
  const ranges = sqlSingleQuotedRanges(parts.join(""));
  let offset = 0;
  return operands.filter((operand, index) => {
    const inValue = ranges.some(([start, end]) => start < offset && offset < end);
    offset += parts[index]?.length ?? 0;
    if (!inValue) return false;
    if (isStaticFragment(operand)) return false;
    const before = operands[index - 1];
    const after = operands[index + 1];
    return (
      before !== undefined &&
      after !== undefined &&
      endsWithSqlQuote(staticLiteralText(before) ?? "") &&
      startsWithSqlQuote(staticLiteralText(after) ?? "")
    );
  });
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
  documentation: NO_DYNAMIC_SQL_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description: NO_DYNAMIC_SQL_DOCUMENTATION.summary,
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
