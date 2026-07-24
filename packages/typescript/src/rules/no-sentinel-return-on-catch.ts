/**
 * @fileoverview Disallow silently swallowing an error in a `catch` clause by
 * returning a "sentinel" empty value as the final/only statement.
 *
 * A `catch` block whose last statement is `return null` / `return undefined` /
 * `return false` / `return []` / `return {}` (and which never `throw`s) discards
 * the caught error entirely. Downstream callers can't distinguish a genuine
 * empty result from a failure, which is a frequent source of silent data loss
 * and broken idempotency decisions.
 *
 * This rule is deliberately conservative — it prefers false negatives over
 * false positives. It does NOT flag:
 *   - catch blocks that `throw`/rethrow anywhere in their body,
 *   - returns of a computed/meaningful value (calls, identifiers, member
 *     expressions, non-empty literals),
 *   - `return 0` / `return ""`, which are often legitimate results,
 *   - catches that LOG or REPORT the caught error before the sentinel return —
 *     a `console.*`/logger call, a project-declared free logging function (the
 *     shared `logFunctions` option), or an error-reporting call that mentions
 *     the caught binding ANYWHERE in its arguments. The binding search walks the
 *     whole argument subtree, because structured loggers take a meta object:
 *     `logEvent("x", { error: err instanceof Error ? err.message : String(err) })`
 *     reports the error just as surely as `report(err)` does. Here the sentinel
 *     is a deliberate degraded return, not a silent swallow.
 *   - the typed-optional / safe-parse / predicate shape: the try body returns an
 *     expression whose subtree contains a parse-style call that throws on bad
 *     input (`JSON.parse(x)`, `new URL(s).protocol === "https:"`, or a lone
 *     `await request.json()`), or the enclosing function is a declared predicate
 *     (`: boolean`) or returns the same sentinel kind on a normal path. Here the
 *     sentinel is the declared contract.
 *
 * The predicate exemption is deliberately limited to a declared `boolean` return
 * type. A declared `T | null` / `T | undefined` return does NOT exempt: hiding a
 * failure behind a nullable accessor is the exact true positive this rule
 * exists for, and exempting it would gut the rule.
 */

import {
  ESLintUtils,
  type TSESTree,
  AST_NODE_TYPES,
} from "@typescript-eslint/utils";

import {
  createLogMatcher,
  calleeName,
  LOGGING_OPTION_PROPERTIES,
  type LoggingOptions,
  REPORT_NAME_RE,
} from "./_logging.js";

type MessageIds = "noSentinelReturn";
type Options = readonly [LoggingOptions?];

type SentinelKind = "nullish" | "boolean" | "array" | "object" | "string";

/** The sentinel "kind" of a returned expression, or null if not a sentinel. */
function sentinelKind(arg: TSESTree.Expression | null): SentinelKind | null {
  if (arg === null) {
    return null;
  }
  if (arg.type === AST_NODE_TYPES.Literal) {
    if (arg.value === null) {
      return "nullish";
    }
    if (typeof arg.value === "boolean") {
      return "boolean";
    }
    if (typeof arg.value === "string") {
      return "string";
    }
    return null;
  }
  if (arg.type === AST_NODE_TYPES.Identifier && arg.name === "undefined") {
    return "nullish";
  }
  if (arg.type === AST_NODE_TYPES.ArrayExpression) {
    return "array";
  }
  if (arg.type === AST_NODE_TYPES.ObjectExpression) {
    return "object";
  }
  return null;
}

/** Whether a returned expression is one of the swallowing sentinels we flag. */
function isSentinelArgument(arg: TSESTree.Expression | null): boolean {
  if (arg === null) {
    return false;
  }
  if (arg.type === AST_NODE_TYPES.Literal && arg.value === null) {
    return true;
  }
  if (arg.type === AST_NODE_TYPES.Literal && arg.value === false) {
    return true;
  }
  if (arg.type === AST_NODE_TYPES.Identifier && arg.name === "undefined") {
    return true;
  }
  if (arg.type === AST_NODE_TYPES.ArrayExpression && arg.elements.length === 0) {
    return true;
  }
  if (
    arg.type === AST_NODE_TYPES.ObjectExpression &&
    arg.properties.length === 0
  ) {
    return true;
  }
  return false;
}

