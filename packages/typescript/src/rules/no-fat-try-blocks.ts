/**
 * @fileoverview no-fat-try-blocks — a `try` holding more than three throwing statements catches failures its handler was never written for.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-fat-try-blocks.test.ts
 */

import { type TSESTree, AST_NODE_TYPES } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "fatTryBlock";
type Options = readonly [];

const MAX_TRY_BODY_STATEMENTS = 3;

const NESTED_FUNCTION_TYPES: ReadonlySet<AST_NODE_TYPES> = new Set([
  AST_NODE_TYPES.FunctionDeclaration,
  AST_NODE_TYPES.FunctionExpression,
  AST_NODE_TYPES.ArrowFunctionExpression,
]);

/** Pure method names must not overlap common I/O-client methods such as `get`, `set`, or `find`. */
const PURE_METHODS: ReadonlySet<string> = new Set([
  "map", "filter", "forEach", "reduce", "reduceRight", "findIndex",
  "findLast", "findLastIndex", "some", "every", "push", "pop", "shift",
  "unshift", "slice", "splice", "concat", "flat", "flatMap", "join", "reverse",
  "sort", "fill", "includes", "indexOf", "lastIndexOf", "at", "toString",
  "toLocaleString", "valueOf", "charAt", "charCodeAt", "codePointAt", "split",
  "padStart", "padEnd", "repeat", "trim", "trimStart", "trimEnd", "toUpperCase",
  "toLowerCase", "toFixed", "toPrecision", "startsWith", "endsWith",
]);

/** Pure collection methods that synchronously execute function arguments. */
const SYNC_CALLBACK_METHODS: ReadonlySet<string> = new Set([
  "every", "filter", "findIndex", "findLast", "findLastIndex", "flatMap",
  "forEach", "map", "reduce", "reduceRight", "some", "sort",
]);

/** Non-throwing global namespaces called as `X.method(...)`. */
const PURE_NAMESPACES: ReadonlySet<string> = new Set([
  "Object", "Array", "Math", "JSON", "Number", "String", "Boolean", "console",
]);

/** Namespace exceptions that commonly throw; `JSON.stringify` remains a deliberate recall tradeoff. */
const IMPURE_NAMESPACE_METHODS: ReadonlySet<string> = new Set(["JSON.parse"]);

/** Constructors that do not throw on construction. */
const PURE_CONSTRUCTORS: ReadonlySet<string> = new Set([
  "Map", "Set", "WeakMap", "WeakSet", "Date", "Error", "TypeError",
  "RangeError", "Array", "Object", "Headers", "URLSearchParams", "FormData",
  "TextEncoder", "TextDecoder", "Blob", "ReadableStream", "WritableStream",
  "TransformStream", "Response", "AbortController",
]);

function isNode(value: unknown): value is TSESTree.Node {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { type?: unknown }).type === "string"
  );
}

/** A call whose value is a known pure, non-throwing helper. */
function isPureCall(node: TSESTree.CallExpression): boolean {
  const callee = node.callee;
  if (callee.type !== AST_NODE_TYPES.MemberExpression) {
    return false;
  }
  const property = callee.property;
  if (property.type !== AST_NODE_TYPES.Identifier) {
    return false;
  }
  if (
    callee.object.type === AST_NODE_TYPES.Identifier &&
    PURE_NAMESPACES.has(callee.object.name)
  ) {
    return !IMPURE_NAMESPACE_METHODS.has(`${callee.object.name}.${property.name}`);
  }
  return (
    PURE_METHODS.has(property.name) &&
    (!SYNC_CALLBACK_METHODS.has(property.name) || !synchronousCallbackCanThrow(node))
  );
}

function synchronousCallbackCanThrow(node: TSESTree.CallExpression): boolean {
  return node.arguments.some((argument) => {
    if (
      argument.type !== AST_NODE_TYPES.ArrowFunctionExpression &&
      argument.type !== AST_NODE_TYPES.FunctionExpression
    ) return false;
    if (argument.async) return false;
    return subtreeMatches(
      argument.body,
      (current) =>
        current.type === AST_NODE_TYPES.ThrowStatement ||
        (current.type === AST_NODE_TYPES.CallExpression &&
          current.callee.type === AST_NODE_TYPES.MemberExpression &&
          !current.callee.computed &&
          current.callee.object.type === AST_NODE_TYPES.Identifier &&
          current.callee.object.name === "JSON" &&
          current.callee.property.type === AST_NODE_TYPES.Identifier &&
          current.callee.property.name === "parse"),
    );
  });
}

function isPureNew(node: TSESTree.NewExpression): boolean {
  return (
    node.callee.type === AST_NODE_TYPES.Identifier &&
    PURE_CONSTRUCTORS.has(node.callee.name)
  );
}

