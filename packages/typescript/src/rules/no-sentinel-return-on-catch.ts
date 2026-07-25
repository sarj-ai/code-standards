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
 *
 * The same swallow is available in promise form — `await load().catch(() => [])`
 * — where there is no `CatchClause` at all, so it is handled separately below.
 * The promise path is deliberately NARROWER: it fires only on an EMPTY
 * COLLECTION (`[]`, `{}`), the shape that is genuinely indistinguishable from a
 * successful empty read. `.catch(() => null)` / `.catch(() => undefined)` is the
 * idiomatic optional lookup and is left alone. It consults the same shared log
 * matcher, so a handler that logs the error before degrading is exempt exactly
 * as the `CatchClause` path is.
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

type MessageIds = "noSentinelReturn" | "noSentinelCatchHandler";
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

/** True when a parameter pattern binds `name` (plain, default, rest, or destructured). */
function bindsName(param: TSESTree.Node, name: string): boolean {
  switch (param.type) {
    case AST_NODE_TYPES.Identifier:
      return param.name === name;
    case AST_NODE_TYPES.AssignmentPattern:
      return bindsName(param.left, name);
    case AST_NODE_TYPES.RestElement:
      return bindsName(param.argument, name);
    case AST_NODE_TYPES.ArrayPattern:
      return param.elements.some(
        (element) => element !== null && bindsName(element, name),
      );
    case AST_NODE_TYPES.ObjectPattern:
      return param.properties.some((property) =>
        property.type === AST_NODE_TYPES.RestElement
          ? bindsName(property.argument, name)
          : bindsName(property.value, name),
      );
    default:
      return false;
  }
}

/**
 * Does `node`'s subtree READ the identifier `name`?
 *
 * "Read" means a VALUE position. A bare name match is not enough, and getting
 * that wrong silently guts the rule. Walking the whole argument subtree (so a
 * structured logger's meta object counts as reporting the error) cost 8 of 18
 * true positives when measured against the previous release, because all of
 * these matched on name alone:
 *
 *   logCounter({ error: 1 })                // object KEY — a counter, not a log
 *   captureMetric({ tags: { e: 1 } })       // nested key
 *   reportStatus(response.err)              // member PROPERTY of another object
 *   logAll(items.map((error) => error.id))  // a param that merely SHADOWS it
 *
 * Each of those swallows the error while looking "logged". Non-computed property
 * keys and non-computed member properties are therefore skipped, and a nested
 * function that rebinds the name is not descended into.
 */
function subtreeReadsName(node: TSESTree.Node, name: string): boolean {
  let found = false;

  /** True when this function rebinds `name`, so its body reads a different value. */
  const shadowsName = (fn: TSESTree.Node): boolean =>
    isFunctionNode(fn) &&
    (fn as unknown as { params: TSESTree.Parameter[] }).params.some((param) =>
      bindsName(param, name),
    );

  const recurse = (current: TSESTree.Node): void => {
    if (found) {
      return;
    }
    if (current.type === AST_NODE_TYPES.Identifier && current.name === name) {
      found = true;
      return;
    }
    if (shadowsName(current)) {
      return;
    }
    for (const key of Object.keys(current)) {
      if (key === "parent") {
        continue;
      }
      // `{ error: 1 }` — the key names a field; it does not read the binding.
      if (
        key === "key" &&
        current.type === AST_NODE_TYPES.Property &&
        !current.computed
      ) {
        continue;
      }
      // `response.err` — the property names a field on some other object.
      if (
        key === "property" &&
        current.type === AST_NODE_TYPES.MemberExpression &&
        !current.computed
      ) {
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

/** Any function-valued node usable as a `.catch()` handler. */
type CatchHandler =
  | TSESTree.ArrowFunctionExpression
  | TSESTree.FunctionExpression;

/**
 * The handler passed to a promise `.catch(fn)`, or null when this is not a
 * promise catch with an inline function. An inline function is required: a
 * named handler (`.catch(onError)`) is reviewable on its own terms.
 */
function promiseCatchHandler(
  node: TSESTree.CallExpression,
): CatchHandler | null {
  const callee = node.callee;
  if (
    callee.type !== AST_NODE_TYPES.MemberExpression ||
    callee.computed ||
    callee.property.type !== AST_NODE_TYPES.Identifier ||
    callee.property.name !== "catch"
  ) {
    return null;
  }
  const handler = node.arguments[0];
  if (
    handler === undefined ||
    (handler.type !== AST_NODE_TYPES.ArrowFunctionExpression &&
      handler.type !== AST_NODE_TYPES.FunctionExpression)
  ) {
    return null;
  }
  return handler;
}

/**
 * True for an empty collection literal — `[]` or `{}`. Only these are flagged on
 * the promise path: an empty collection returned from a failed read is
 * indistinguishable from a successful empty read, whereas `null`/`undefined` is
 * the idiomatic "not found".
 */
function isEmptyCollection(node: TSESTree.Node | null | undefined): boolean {
  if (node === null || node === undefined) {
    return false;
  }
  if (node.type === AST_NODE_TYPES.ArrayExpression) {
    return node.elements.length === 0;
  }
  if (node.type === AST_NODE_TYPES.ObjectExpression) {
    return node.properties.length === 0;
  }
  return false;
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
      noSentinelCatchHandler:
        "`.catch(() => [])` reports a failed read as an empty result, so callers cannot tell an outage from 'nothing to do'. Log the error and rethrow, or return an explicit failure value.",
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

    /**
     * The node to report for a `.catch()` handler that swallows into an empty
     * collection, or null when the handler does something real. Covers both the
     * expression body (`() => []`) and the block body whose last statement
     * returns the sentinel. Lives inside `create` because the log/report
     * exemption needs the per-invocation shared log matcher.
     */
    function swallowingHandlerTarget(
      handler: CatchHandler,
    ): TSESTree.Node | null {
      if (handler.body.type !== AST_NODE_TYPES.BlockStatement) {
        return isEmptyCollection(handler.body) ? handler.body : null;
      }

      const statements = handler.body.body;
      const last = statements[statements.length - 1];
      if (last === undefined || last.type !== AST_NODE_TYPES.ReturnStatement) {
        return null;
      }
      if (!isEmptyCollection(last.argument)) {
        return null;
      }
      if (containsThrow(handler.body)) {
        return null;
      }

      const caughtName =
        handler.params[0]?.type === AST_NODE_TYPES.Identifier
          ? handler.params[0].name
          : null;
      if (logsOrReportsError(handler.body, caughtName)) {
        return null;
      }
      // A comment documents a deliberate, reviewed swallow.
      if (context.sourceCode.getCommentsInside(handler.body).length > 0) {
        return null;
      }
      return last;
    }

    return {
      CallExpression(node: TSESTree.CallExpression): void {
        const handler = promiseCatchHandler(node);
        if (handler === null) {
          return;
        }
        const target = swallowingHandlerTarget(handler);
        if (target !== null) {
          context.report({ node: target, messageId: "noSentinelCatchHandler" });
        }
      },
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
