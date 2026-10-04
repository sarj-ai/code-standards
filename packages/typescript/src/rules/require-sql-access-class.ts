/**
 * @fileoverview require-sql-access-class — database I/O belongs to an injected repository or store.
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-sql-access-class.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


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
  defaultLevel: "warning",
  summary: "Keep SQL reads and writes inside a class that receives its database dependency.",
  rationale:
    "An injected repository class is the preferred ownership boundary for database access under this architectural policy; free functions can also express explicit dependencies.",
  remediation:
    "Move the query into a repository or store class and inject the pool, connection, transaction, or typed database binding through its constructor.",
  category: "architecture",
  limitations: [
    "The rule recognizes conventional database receiver names, Cloudflare DB bindings, direct pool.query calls, explicit query-builder terminals, and Prisma-style model delegates; unusually named or heavily aliased clients require architectural review.",
    "Query construction without a recognized execution terminal is intentionally not reported.",
    "Stable local Map, WeakMap, and URLSearchParams instances are excluded. Other conventional receiver names are heuristics, not proof of a database API.",
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

function memberName(node: ESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === "Identifier")
    return node.property.name;
  if (
    node.computed &&
    node.property.type === "Literal" &&
    typeof node.property.value === "string"
  )
    return node.property.value;
  return null;
}

function isDatabaseOperation(
  method: string,
  receiver: ESTree.Expression,
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

function databaseReceiver(node: ESTree.Expression): boolean {
  if (node.type === "Identifier")
    return DATABASE_NAMES.test(node.name);
  if (node.type !== "MemberExpression") return false;
  const name = memberName(node);
  return name === "DB" || (name !== null && DATABASE_NAMES.test(name));
}

function databaseRootMember(node: ESTree.Expression): string | null {
  let current = node;
  for (;;) {
    if (current.type === "ChainExpression") {
      current = current.expression;
      continue;
    }
    if (
      current.type === "TSAsExpression" ||
      current.type === "TSNonNullExpression" ||
      current.type === "TSTypeAssertion"
    ) {
      current = current.expression;
      continue;
    }
    if (current.type === "CallExpression") {
      if (current.callee.type !== "MemberExpression") return null;
      current = current.callee.object;
      continue;
    }
    if (current.type === "MemberExpression") {
      if (current.object.type === "ThisExpression")
        return memberName(current);
      current = current.object;
      continue;
    }
    return current.type === "Identifier" ? current.name : null;
  }
}

function expressionHasDatabaseMarker(node: ESTree.Expression): boolean {
  let current: ESTree.Expression = node;
  for (;;) {
    if (current.type === "ChainExpression") {
      current = current.expression;
      continue;
    }
    if (
      current.type === "TSAsExpression" ||
      current.type === "TSNonNullExpression" ||
      current.type === "TSTypeAssertion"
    ) {
      current = current.expression;
      continue;
    }
    if (current.type === "CallExpression") {
      if (current.callee.type !== "MemberExpression") return false;
      current = current.callee.object;
      continue;
    }
    if (current.type === "MemberExpression") {
      const name = memberName(current);
      if (name === "DB" || (name !== null && DATABASE_NAMES.test(name)))
        return true;
      current = current.object;
      continue;
    }
    return current.type === "Identifier" && DATABASE_NAMES.test(current.name);
  }
}

function expressionCallsBuilder(node: ESTree.Expression): boolean {
  let current: ESTree.Expression = node;
  for (;;) {
    if (current.type === "ChainExpression") {
      current = current.expression;
      continue;
    }
    if (
      current.type === "TSAsExpression" ||
      current.type === "TSNonNullExpression" ||
      current.type === "TSTypeAssertion"
    ) {
      current = current.expression;
      continue;
    }
    if (current.type === "CallExpression") {
      if (current.callee.type !== "MemberExpression") return false;
      const name = memberName(current.callee);
      if (name !== null && BUILDER_METHODS.has(name)) return true;
      current = current.callee.object;
      continue;
    }
    if (current.type !== "MemberExpression") return false;
    current = current.object;
  }
}

function owningClass(
  node: ESTree.Node,
): ESTree.Class | null {
  let current = node.parent;
  while (current != null) {
    if (
      current.type === "ClassDeclaration" ||
      current.type === "ClassExpression"
    )
      return current;
    current = current.parent;
  }
  return null;
}

function injectedMembers(
  owner: ESTree.Class,
): ReadonlySet<string> {
  const injected = new Set<string>();
  const constructor = owner.body.body.find(
    (member): member is ESTree.MethodDefinition =>
      member.type === "MethodDefinition" &&
      member.kind === "constructor",
  );
  if (constructor === undefined) return injected;
  const parameters = new Set<string>();
  for (const parameter of constructor.value.params) {
    for (const name of parameterNames(parameter)) parameters.add(name);
    if (parameter.type !== "TSParameterProperty") continue;
    const value = parameter.parameter.type === "AssignmentPattern"
      ? parameter.parameter.left
      : parameter.parameter;
    if (value.type === "Identifier") injected.add(value.name);
  }
  const body = constructor.value.body;
  if (body === null) return injected;
  function collectInjectedMember(statement: ESTree.Statement): void {
    if (
      statement.type !== "ExpressionStatement" ||
      statement.expression.type !== "AssignmentExpression" ||
      statement.expression.operator !== "="
    ) return;
    const { left, right } = statement.expression;
    if (left.type !== "MemberExpression") return;
    const target = thisRootMember(left);
    if (target === null) return;
    const source = right.type === "Identifier"
      ? right.name
      : right.type === "MemberExpression" &&
        right.object.type === "Identifier"
        ? right.object.name
        : null;
    if (source !== null && parameters.has(source)) injected.add(target);
  }

  for (const statement of body.body) { collectInjectedMember(statement); }
  return injected;
}

function thisRootMember(node: ESTree.Expression): string | null {
  let current = node;
  let root: string | null = null;
  while (current.type === "MemberExpression") {
    const name = memberName(current);
    if (name === null) return null;
    root = name;
    current = current.object;
  }
  return current.type === "ThisExpression" ? root : null;
}

function parameterNames(parameter: ESTree.ParamPattern): ReadonlySet<string> {
  let value = parameter;
  if (value.type === "TSParameterProperty") value = value.parameter;
  if (value.type === "AssignmentPattern") value = value.left;
  if (value.type === "Identifier") return new Set([value.name]);
  if (value.type !== "ObjectPattern") return new Set();
  return new Set(
    value.properties.flatMap((property) => {
      if (property.type === "RestElement")
        return property.argument.type === "Identifier"
          ? [property.argument.name]
          : [];
      const target = property.value.type === "AssignmentPattern"
        ? property.value.left
        : property.value;
      return target.type === "Identifier" ? [target.name] : [];
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
      isTestFile(sourceOrigin(context).filename) ||
      isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)
    )
      return {};
    function knownNonDatabase(node: ESTree.Node, seen = new Set<ESTree.Node>()): boolean {
      if (seen.has(node)) return false;
      seen.add(node);
      if (node.type === "Identifier") {
        const binding = findVariable(context.sourceCode.getScope(node), node.name);
        if (binding?.defs.length !== 1 || binding.references.some((reference) => reference.isWrite() && reference.init !== true)) return false;
        const definition = binding.defs[0];
        return definition?.type === "Variable" && definition.node.type === "VariableDeclarator" && definition.node.init !== null && knownNonDatabase(definition.node.init, seen);
      }
      return node.type === "NewExpression" && node.callee.type === "Identifier" &&
        ["Map", "WeakMap", "URLSearchParams"].includes(node.callee.name) &&
        (findVariable(context.sourceCode.getScope(node.callee), node.callee.name)?.defs.length ?? 0) === 0;
    }
    return {
      CallExpression(node): void {
        if (
          node.callee.type !== "MemberExpression"
        )
          return;
        const method = memberName(node.callee);
        if (knownNonDatabase(node.callee.object)) return;
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