function isFunctionNode(node: TSESTree.Node): boolean {
  return (
    node.type === AST_NODE_TYPES.FunctionDeclaration ||
    node.type === AST_NODE_TYPES.FunctionExpression ||
    node.type === AST_NODE_TYPES.ArrowFunctionExpression
  );
}

function isNode(value: unknown): value is TSESTree.Node {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { type?: unknown }).type === "string"
  );
}

/**
 * Walk `node`'s subtree applying `visit`, but do not descend into nested
 * function scopes — their statements don't run synchronously for the current
 * catch. Stops early once `visit` returns true.
 */
function walkWithinScope(
  node: TSESTree.Node,
  visit: (current: TSESTree.Node) => boolean,
): boolean {
  let found = false;

  const recurse = (current: TSESTree.Node): void => {
    if (found) {
      return;
    }
    if (visit(current)) {
      found = true;
      return;
    }
    if (isFunctionNode(current)) {
      return;
    }
    for (const key of Object.keys(current)) {
      if (key === "parent") {
        continue;
      }
      const value = (current as unknown as Record<string, unknown>)[key];
      if (Array.isArray(value)) {
        for (const child of value) {
          if (isNode(child)) {
            recurse(child);
          }
        }
      } else if (isNode(value)) {
        recurse(value);
      }
    }
  };

  recurse(node);
  return found;
}

/** Does this subtree throw (ignoring nested function scopes)? */
function containsThrow(node: TSESTree.Node): boolean {
  return walkWithinScope(
    node,
    (current) => current.type === AST_NODE_TYPES.ThrowStatement,
  );
}

/** Does `node`'s subtree read the identifier `name`? */
function subtreeReadsName(node: TSESTree.Node, name: string): boolean {
  let found = false;

  const recurse = (current: TSESTree.Node): void => {
    if (found) {
      return;
    }
    if (current.type === AST_NODE_TYPES.Identifier && current.name === name) {
      found = true;
      return;
    }
    for (const key of Object.keys(current)) {
      if (key === "parent") {
        continue;
      }
      const value = (current as unknown as Record<string, unknown>)[key];
      if (Array.isArray(value)) {
        for (const child of value) {
          if (isNode(child)) {
            recurse(child);
          }
        }
      } else if (isNode(value)) {
        recurse(value);
      }
    }
  };

  recurse(node);
  return found;
}

/**
 * Does the caught-error binding appear ANYWHERE in a call's arguments? The whole
 * argument subtree is searched, not just top-level positional args: a structured
 * logger takes the error nested in a meta object or behind a conditional
 * (`logEvent("x", { error: err instanceof Error ? err.message : String(err) })`),
 * and that reports the error exactly as `report(err)` does.
 */
function argsIncludeBinding(
  args: readonly TSESTree.CallExpressionArgument[],
  caughtName: string | null,
): boolean {
  if (caughtName === null) {
    return false;
  }
  return args.some((arg) => subtreeReadsName(arg, caughtName));
}

/** The try block guarded by this catch. */
function tryBlockOf(catchNode: TSESTree.CatchClause): TSESTree.BlockStatement {
  return catchNode.parent.block;
}

/** Constructors that throw on malformed input. */
const SAFE_PARSE_CONSTRUCTORS: ReadonlySet<string> = new Set([
  "RegExp",
  "URL",
  "URLPattern",
]);

/**
 * A parse-style call that throws on bad input: `JSON.parse(x)`, `YAML.parse(x)`,
 * `new RegExp(x)`, `new URL(x)`.
 */
function isParseShapedNode(node: TSESTree.Node): boolean {
  if (
    node.type === AST_NODE_TYPES.CallExpression &&
    node.callee.type === AST_NODE_TYPES.MemberExpression &&
    !node.callee.computed &&
    node.callee.property.type === AST_NODE_TYPES.Identifier
  ) {
    return node.callee.property.name === "parse";
  }
  if (
    node.type === AST_NODE_TYPES.NewExpression &&
    node.callee.type === AST_NODE_TYPES.Identifier
  ) {
    return SAFE_PARSE_CONSTRUCTORS.has(node.callee.name);
  }
  return false;
}