function subtreeMatches(
  stmt: TSESTree.Node,
  predicate: (node: TSESTree.Node) => boolean,
  descendIntoFunctions = false,
): boolean {
  let found = false;

  const visit = (current: TSESTree.Node): void => {
    if (found) {
      return;
    }
    if (predicate(current)) {
      found = true;
      return;
    }
    for (const key of Object.keys(current)) {
      if (key === "parent") {
        continue;
      }
      if (
        !descendIntoFunctions &&
        NESTED_FUNCTION_TYPES.has(current.type) &&
        key === "body"
      ) {
        continue;
      }
      const value = (current as unknown as Record<string, unknown>)[key];
      if (Array.isArray(value)) {
        for (const child of value) {
          if (isNode(child)) {
            visit(child);
          }
        }
      } else if (isNode(value)) {
        visit(value);
      }
      if (found) {
        return;
      }
    }
  };

  visit(stmt);
  return found;
}

/** Unwrap `await` / optional-chain / non-null wrappers to the core expression. */
function unwrap(expr: TSESTree.Expression): TSESTree.Expression {
  let current = expr;
  while (
    current.type === AST_NODE_TYPES.ChainExpression ||
    current.type === AST_NODE_TYPES.TSNonNullExpression
  ) {
    current = current.expression;
  }
  return current;
}

/** `await` and used calls count; bare calls do not, including inside blocks and branches. */
function canThrow(stmt: TSESTree.Statement): boolean {
  if (hasAwait(stmt)) {
    return true;
  }
  if (isBareCallStatement(stmt)) {
    return false;
  }
  if (stmt.type === AST_NODE_TYPES.BlockStatement) {
    return stmt.body.some(canThrow);
  }
  if (stmt.type === AST_NODE_TYPES.IfStatement) {
    return (
      hasThrowingCallOrNew(stmt.test) ||
      canThrow(stmt.consequent) ||
      (stmt.alternate !== null && canThrow(stmt.alternate))
    );
  }
  return hasThrowingCallOrNew(stmt);
}

const hasAwait = (node: TSESTree.Node): boolean =>
  subtreeMatches(node, (n) => n.type === AST_NODE_TYPES.AwaitExpression);

const hasThrowingCallOrNew = (node: TSESTree.Node): boolean =>
  subtreeMatches(
    node,
    (n) =>
      (n.type === AST_NODE_TYPES.CallExpression && !isPureCall(n)) ||
      (n.type === AST_NODE_TYPES.NewExpression && !isPureNew(n)),
  );

/** A bare fire-and-forget call statement — `toast("done");`, `logEvent(...);`. */
function isBareCallStatement(stmt: TSESTree.Statement): boolean {
  return (
    stmt.type === AST_NODE_TYPES.ExpressionStatement &&
    unwrap(stmt.expression).type === AST_NODE_TYPES.CallExpression
  );
}

function handlerRethrows(handler: TSESTree.CatchClause | null): boolean {
  if (handler === null) {
    return false;
  }
  const body = handler.body.body;
  const last = body[body.length - 1];
  return last !== undefined && last.type === AST_NODE_TYPES.ThrowStatement;
}

/** Statements that hand control straight through to their own parent. */
const PASS_THROUGH_PARENTS: ReadonlySet<AST_NODE_TYPES> = new Set([
  AST_NODE_TYPES.IfStatement,
  AST_NODE_TYPES.TryStatement,
  AST_NODE_TYPES.CatchClause,
  AST_NODE_TYPES.LabeledStatement,
]);

/** A member property / object key spelled `x` is not a reference to `x`. */
function isPropertyName(node: TSESTree.Identifier): boolean {
  const parent = node.parent;
  if (parent.type === AST_NODE_TYPES.MemberExpression) {
    return parent.property === node && !parent.computed;
  }
  if (parent.type === AST_NODE_TYPES.Property) {
    return parent.key === node && !parent.computed;
  }
  return false;
}

/** `null`, `undefined`, `false`, `void 0`, `[]`, `{}` — a success-shaped value. */
function isSuccessShapedValue(expr: TSESTree.Expression): boolean {
  let current: TSESTree.Expression = expr;
  while (
    current.type === AST_NODE_TYPES.TSAsExpression ||
    current.type === AST_NODE_TYPES.TSNonNullExpression
  ) {
    current = current.expression;
  }
  if (current.type === AST_NODE_TYPES.Literal) {
    return current.value === null || current.value === false;
  }
  if (current.type === AST_NODE_TYPES.Identifier) {
    return current.name === "undefined";
  }
  if (current.type === AST_NODE_TYPES.UnaryExpression) {
    return current.operator === "void";
  }
  if (current.type === AST_NODE_TYPES.ArrayExpression) {
    return current.elements.length === 0;
  }
  if (current.type === AST_NODE_TYPES.ObjectExpression) {
    return current.properties.length === 0;
  }
  return false;
}

/** Exempt terminal boundaries that propagate the caught error without fabricating success. */
function isTerminalErrorBoundary(node: TSESTree.TryStatement): boolean {
  const handler = node.handler;
  return (
    handler !== null &&
    isTerminalInFunction(node) &&
    handlerEndsByHandingOff(handler) &&
    handlerMentionsCaughtBinding(handler) &&
    !handlerReturnsSuccessShaped(handler)
  );
}

