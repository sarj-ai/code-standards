/**
 * @fileoverview no-sentinel-return-on-catch — a `catch` returning `null` / `[]` / `{}` discards the error, so callers cannot tell empty from failed.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-sentinel-return-on-catch.test.ts
 */

import { type TSESTree, AST_NODE_TYPES } from "@typescript-eslint/utils";

import {
  createLogMatcher,
  calleeName,
  LOGGING_OPTION_PROPERTIES,
  type LoggingOptions,
  REPORT_NAME_RE,
} from "./_logging.js";
import { createRule } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

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
 * Does `node`'s subtree READ the identifier `name`, in a VALUE position?
 *
 * A bare name match is not enough: an object key, a nested key, a member
 * property of another object and a parameter that merely shadows the name all
 * swallow the error while looking "logged". So non-computed property keys and
 * non-computed member properties are skipped, and a nested function that
 * rebinds the name is not descended into. Each shape has a case in the tests.
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
 * Function names that declare a boolean contract as clearly as a `: boolean`
 * annotation does. TypeScript INFERS the return type of
 * `async function isDirectory(d: string) { try { … } catch { return false } }`,
 * so demanding the annotation made the predicate exemption depend on a style
 * choice rather than on the contract.
 */
const PREDICATE_NAME_RE = /^(is|has|can|should|must|does|did|was|were|are)[A-Z]/;
const PREDICATE_SUFFIX_RE = /(Exists?|Available|Enabled|Disabled)$/;

/** The name of the nearest enclosing function, or null for an anonymous one. */
function enclosingFunctionName(node: TSESTree.Node): string | null {
  let current: TSESTree.Node | undefined | null = node.parent;
  while (current !== undefined && current !== null) {
    if (isFunctionNode(current)) {
      if (
        "id" in current &&
        isNode(current.id) &&
        current.id.type === AST_NODE_TYPES.Identifier
      ) {
        return current.id.name;
      }
      const parent = current.parent;
      if (
        parent?.type === AST_NODE_TYPES.VariableDeclarator &&
        parent.id.type === AST_NODE_TYPES.Identifier
      ) {
        return parent.id.name;
      }
      return null;
    }
    current = current.parent;
  }
  return null;
}

/**
 * True when the enclosing function's NAME declares it a predicate and the catch
 * returns a boolean. Same reasoning as `isDeclaredBooleanPredicate`, applied to
 * the (very common) unannotated spelling.
 */
function isNamedBooleanPredicate(
  catchNode: TSESTree.CatchClause,
  kind: SentinelKind,
): boolean {
  if (kind !== "boolean") {
    return false;
  }
  const name = enclosingFunctionName(catchNode);
  return (
    name !== null &&
    (PREDICATE_NAME_RE.test(name) || PREDICATE_SUFFIX_RE.test(name))
  );
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

/** Does the try body return a safe-parse-style expression? */
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
    return returnedSentinelKinds(current.argument).has(kind);
  });
}

/**
 * The sentinel kinds a returned expression can evaluate to. A bare sentinel
 * yields one; a ternary or a `??` / `||` fallback yields the kinds of its
 * branches, because `return valid ? value : false` puts `false` on a NORMAL
 * path just as plainly as `return false` does.
 */
function returnedSentinelKinds(
  arg: TSESTree.Expression | null,
): ReadonlySet<SentinelKind> {
  const kinds = new Set<SentinelKind>();
  if (arg === null) {
    return kinds;
  }
  const direct = sentinelKind(arg);
  if (direct !== null) {
    kinds.add(direct);
    return kinds;
  }
  if (arg.type === AST_NODE_TYPES.ConditionalExpression) {
    for (const branch of [arg.consequent, arg.alternate]) {
      for (const nested of returnedSentinelKinds(branch)) {
        kinds.add(nested);
      }
    }
  } else if (
    arg.type === AST_NODE_TYPES.LogicalExpression &&
    (arg.operator === "??" || arg.operator === "||")
  ) {
    for (const nested of returnedSentinelKinds(arg.right)) {
      kinds.add(nested);
    }
  }
  return kinds;
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

export default createRule<Options, MessageIds>({
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
    if (isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }

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
        if (kind !== null && isNamedBooleanPredicate(node, kind)) {
          return;
        }

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
