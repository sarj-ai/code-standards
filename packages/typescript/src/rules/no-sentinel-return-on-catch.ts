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
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "noSentinelReturn";
type Options = readonly [LoggingOptions?];

export const noSentinelReturnOnCatchDocumentation = {
  summary: "Disallow swallowing a caught error by returning an empty sentinel unless the error is handled or the sentinel is part of the function contract.",
  rationale: "An unreported fallback makes operational failure indistinguishable from a legitimate empty result.",
  remediation: "Rethrow, report the error before returning, or model expected absence with an explicit predicate, safe-parse, or result contract.",
  category: "correctness",
  limitations: ["Recognized predicate, safe-parse, normal-path sentinel, deliberate parse, generated-client, and configured logging patterns are excluded."],
  examples: [
    { id: "reported-fallback", title: "Report an error before returning a fallback", outcome: "no-match", files: [{ path: "src/load.ts", source: "function load() { try { return read(); } catch (error) { logger.warn('load failed', error); return null; } }" }], focusPath: "src/load.ts", expectedCount: 0, public: true },
    { id: "silent-fallback", title: "Do not turn an unreported error into absence", outcome: "match", files: [{ path: "src/load.ts", source: "function load() { try { return read(); } catch { return null; } }" }], focusPath: "src/load.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

type SentinelKind = "nullish" | "boolean" | "array" | "object" | "string";

/** Peel type-only wrappers while preserving runtime expressions such as `value!`. */
function unwrapSentinelExpression(
  arg: TSESTree.Expression | null,
): TSESTree.Expression | null {
  let current = arg;
  while (
    current?.type === AST_NODE_TYPES.TSAsExpression ||
    current?.type === AST_NODE_TYPES.TSTypeAssertion ||
    current?.type === AST_NODE_TYPES.TSSatisfiesExpression
  ) {
    current = current.expression;
  }
  return current;
}

/** The sentinel "kind" of a returned expression, or null if not a sentinel. */
function sentinelKind(arg: TSESTree.Expression | null): SentinelKind | null {
  const value = unwrapSentinelExpression(arg);
  if (value === null) {
    return null;
  }
  if (value.type === AST_NODE_TYPES.Literal) {
    if (value.value === null) {
      return "nullish";
    }
    if (typeof value.value === "boolean") {
      return "boolean";
    }
    if (typeof value.value === "string") {
      return "string";
    }
    return null;
  }
  if (value.type === AST_NODE_TYPES.Identifier && value.name === "undefined") {
    return "nullish";
  }
  if (value.type === AST_NODE_TYPES.ArrayExpression) {
    return "array";
  }
  if (value.type === AST_NODE_TYPES.ObjectExpression) {
    return "object";
  }
  return null;
}

/** Whether a returned expression is one of the swallowing sentinels we flag. */
function isSentinelArgument(arg: TSESTree.Expression | null): boolean {
  const value = unwrapSentinelExpression(arg);
  if (value === null) {
    return false;
  }
  if (value.type === AST_NODE_TYPES.Literal && value.value === null) {
    return true;
  }
  if (value.type === AST_NODE_TYPES.Literal && value.value === false) {
    return true;
  }
  if (value.type === AST_NODE_TYPES.Identifier && value.name === "undefined") {
    return true;
  }
  if (value.type === AST_NODE_TYPES.ArrayExpression && value.elements.length === 0) {
    return true;
  }
  if (
    value.type === AST_NODE_TYPES.ObjectExpression &&
    value.properties.length === 0
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

/** Walk a subtree without entering nested functions, stopping on a match. */
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

/** Whether a subtree reads a binding in a value position without shadowing it. */
function subtreeReadsName(node: TSESTree.Node, name: string): boolean {
  let found = false;

  /** Whether this function rebinds `name`. */
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

/** Whether any call argument reads the caught-error binding. */
function argsIncludeBinding(
  args: readonly TSESTree.CallExpressionArgument[],
  caughtName: string | null,
): boolean {
  if (caughtName === null) {
    return false;
  }
  return args.some((arg) => subtreeReadsName(arg, caughtName));
}

/** Whether a node is a parse-style call or constructor that throws on bad input. */
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

/** Constructors that throw on malformed input. */
const SAFE_PARSE_CONSTRUCTORS: ReadonlySet<string> = new Set([
  "RegExp",
  "URL",
  "URLPattern",
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

/** Body-decoding methods of a `Request` / `Response` — they throw on bad input. */
const BODY_DECODE_METHODS: ReadonlySet<string> = new Set([
  "json",
  "text",
  "arrayBuffer",
]);

/** Whether a return value contains a match outside nested function scopes. */
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

/** Whether an enclosing predicate-named function returns `false` from its catch. */
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

/** Names that conventionally declare a boolean-returning function. */
const PREDICATE_NAME_RE = /^(is|has|can|should|must|does|did|was|were|are)[A-Z]/;
const PREDICATE_SUFFIX_RE = /(Exists?|Available|Enabled|Disabled)$/;

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

/**
 * `try { throw Error(); } catch (error) { inspect(error.stack); return null; }`
 * deliberately creates an Error to capture the current stack; no operational
 * failure is swallowed. Keep this exemption exact so ordinary caught errors
 * remain visible.
 */
function isIntentionalStackCapture(
  catchNode: TSESTree.CatchClause,
  caughtName: string | null,
): boolean {
  if (caughtName === null) return false;
  const tryBody = tryBlockOf(catchNode).body;
  const only = tryBody.length === 1 ? tryBody[0] : undefined;
  if (only?.type !== AST_NODE_TYPES.ThrowStatement) return false;
  const thrown = unwrapSentinelExpression(only.argument);
  const constructsError =
    (thrown?.type === AST_NODE_TYPES.CallExpression ||
      thrown?.type === AST_NODE_TYPES.NewExpression) &&
    thrown.callee.type === AST_NODE_TYPES.Identifier &&
    thrown.callee.name === "Error";
  if (!constructsError) return false;
  return catchNode.body.body
    .slice(0, -1)
    .some((statement) => subtreeReadsName(statement, caughtName));
}

/** The try block guarded by this catch. */
function tryBlockOf(catchNode: TSESTree.CatchClause): TSESTree.BlockStatement {
  return catchNode.parent.block;
}

/** Whether a normal path returns the same sentinel kind as the catch. */
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

/** Sentinel kinds reachable through a direct, ternary, or fallback return. */
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
  documentation: noSentinelReturnOnCatchDocumentation,
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow swallowing a caught error by returning an empty sentinel unless the error is handled or the sentinel is part of the function contract.",
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

        if (isIntentionalStackCapture(node, caughtName)) {
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