/** A terminal node is last through every enclosing block up to its function, without a loop or switch. */
function isTerminalInFunction(node: TSESTree.Node): boolean {
  let current: TSESTree.Node = node;
  let parent: TSESTree.Node | undefined = current.parent;

  while (parent !== undefined) {
    if (parent.type === AST_NODE_TYPES.BlockStatement) {
      if (parent.body[parent.body.length - 1] !== current) {
        return false;
      }
    } else if (parent.type === AST_NODE_TYPES.Program) {
      return parent.body[parent.body.length - 1] === current;
    } else if (NESTED_FUNCTION_TYPES.has(parent.type)) {
      return true;
    } else if (!PASS_THROUGH_PARENTS.has(parent.type)) {
      return false;
    }
    current = parent;
    parent = current.parent;
  }
  return false;
}

/** A propagating handler ends with `return`, `throw`, or a bare call. */
function handlerEndsByHandingOff(handler: TSESTree.CatchClause): boolean {
  const body = handler.body.body;
  const last = body[body.length - 1];
  if (last === undefined) {
    return false;
  }
  if (
    last.type === AST_NODE_TYPES.ReturnStatement ||
    last.type === AST_NODE_TYPES.ThrowStatement
  ) {
    return true;
  }
  return (
    last.type === AST_NODE_TYPES.ExpressionStatement &&
    unwrapAwait(last.expression).type === AST_NODE_TYPES.CallExpression
  );
}

/** `await f()` unwrapped to `f()`; everything else unwrapped as usual. */
function unwrapAwait(expr: TSESTree.Expression): TSESTree.Expression {
  const inner = unwrap(expr);
  return inner.type === AST_NODE_TYPES.AwaitExpression
    ? unwrap(inner.argument)
    : inner;
}

/** A boundary must reference its caught error, including through nested callbacks. */
function handlerMentionsCaughtBinding(handler: TSESTree.CatchClause): boolean {
  const names = caughtBindingNames(handler);
  if (names.size === 0) {
    return false;
  }
  return subtreeMatches(
    handler.body,
    (n) =>
      n.type === AST_NODE_TYPES.Identifier &&
      names.has(n.name) &&
      !isPropertyName(n),
    true,
  );
}

function caughtBindingNames(handler: TSESTree.CatchClause): ReadonlySet<string> {
  const names = new Set<string>();
  if (handler.param !== null) {
    collectBindingNames(handler.param, names);
  }
  return names;
}

/** Collect identifiers bound by a catch pattern, excluding type annotations. */
function collectBindingNames(
  pattern: TSESTree.Node,
  names: Set<string>,
): void {
  if (pattern.type === AST_NODE_TYPES.Identifier) {
    names.add(pattern.name);
    return;
  }
  if (pattern.type === AST_NODE_TYPES.ObjectPattern) {
    for (const property of pattern.properties) {
      collectBindingNames(
        property.type === AST_NODE_TYPES.RestElement
          ? property.argument
          : property.value,
        names,
      );
    }
    return;
  }
  if (pattern.type === AST_NODE_TYPES.ArrayPattern) {
    for (const element of pattern.elements) {
      if (element !== null) {
        collectBindingNames(element, names);
      }
    }
    return;
  }
  if (
    pattern.type === AST_NODE_TYPES.AssignmentPattern ||
    pattern.type === AST_NODE_TYPES.RestElement
  ) {
    collectBindingNames(
      pattern.type === AST_NODE_TYPES.AssignmentPattern
        ? pattern.left
        : pattern.argument,
      names,
    );
  }
}

/** Empty or false results hide which operation failed and are not error propagation. */
const handlerReturnsSuccessShaped = (handler: TSESTree.CatchClause): boolean =>
  subtreeMatches(
    handler.body,
    (n) =>
      n.type === AST_NODE_TYPES.ReturnStatement &&
      n.argument !== null &&
      isSuccessShapedValue(n.argument),
  );

export default createRule<Options, MessageIds>({
  name: "no-fat-try-blocks",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow `try` blocks with more than three top-level statements that can throw — isolate the throwing statement and move non-throwing work outside.",
    },
    schema: [],
    messages: {
      fatTryBlock:
        "This `try` block has {{count}} statements that can throw (max {{max}}). Isolate the throwing statement(s); move non-throwing work outside the `try`.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }

    const sourceCode = context.sourceCode;

    return {
      TryStatement(node: TSESTree.TryStatement): void {
        if (node.finalizer !== null) {
          return;
        }
        if (handlerRethrows(node.handler)) {
          return;
        }
        if (isTerminalErrorBoundary(node)) {
          return;
        }

        const count = node.block.body.filter(canThrow).length;
        if (count <= MAX_TRY_BODY_STATEMENTS) {
          return;
        }

        const tryKeyword = sourceCode.getFirstToken(node);
        context.report({
          node: tryKeyword ?? node,
          messageId: "fatTryBlock",
          data: { count, max: MAX_TRY_BODY_STATEMENTS },
        });
      },
    };
  },
});
