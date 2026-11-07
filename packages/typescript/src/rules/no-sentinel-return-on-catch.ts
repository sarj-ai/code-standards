/**
 * @fileoverview no-sentinel-return-on-catch — a `catch` returning `null` / `[]` / `{}` discards the error, so callers cannot tell empty from failed.
 *
 * Port of the 18.x `no-sentinel-return-on-catch` rule. Same algorithm;
 * generated files are skipped and options are read in `before()`, and parents
 * are read with `parentOf()` because Oxlint's `Program.parent` is `null`.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { forEachOwnAstChild, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import {
  calleeName,
  createLogMatcher,
  LOGGING_OPTION_PROPERTIES,
  type LoggingOptions,
  type LogMatcher,
  REPORT_NAME_RE,
} from "../utils/logging.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { enclosingFunction } from "../utils/stable-value-binding.js";

const NAME = "no-sentinel-return-on-catch";

type SentinelKind = "nullish" | "boolean" | "array" | "object" | "string";

/** Peel type-only wrappers while preserving runtime expressions such as `value!`. */
function unwrapSentinelExpression(
  arg: Node | null,
): Node | null {
  let current = arg;
  while (
    current?.type === "TSAsExpression" ||
    current?.type === "TSTypeAssertion" ||
    current?.type === "TSSatisfiesExpression"
  ) {
    current = current.expression;
  }
  return current;
}

