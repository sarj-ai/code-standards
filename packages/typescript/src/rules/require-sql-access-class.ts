/**
 * @fileoverview require-sql-access-class — database I/O belongs to an injected repository or store.
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-sql-access-class.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "moveSqlIntoClass";
type Options = [];

const SQL_METHODS: ReadonlySet<string> = new Set([
  "all",
  "batch",
  "delete",
  "dump",
  "exec",
  "execute",
  "get",
  "insert",
  "pragma",
  "prepare",
  "run",
  "select",
  "transaction",
  "update",
]);
const DATABASE_NAMES = /^(?:db|database|connection|pool|query|transaction|tx)$/iu;

export const REQUIRE_SQL_ACCESS_CLASS_DOCUMENTATION = {
  summary: "Keep SQL reads and writes inside a class that receives its database dependency.",
  rationale:
    "Free-function database access hides connection ownership and makes transaction, retry, observability, and test boundaries inconsistent.",
  remediation:
    "Move the query into a repository or store class and inject the pool, connection, transaction, or typed database binding through its constructor.",
  category: "architecture",
  limitations: [
    "The rule recognizes conventional database receiver names and Cloudflare DB bindings; unusually named or heavily aliased clients require architectural review.",
    "Query construction without execution is not reported.",
  ],
  examples: [
    {
      id: "injected-repository",
      title: "Own queries in an injected repository",
      outcome: "no-match",
      files: [
        {
          path: "src/user-repository.ts",
          source:
            "export class UserRepository { constructor(private readonly db: Database.Database) {} find(id: string) { return this.db.prepare('SELECT id FROM user WHERE id = ?').get(id); } }",
        },
      ],
      focusPath: "src/user-repository.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "free-query",
      title: "Do not execute SQL in a free function",
      outcome: "match",
      files: [
        {
          path: "src/users.ts",
          source:
            "export function find(database: Database.Database, id: string) { return database.prepare('SELECT id FROM user WHERE id = ?').get(id); }",
        },
      ],
      focusPath: "src/users.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function memberName(node: TSESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === AST_NODE_TYPES.Identifier)
    return node.property.name;
  if (
    node.computed &&
    node.property.type === AST_NODE_TYPES.Literal &&
    typeof node.property.value === "string"
  )
    return node.property.value;
  return null;
}

function databaseReceiver(node: TSESTree.Expression): boolean {
  if (node.type === AST_NODE_TYPES.Identifier)
    return DATABASE_NAMES.test(node.name);
  if (node.type !== AST_NODE_TYPES.MemberExpression) return false;
  const name = memberName(node);
  return name === "DB" || (name !== null && DATABASE_NAMES.test(name));
}

function belongsToClass(node: TSESTree.Node): boolean {
  let current = node.parent;
  while (current != null) {
    if (
      current.type === AST_NODE_TYPES.ClassDeclaration ||
      current.type === AST_NODE_TYPES.ClassExpression
    )
      return true;
    current = current.parent;
  }
  return false;
}

export default createRule<Options, MessageIds>({
  name: "require-sql-access-class",
  documentation: REQUIRE_SQL_ACCESS_CLASS_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Keep SQL reads and writes inside a class that receives its database dependency.",
    },
    schema: [],
    messages: {
      moveSqlIntoClass:
        "Move this database operation into a repository or store class with an injected connection or pool.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (
      isTestFile(context.filename) ||
      isGeneratedFile(context.filename, context.sourceCode.text)
    )
      return {};
    return {
      CallExpression(node): void {
        if (
          belongsToClass(node) ||
          node.callee.type !== AST_NODE_TYPES.MemberExpression
        )
          return;
        const method = memberName(node.callee);
        if (
          method === null ||
          !SQL_METHODS.has(method) ||
          !databaseReceiver(node.callee.object)
        )
          return;
        context.report({ node, messageId: "moveSqlIntoClass" });
      },
    };
  },
});
