/**
 * @fileoverview require-sql-access-class — database I/O belongs to an injected repository or store.
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-sql-access-class.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "moveSqlIntoClass";
type Options = [];

/** Operations that execute immediately when called on a database receiver. */
const DIRECT_EXECUTION_METHODS: ReadonlySet<string> = new Set([
  "all",
  "batch",
  "dump",
  "exec",
  "execute",
  "get",
  "pragma",
  "prepare",
  "query",
  "run",
  "transaction",
]);

/** Explicit query-builder terminals used by Kysely and similar SQL builders. */
const BUILDER_TERMINAL_METHODS: ReadonlySet<string> = new Set([
  "execute",
  "executeQuery",
  "executeTakeFirst",
  "executeTakeFirstOrThrow",
  "stream",
]);

/** Builder roots whose `all`, `get`, or `run` terminal performs the operation. */
const BUILDER_METHODS: ReadonlySet<string> = new Set([
  "delete",
  "insert",
  "select",
  "update",
]);
const BUILDER_SHORT_TERMINALS: ReadonlySet<string> = new Set([
  "all",
  "get",
  "run",
]);

/** Prisma model delegates execute at these terminal methods. */
const MODEL_EXECUTION_METHODS: ReadonlySet<string> = new Set([
  "aggregate",
  "count",
  "create",
  "createMany",
  "createManyAndReturn",
  "delete",
  "deleteMany",
  "findFirst",
  "findFirstOrThrow",
  "findMany",
  "findUnique",
  "findUniqueOrThrow",
  "groupBy",
  "update",
  "updateMany",
  "updateManyAndReturn",
  "upsert",
]);

const DATABASE_NAMES = /^(?:db|database|connection|pool|prisma|query|transaction|tx)$/iu;