/** The sentinel "kind" of a returned expression, or null if not a sentinel. */
function sentinelKind(arg: Node | null): SentinelKind | null {
  const value = unwrapSentinelExpression(arg);
  if (value === null) {
    return null;
  }
  if (value.type === "Literal") {
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
  if (value.type === "Identifier" && value.name === "undefined") {
    return "nullish";
  }
  if (value.type === "ArrayExpression") {
    return "array";
  }
  if (value.type === "ObjectExpression") {
    return "object";
  }
  return null;
}

/** `null`, `false`, `undefined`, `[]` and `{}`: the empty values a swallowing catch returns. */
function isEmptySentinel(value: Node): boolean {
  if (value.type === "Literal") return value.value === null || value.value === false;
  if (value.type === "ArrayExpression") return value.elements.length === 0;
  if (value.type === "ObjectExpression") return value.properties.length === 0;
  return value.type === "Identifier" && value.name === "undefined";
}

function functionNode(node: Node): ESTree.Function | ESTree.ArrowFunctionExpression | null {
  return (
    node.type === "FunctionDeclaration" ||
    node.type === "FunctionExpression" ||
    node.type === "ArrowFunctionExpression"
  ) ? node : null;
}

/** Walk a subtree without entering nested functions, stopping on a match. */
function walkWithinScope(
  node: Node,
  visit: (current: Node) => boolean,
): boolean {
  if (visit(node)) return true;
  return functionNode(node) === null && forEachOwnAstChild(node, (child) => walkWithinScope(child, visit));
}

/** Does this subtree throw (ignoring nested function scopes)? */
function containsThrow(node: Node): boolean {
  return walkWithinScope(
    node,
    (current) => current.type === "ThrowStatement",
  );
}

/** True when a parameter pattern binds `name` (plain, default, rest, or destructured). */
function bindsName(param: Node, name: string): boolean {
  switch (param.type) {
    case "Identifier":
      return param.name === name;
    case "AssignmentPattern":
      return bindsName(param.left, name);
    case "RestElement":
      return bindsName(param.argument, name);
    case "ArrayPattern":
      return param.elements.some(
        (element) => element !== null && bindsName(element, name),
      );
    case "ObjectPattern":
      return param.properties.some((property) =>
        property.type === "RestElement"
          ? bindsName(property.argument, name)
          : bindsName(property.value, name),
      );
    default:
      return false;
  }
}

/** Whether a subtree reads a binding in a value position without shadowing it. */
function subtreeReadsName(node: Node, name: string): boolean {
  if (node.type === "Identifier" && node.name === name) return true;
  // A function that rebinds `name` hides the caught error from its body.
  if (functionNode(node)?.params.some((param) => bindsName(param, name)) === true) return false;
  return forEachOwnAstChild(node, (child) => subtreeReadsName(child, name), (key) => !isNonReadingProperty(node, key));
}

/** Whether a node is a parse-style call or constructor that throws on bad input. */
function isParseShapedNode(node: ESTree.CallExpression | ESTree.NewExpression): boolean {
  const callee = unwrapExpression(node.callee);
  if (node.type === "CallExpression") {
    return callee.type === "MemberExpression" && getPropertyName(callee) === "parse";
  }
  return callee.type === "Identifier" && SAFE_PARSE_CONSTRUCTORS.has(callee.name);
}

/** Constructors that throw on malformed input. */
const SAFE_PARSE_CONSTRUCTORS: ReadonlySet<string> = new Set([
  "RegExp",
  "URL",
  "URLPattern",
]);

function isBodyDecodeNode(node: ESTree.CallExpression | ESTree.NewExpression): boolean {
  if (node.type !== "CallExpression") return false;
  const callee = unwrapExpression(node.callee);
  return callee.type === "MemberExpression" && BODY_DECODE_METHODS.has(getPropertyName(callee) ?? "");
}

/** Pure validation and optional browser-storage reads around JSON parsing. */
function isSafeParseSupportCall(node: ESTree.CallExpression): boolean {
  const callee = unwrapExpression(node.callee);
  if (callee.type !== "MemberExpression") return false;
  const method = getPropertyName(callee);
  if (
    method === "isArray" &&
    callee.object.type === "Identifier" &&
    callee.object.name === "Array"
  ) {
    return true;
  }
  if (method !== "getItem") return false;
  if (
    callee.object.type === "Identifier" &&
    (callee.object.name === "localStorage" ||
      callee.object.name === "sessionStorage")
  ) {
    return true;
  }
  return (
    callee.object.type === "MemberExpression" &&
    callee.object.object.type === "Identifier" &&
    (callee.object.object.name === "window" ||
      callee.object.object.name === "globalThis") &&
    STORAGE_OBJECTS.has(getPropertyName(callee.object) ?? "")
  );
}

const STORAGE_OBJECTS: ReadonlySet<string> = new Set(["localStorage", "sessionStorage"]);

/** Body-decoding methods of a `Request` / `Response` — they throw on bad input. */
const BODY_DECODE_METHODS: ReadonlySet<string> = new Set([
  "json",
  "text",
  "arrayBuffer",
]);

type FunctionNode = ESTree.Function | ESTree.ArrowFunctionExpression;

/** Names that conventionally declare a boolean-returning function. */
const PREDICATE_NAME_RE = /^(is|has|can|should|must|does|did|was|were|are)[A-Z]/;
const PREDICATE_SUFFIX_RE = /(Exists?|Available|Enabled|Disabled)$/;

/** Does the try body contain only deliberate parse/decode operations that may throw? */
function tryReturnsSafeParse(catchNode: ESTree.CatchClause): boolean {
  const tryBlock = tryBlockOf(catchNode);
  let sawSafeParse = false;
  let sawUnsafeOperation = false;

  const recurse = (current: Node): void => {
    if (sawUnsafeOperation || (current !== tryBlock && functionNode(current) !== null)) return;
    if (current.type === "AwaitExpression") {
      if (current.argument.type === "CallExpression" && isBodyDecodeNode(current.argument)) {
        recurse(current.argument);
      } else {
        sawUnsafeOperation = true;
      }
      return;
    }
    if (current.type === "CallExpression" || current.type === "NewExpression") {
      if (isParseShapedNode(current) || isBodyDecodeNode(current)) {
        sawSafeParse = true;
      } else if (
        current.type === "CallExpression" &&
        isSafeParseSupportCall(current)
      ) {
        // Pure support work does not broaden the failure boundary.
      } else {
        sawUnsafeOperation = true;
        return;
      }
    }
    visitChildren(current);
  };

  function visitChildren(current: Node): void {
    forEachOwnAstChild(current, child => {
      recurse(child);
      return sawUnsafeOperation;
    });
  }

  recurse(tryBlock);
  return sawSafeParse && !sawUnsafeOperation;
}

/**
 * `try { throw Error(); } catch (error) { inspect(error.stack); return null; }`
 * deliberately creates an Error to capture the current stack; no operational
 * failure is swallowed. Keep this exemption exact so ordinary caught errors
 * remain visible.
 */
function isIntentionalStackCapture(
  catchNode: ESTree.CatchClause,
  caughtName: string | null,
): boolean {
  if (caughtName === null) return false;
  const tryBody = tryBlockOf(catchNode).body;
  const only = tryBody.length === 1 ? tryBody[0] : undefined;
  if (only?.type !== "ThrowStatement") return false;
  const thrown = unwrapSentinelExpression(only.argument);
  const constructsError =
    (thrown?.type === "CallExpression" ||
      thrown?.type === "NewExpression") &&
    thrown.callee.type === "Identifier" &&
    thrown.callee.name === "Error";
  if (!constructsError) return false;
  return catchNode.body.body
    .slice(0, -1)
    .some((statement) => subtreeReadsName(statement, caughtName));
}

/** The try block guarded by this catch. */
function tryBlockOf(catchNode: ESTree.CatchClause): ESTree.BlockStatement {
  return (parentOf(catchNode) as ESTree.TryStatement).block;
}

/** The catch's own contract: a boolean predicate or a function that also returns this sentinel normally. */
function isSentinelContract(catchNode: ESTree.CatchClause, kind: SentinelKind): boolean {
  const fn = enclosingFunction(catchNode);
  if (fn === null) return false;
  return (kind === "boolean" && (isNamedBooleanPredicate(fn) || isDeclaredBooleanPredicate(fn))) ||
    functionReturnsSameSentinelKindElsewhere(catchNode, fn, kind);
}

/** A predicate-named function may answer `false` from its catch. */
function isNamedBooleanPredicate(fn: FunctionNode): boolean {
  const name = functionName(fn);
  return name !== null && (PREDICATE_NAME_RE.test(name) || PREDICATE_SUFFIX_RE.test(name));
}

/** The function's own name, or the variable it initializes; null for an anonymous one. */
function functionName(fn: FunctionNode): string | null {
  if ("id" in fn && fn.id !== null && fn.id.type === "Identifier") return fn.id.name;
  const parent = parentOf(fn);
  return parent?.type === "VariableDeclarator" && parent.id.type === "Identifier" ? parent.id.name : null;
}

/** A function declared to return `boolean` or `Promise<boolean>` may answer `false` from its catch. */
function isDeclaredBooleanPredicate(fn: FunctionNode): boolean {
  let declared: ESTree.TSType | null = fn.returnType?.typeAnnotation ?? null;
  if (
    declared?.type === "TSTypeReference" &&
    declared.typeName.type === "Identifier" &&
    declared.typeName.name === "Promise"
  ) {
    declared = declared.typeArguments?.params[0] ?? null;
  }
  return declared?.type === "TSBooleanKeyword";
}

/** Whether a normal path returns the same sentinel kind as the catch. */
function functionReturnsSameSentinelKindElsewhere(
  catchNode: ESTree.CatchClause,
  fn: FunctionNode,
  kind: SentinelKind,
): boolean {
  // Empty collections and objects are common successful results but say
  // nothing about whether operational failure may be converted into one.
  if ((kind !== "nullish" && kind !== "boolean") || fn.body?.type !== "BlockStatement") return false;
  return walkWithinScope(fn.body, (current) =>
    current.type === "ReturnStatement" &&
    !isWithin(current, catchNode.body) &&
    returnedSentinelKinds(current.argument).has(kind),
  );
}

/** Sentinel kinds reachable through a direct, ternary, or fallback return. */
function returnedSentinelKinds(
  arg: Node | null,
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
  if (arg.type === "ConditionalExpression") {
    for (const branch of [arg.consequent, arg.alternate]) {
      for (const nested of returnedSentinelKinds(branch)) {
        kinds.add(nested);
      }
    }
  } else if (
    arg.type === "LogicalExpression" &&
    (arg.operator === "??" || arg.operator === "||")
  ) {
    for (const nested of returnedSentinelKinds(arg.right)) {
      kinds.add(nested);
    }
  } else if (arg.type === "ChainExpression") {
    // Optional chaining explicitly models ordinary-path absence as undefined.
    kinds.add("nullish");
  }
  return kinds;
}

/** Is `node` inside `ancestor`'s subtree? */
function isWithin(node: Node, ancestor: Node): boolean {
  let current: Node | null = node;
  while (current !== null) {
    if (current === ancestor) {
      return true;
    }
    current = parentOf(current);
  }
  return false;
}

export default defineRule({
  meta: {
    defaultOptions: [{}],
    type: "problem",
    docs: {
      description:
        "Disallow swallowing a caught error by returning an empty sentinel unless the error is handled or the sentinel is part of the function contract.",
      url: docsUrl(NAME),
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
  createOnce(context) {
    let matcher: LogMatcher;
    // Options arrive per file; rebuild the matcher only when they change.
    let matcherOptions: unknown;

    function logsOrReportsError(
      catchBody: ESTree.BlockStatement,
      caughtName: string | null,
    ): boolean {
      return walkWithinScope(catchBody, (current) =>
        current.type === "CallExpression" &&
        (matcher.isLoggingCall(current) || isReportCall(current)) &&
        (caughtName === null || current.arguments.some((arg) => subtreeReadsName(arg, caughtName))),
      );
    }

    /** The returned sentinel when the catch ends by returning one, or null. */
    function swallowedSentinel(node: ESTree.CatchClause): { last: ESTree.ReturnStatement; kind: SentinelKind } | null {
      const last = node.body.body.at(-1);
      const returned = last?.type === "ReturnStatement" ? unwrapSentinelExpression(last.argument) : null;
      if (last?.type !== "ReturnStatement" || returned === null || !isEmptySentinel(returned)) return null;
      // A locally declared `undefined` is not the undefined value.
      if (returned.type === "Identifier" &&
        (findVariable(context.sourceCode.getScope(returned), returned.name)?.defs.length ?? 0) > 0) return null;
      const kind = sentinelKind(returned);
      return kind === null ? null : { last, kind };
    }

    return {
      before(): boolean | void {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        const [loggingOptions] = context.options as unknown as readonly [LoggingOptions?];
        if (matcher === undefined || loggingOptions !== matcherOptions) {
          matcher = createLogMatcher(loggingOptions);
          matcherOptions = loggingOptions;
        }
      },
      CatchClause(node: ESTree.CatchClause): void {
        const sentinel = swallowedSentinel(node);
        if (sentinel === null || containsThrow(node.body)) return;
        const caughtName = node.param?.type === "Identifier" ? node.param.name : null;
        if (
          logsOrReportsError(node.body, caughtName) ||
          tryReturnsSafeParse(node) ||
          isIntentionalStackCapture(node, caughtName) ||
          isSentinelContract(node, sentinel.kind)
        ) {
          return;
        }
        context.report({
          node: sentinel.last,
          messageId: "noSentinelReturn",
        });
      },
    };
  },
});

/** A call to an error-reporting function such as `reportError(...)` or `Sentry.captureException(...)`. */
function isReportCall(node: ESTree.CallExpression): boolean {
  const name = calleeName(node.callee);
  return name !== null && REPORT_NAME_RE.test(name);
}

function isNonReadingProperty(current: Node, key: string): boolean {
  // `{ error: 1 }` — the key names a field; it does not read the binding.
  if (
    key === "key" &&
    current.type === "Property" &&
    !current.computed
  ) {
    return true;
  }
  // `response.err` — the property names a field on some other object.
  if (
    key === "property" &&
    current.type === "MemberExpression" &&
    !current.computed
  ) {
    return true;
  }
  return false;
}