/** Body-decoding methods of a `Request` / `Response` — they throw on bad input. */
const BODY_DECODE_METHODS: ReadonlySet<string> = new Set([
  "json",
  "text",
  "arrayBuffer",
]);

function isBodyDecodeNode(node: TSESTree.Node): boolean {
  return (
    node.type === AST_NODE_TYPES.CallExpression &&
    node.callee.type === AST_NODE_TYPES.MemberExpression &&
    !node.callee.computed &&
    node.callee.property.type === AST_NODE_TYPES.Identifier &&
    BODY_DECODE_METHODS.has(node.callee.property.name)
  );
}

/**
 * True when a return statement's argument SUBTREE contains a match. The whole
 * subtree is searched rather than the top node alone, because the parse is
 * usually consumed in place: `return new URL(s).protocol === "https:"` is a
 * `BinaryExpression`, not a `NewExpression`, and `return await request.json()`
 * is an `AwaitExpression`. Nested function scopes are not searched — a parse
 * inside a callback does not run when the `try` does.
 */
function returnsMatching(
  stmt: TSESTree.Node,
  predicate: (node: TSESTree.Node) => boolean,
): boolean {
  return (
    stmt.type === AST_NODE_TYPES.ReturnStatement &&
    stmt.argument !== null &&
    walkWithinScope(stmt.argument, predicate)
  );
}

/** The declared return type annotation of the nearest enclosing function, or null. */
function enclosingReturnTypeNode(
  node: TSESTree.Node,
): TSESTree.TypeNode | null {
  let current: TSESTree.Node | undefined | null = node.parent;
  while (current !== undefined && current !== null) {
    if (isFunctionNode(current) && "returnType" in current) {
      return current.returnType?.typeAnnotation ?? null;
    }
    current = current.parent;
  }
  return null;
}

/**
 * True when the enclosing function is a DECLARED predicate — annotated
 * `: boolean` (or `: Promise<boolean>`) — and the catch returns `false`. A
 * boolean return type cannot carry error information at all, so "return a typed
 * Result" is not advice that applies; the sentinel IS the whole contract. Only
 * `boolean` qualifies: a declared `T | null` return is the shape this rule
 * exists to flag and must keep firing.
 */
function isDeclaredBooleanPredicate(
  catchNode: TSESTree.CatchClause,
  kind: SentinelKind,
): boolean {
  if (kind !== "boolean") {
    return false;
  }
  let declared = enclosingReturnTypeNode(catchNode);
  if (
    declared?.type === AST_NODE_TYPES.TSTypeReference &&
    declared.typeName.type === AST_NODE_TYPES.Identifier &&
    declared.typeName.name === "Promise"
  ) {
    declared = declared.typeArguments?.params[0] ?? null;
  }
  return declared?.type === AST_NODE_TYPES.TSBooleanKeyword;
}

/**
 * Does the try body return a safe-parse-style expression?
 *
 * `JSON.parse` / `new RegExp` / `new URL` count from anywhere in the try body —
 * a read-then-parse (`const t = read(p); return JSON.parse(t)`) is still the
 * safe-parse contract. A body-decoding method (`.json()`) counts ONLY when it is
 * the try's sole statement, so `try { return await request.json() }` is exempt
 * while `try { const res = await fetch(url); return await res.json() }` is not:
 * there the catch also swallows the network failure, which is the true positive.
 */
function tryReturnsSafeParse(catchNode: TSESTree.CatchClause): boolean {
  const tryBlock = tryBlockOf(catchNode);
  if (
    walkWithinScope(tryBlock, (current) =>
      returnsMatching(current, isParseShapedNode),
    )
  ) {
    return true;
  }
  const only = tryBlock.body.length === 1 ? tryBlock.body[0] : undefined;
  return only !== undefined && returnsMatching(only, isBodyDecodeNode);
}