export const REQUIRE_SQL_ACCESS_CLASS_DOCUMENTATION = {
  summary: "Keep SQL reads and writes inside a class that receives its database dependency.",
  rationale:
    "Free-function database access hides connection ownership and makes transaction, retry, observability, and test boundaries inconsistent.",
  remediation:
    "Move the query into a repository or store class and inject the pool, connection, transaction, or typed database binding through its constructor.",
  category: "architecture",
  limitations: [
    "The rule recognizes conventional database receiver names, Cloudflare DB bindings, direct pool.query calls, explicit query-builder terminals, and Prisma-style model delegates; unusually named or heavily aliased clients require architectural review.",
    "Query construction without a recognized execution terminal is intentionally not reported.",
    "Constructor injection inherited from a base class or transformed through a wrapper is not inferred by this syntax-only rule.",
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

function isDatabaseOperation(
  method: string,
  receiver: TSESTree.Expression,
): boolean {
  if (DIRECT_EXECUTION_METHODS.has(method) && databaseReceiver(receiver))
    return true;
  if (!expressionHasDatabaseMarker(receiver)) return false;
  if (
    BUILDER_TERMINAL_METHODS.has(method) ||
    MODEL_EXECUTION_METHODS.has(method)
  ) return true;
  return BUILDER_SHORT_TERMINALS.has(method) && expressionCallsBuilder(receiver);
}

function databaseReceiver(node: TSESTree.Expression): boolean {
  if (node.type === AST_NODE_TYPES.Identifier)
    return DATABASE_NAMES.test(node.name);
  if (node.type !== AST_NODE_TYPES.MemberExpression) return false;
  const name = memberName(node);
  return name === "DB" || (name !== null && DATABASE_NAMES.test(name));
}

function databaseRootMember(node: TSESTree.Expression): string | null {
  let current = node;
  for (;;) {
    if (current.type === AST_NODE_TYPES.ChainExpression) {
      current = current.expression;
      continue;
    }
    if (
      current.type === AST_NODE_TYPES.TSAsExpression ||
      current.type === AST_NODE_TYPES.TSNonNullExpression ||
      current.type === AST_NODE_TYPES.TSTypeAssertion
    ) {
      current = current.expression;
      continue;
    }
    if (current.type === AST_NODE_TYPES.CallExpression) {
      if (current.callee.type !== AST_NODE_TYPES.MemberExpression) return null;
      current = current.callee.object;
      continue;
    }
    if (current.type === AST_NODE_TYPES.MemberExpression) {
      if (current.object.type === AST_NODE_TYPES.ThisExpression)
        return memberName(current);
      current = current.object;
      continue;
    }
    return current.type === AST_NODE_TYPES.Identifier ? current.name : null;
  }
}

function expressionHasDatabaseMarker(node: TSESTree.Expression): boolean {
  let current: TSESTree.Expression = node;
  for (;;) {
    if (current.type === AST_NODE_TYPES.ChainExpression) {
      current = current.expression;
      continue;
    }
    if (
      current.type === AST_NODE_TYPES.TSAsExpression ||
      current.type === AST_NODE_TYPES.TSNonNullExpression ||
      current.type === AST_NODE_TYPES.TSTypeAssertion
    ) {
      current = current.expression;
      continue;
    }
    if (current.type === AST_NODE_TYPES.CallExpression) {
      if (current.callee.type !== AST_NODE_TYPES.MemberExpression) return false;
      current = current.callee.object;
      continue;
    }
    if (current.type === AST_NODE_TYPES.MemberExpression) {
      const name = memberName(current);
      if (name === "DB" || (name !== null && DATABASE_NAMES.test(name)))
        return true;
      current = current.object;
      continue;
    }
    return current.type === AST_NODE_TYPES.Identifier && DATABASE_NAMES.test(current.name);
  }
}

function expressionCallsBuilder(node: TSESTree.Expression): boolean {
  let current: TSESTree.Expression = node;
  for (;;) {
    if (current.type === AST_NODE_TYPES.ChainExpression) {
      current = current.expression;
      continue;
    }
    if (
      current.type === AST_NODE_TYPES.TSAsExpression ||
      current.type === AST_NODE_TYPES.TSNonNullExpression ||
      current.type === AST_NODE_TYPES.TSTypeAssertion
    ) {
      current = current.expression;
      continue;
    }
    if (current.type === AST_NODE_TYPES.CallExpression) {
      if (current.callee.type !== AST_NODE_TYPES.MemberExpression) return false;
      const name = memberName(current.callee);
      if (name !== null && BUILDER_METHODS.has(name)) return true;
      current = current.callee.object;
      continue;
    }
    if (current.type !== AST_NODE_TYPES.MemberExpression) return false;
    current = current.object;
  }
}

function owningClass(
  node: TSESTree.Node,
): TSESTree.ClassDeclaration | TSESTree.ClassExpression | null {
  let current = node.parent;
  while (current != null) {
    if (
      current.type === AST_NODE_TYPES.ClassDeclaration ||
      current.type === AST_NODE_TYPES.ClassExpression
    )
      return current;
    current = current.parent;
  }
  return null;
}

function injectedMembers(
  owner: TSESTree.ClassDeclaration | TSESTree.ClassExpression,
): ReadonlySet<string> {
  const injected = new Set<string>();
  const constructor = owner.body.body.find(
    (member): member is TSESTree.MethodDefinition =>
      member.type === AST_NODE_TYPES.MethodDefinition &&
      member.kind === "constructor",
  );
  if (constructor === undefined) return injected;
  const parameters = new Set<string>();
  for (const parameter of constructor.value.params) {
    for (const name of parameterNames(parameter)) parameters.add(name);
    if (parameter.type !== AST_NODE_TYPES.TSParameterProperty) continue;
    const value = parameter.parameter.type === AST_NODE_TYPES.AssignmentPattern
      ? parameter.parameter.left
      : parameter.parameter;
    if (value.type === AST_NODE_TYPES.Identifier) injected.add(value.name);
  }
  const body = constructor.value.body;
  if (body === null) return injected;
  for (const statement of body.body) {
    if (
      statement.type !== AST_NODE_TYPES.ExpressionStatement ||
      statement.expression.type !== AST_NODE_TYPES.AssignmentExpression ||
      statement.expression.operator !== "="
    ) continue;
    const { left, right } = statement.expression;
    if (left.type !== AST_NODE_TYPES.MemberExpression) continue;
    const target = thisRootMember(left);
    if (target === null) continue;
    const source = right.type === AST_NODE_TYPES.Identifier
      ? right.name
      : right.type === AST_NODE_TYPES.MemberExpression &&
          right.object.type === AST_NODE_TYPES.Identifier
        ? right.object.name
        : null;
    if (source !== null && parameters.has(source)) injected.add(target);
  }
  return injected;
}

function thisRootMember(node: TSESTree.Expression): string | null {
  let current = node;
  let root: string | null = null;
  while (current.type === AST_NODE_TYPES.MemberExpression) {
    const name = memberName(current);
    if (name === null) return null;
    root = name;
    current = current.object;
  }
  return current.type === AST_NODE_TYPES.ThisExpression ? root : null;
}

function parameterNames(parameter: TSESTree.Parameter): ReadonlySet<string> {
  let value = parameter;
  if (value.type === AST_NODE_TYPES.TSParameterProperty) value = value.parameter;
  if (value.type === AST_NODE_TYPES.AssignmentPattern) value = value.left;
  if (value.type === AST_NODE_TYPES.Identifier) return new Set([value.name]);
  if (value.type !== AST_NODE_TYPES.ObjectPattern) return new Set();
  return new Set(
    value.properties.flatMap((property) => {
      if (property.type === AST_NODE_TYPES.RestElement)
        return property.argument.type === AST_NODE_TYPES.Identifier
          ? [property.argument.name]
          : [];
      const target = property.value.type === AST_NODE_TYPES.AssignmentPattern
        ? property.value.left
        : property.value;
      return target.type === AST_NODE_TYPES.Identifier ? [target.name] : [];
    }),
  );
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
          node.callee.type !== AST_NODE_TYPES.MemberExpression
        )
          return;
        const method = memberName(node.callee);
        if (
          method === null ||
          !isDatabaseOperation(method, node.callee.object)
        )
          return;
        const owner = owningClass(node);
        if (owner !== null) {
          const root = databaseRootMember(node.callee.object);
          if (root !== null && injectedMembers(owner).has(root)) return;
        }
        context.report({ node, messageId: "moveSqlIntoClass" });
      },
    };
  },
});
