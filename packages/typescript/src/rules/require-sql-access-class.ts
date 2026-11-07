/**
 * @fileoverview require-sql-access-class — keep SQL reads and writes inside an injected-dependency class.
 *
 * Port of the 18.x `require-sql-access-class` rule. The rule is untyped,
 * so the port covers all of it.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";

const NAME = "require-sql-access-class";

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

const NON_DATABASE_CONSTRUCTORS: ReadonlySet<string> = new Set(["Map", "WeakMap", "URLSearchParams"]);

const DATABASE_NAMES = /^(?:db|database|connection|pool|prisma|query|transaction|tx)$/iu;

function isDatabaseOperation(
  method: string,
  receiver: Node,
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

function databaseReceiver(node: Node): boolean {
  node = unwrapExpression(node);
  if (node.type === "Identifier")
    return DATABASE_NAMES.test(node.name);
  if (node.type !== "MemberExpression") return false;
  const name = getPropertyName(node);
  return name === "DB" || (name !== null && DATABASE_NAMES.test(name));
}

function databaseRootMember(node: Node): string | null {
  let current = node;
  for (;;) {
    current = unwrapExpression(current);
    if (current.type === "ChainExpression") {
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
        return getPropertyName(current);
      current = current.object;
      continue;
    }
    return current.type === "Identifier" ? current.name : null;
  }
}

function expressionHasDatabaseMarker(node: Node): boolean {
  let current: Node = node;
  for (;;) {
    current = unwrapExpression(current);
    if (current.type === "ChainExpression") {
      current = current.expression;
      continue;
    }
    if (current.type === "CallExpression") {
      if (current.callee.type !== "MemberExpression") return false;
      current = current.callee.object;
      continue;
    }
    if (current.type === "MemberExpression") {
      const name = getPropertyName(current);
      if (name === "DB" || (name !== null && DATABASE_NAMES.test(name)))
        return true;
      current = current.object;
      continue;
    }
    return current.type === "Identifier" && DATABASE_NAMES.test(current.name);
  }
}

function expressionCallsBuilder(node: Node): boolean {
  let current: Node = node;
  for (;;) {
    current = unwrapExpression(current);
    if (current.type === "ChainExpression") {
      current = current.expression;
      continue;
    }
    if (current.type === "CallExpression") {
      if (current.callee.type !== "MemberExpression") return false;
      const name = getPropertyName(current.callee);
      if (name !== null && BUILDER_METHODS.has(name)) return true;
      current = current.callee.object;
      continue;
    }
    if (current.type !== "MemberExpression") return false;
    current = current.object;
  }
}

function owningClass(node: Node): ESTree.Class | null {
  for (let current = parentOf(node); current !== null; current = parentOf(current)) {
    if (current.type === "ClassDeclaration" || current.type === "ClassExpression") return current;
  }
  return null;
}

function injectedMembers(
  owner: ESTree.Class,
): ReadonlySet<string> {
  const injected = new Set<string>();
  const constructor = owner.body.body.find(
    (member) =>
      member.type === "MethodDefinition" &&
      member.kind === "constructor",
  );
  if (constructor?.type !== "MethodDefinition") return injected;
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

function thisRootMember(node: Node): string | null {
  let current = node;
  let root: string | null = null;
  while (current.type === "MemberExpression") {
    const name = getPropertyName(current);
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

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Keep SQL reads and writes inside a class that receives its database dependency.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      moveSqlIntoClass:
        "Move this database operation into a repository or store class with an injected connection or pool.",
    },
  },
  createOnce(context) {
    function knownNonDatabase(node: Node, seen = new Set<Node>()): boolean {
      if (seen.has(node)) return false;
      seen.add(node);
      if (node.type === "Identifier") {
        const binding = findVariable(context.sourceCode.getScope(node), node.name);
        if (binding?.defs.length !== 1 || binding.references.some((reference) => reference.isWrite() && reference.init !== true)) return false;
        const definition = binding.defs[0];
        if (definition?.type !== "Variable") return false;
        const init = (definition.node as ESTree.VariableDeclarator).init;
        return init !== null && knownNonDatabase(init, seen);
      }
      if (node.type !== "NewExpression") return false;
      const callee = unwrapExpression(node.callee);
      return callee.type === "Identifier" && NON_DATABASE_CONSTRUCTORS.has(callee.name) &&
        (findVariable(context.sourceCode.getScope(callee), callee.name)?.defs.length ?? 0) === 0;
    }
    return {
      before() {
        const file = { filename: context.filename, cwd: context.cwd };
        if (isTestFile(file) || isGeneratedFile(file, context.sourceCode.text)) return false;
        return undefined;
      },
      CallExpression(node): void {
        const callee = unwrapExpression(node.callee);
        if (callee.type !== "MemberExpression") return;
        const method = getPropertyName(callee);
        // The syntactic test runs first: the scope lookup is the expensive check.
        if (method === null || !isDatabaseOperation(method, callee.object) || knownNonDatabase(callee.object)) return;
        const owner = owningClass(node);
        if (owner !== null) {
          const root = databaseRootMember(callee.object);
          if (root !== null && injectedMembers(owner).has(root)) return;
        }
        context.report({ node, messageId: "moveSqlIntoClass" });
      },
    };
  },
});