/** The nearest enclosing function body, or null. */
function enclosingFunctionBody(
  node: TSESTree.Node,
): TSESTree.BlockStatement | null {
  let current: TSESTree.Node | undefined | null = node.parent;
  while (current !== undefined && current !== null) {
    if (
      isFunctionNode(current) &&
      "body" in current &&
      isNode(current.body) &&
      current.body.type === AST_NODE_TYPES.BlockStatement
    ) {
      return current.body;
    }
    current = current.parent;
  }
  return null;
}

/**
 * True when the enclosing function returns the same sentinel kind on a normal
 * (non-catch) path — a boolean predicate, a `T | undefined` accessor, etc. —
 * so the catch sentinel is the declared contract, not a swallow. Returns inside
 * the flagged catch itself are excluded.
 */
function functionReturnsSameSentinelKindElsewhere(
  catchNode: TSESTree.CatchClause,
  kind: SentinelKind,
): boolean {
  const functionBody = enclosingFunctionBody(catchNode);
  if (functionBody === null) {
    return false;
  }
  return walkWithinScope(functionBody, (current) => {
    if (current.type !== AST_NODE_TYPES.ReturnStatement) {
      return false;
    }
    if (isWithin(current, catchNode.body)) {
      return false;
    }
    return sentinelKind(current.argument) === kind;
  });
}

/** Is `node` inside `ancestor`'s subtree? */
function isWithin(node: TSESTree.Node, ancestor: TSESTree.Node): boolean {
  let current: TSESTree.Node | undefined | null = node;
  while (current !== undefined && current !== null) {
    if (current === ancestor) {
      return true;
    }
    current = current.parent;
  }
  return false;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-sentinel-return-on-catch",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow swallowing a caught error by returning an empty sentinel (`null`, `undefined`, `false`, `[]`, `{}`) as the final statement of a `catch` block, unless the error is logged/reported or the sentinel is the declared safe-parse/predicate contract.",
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: { ...LOGGING_OPTION_PROPERTIES },
      },
    ],
    messages: {
      noSentinelReturn:
        "This `catch` block swallows the error by returning an empty sentinel without logging it. Rethrow it, log/report it, or return a typed Result.",
    },
  },
  defaultOptions: [{}],
  create(context, [loggingOptions]) {
    const matcher = createLogMatcher(loggingOptions);

    /**
     * Does the catch body log or report the caught error before the sentinel
     * return? Either a logging call (logger receiver or a declared
     * `logFunctions` free function), or an error-reporting call whose name
     * matches `REPORT_NAME_RE` and whose arguments mention the caught binding.
     */
    function logsOrReportsError(
      catchBody: TSESTree.BlockStatement,
      caughtName: string | null,
    ): boolean {
      return walkWithinScope(catchBody, (current) => {
        if (current.type !== AST_NODE_TYPES.CallExpression) {
          return false;
        }
        if (matcher.isLoggingCall(current)) {
          return true;
        }
        const name = calleeName(current.callee);
        return (
          name !== null &&
          REPORT_NAME_RE.test(name) &&
          argsIncludeBinding(current.arguments, caughtName)
        );
      });
    }

    return {
      CatchClause(node: TSESTree.CatchClause): void {
        const body = node.body.body;
        if (body.length === 0) {
          return;
        }

        const last = body[body.length - 1];
        if (last === undefined || last.type !== AST_NODE_TYPES.ReturnStatement) {
          return;
        }

        if (!isSentinelArgument(last.argument)) {
          return;
        }

        if (containsThrow(node.body)) {
          return;
        }

        const caughtName =
          node.param?.type === AST_NODE_TYPES.Identifier
            ? node.param.name
            : null;

        if (logsOrReportsError(node.body, caughtName)) {
          return;
        }

        if (tryReturnsSafeParse(node)) {
          return;
        }

        const kind = sentinelKind(last.argument);
        if (kind !== null && isDeclaredBooleanPredicate(node, kind)) {
          return;
        }

        if (
          kind !== null &&
          functionReturnsSameSentinelKindElsewhere(node, kind)
        ) {
          return;
        }

        context.report({
          node: last,
          messageId: "noSentinelReturn",
        });
      },
    };
  },
});
