/**
 * @fileoverview no-sentinel-return-on-catch — a `catch` returning `null` / `[]` / `{}` discards the error, so callers cannot tell empty from failed.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-sentinel-return-on-catch.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";
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

export const NO_SENTINEL_RETURN_ON_CATCH_DOCUMENTATION = {
  summary: "Disallow swallowing a caught error by returning an empty sentinel unless the error is handled or the sentinel is part of the function contract.",
  rationale: "An unreported fallback makes operational failure indistinguishable from a legitimate empty result.",
  remediation: "Rethrow, report the error before returning, or model expected absence with an explicit predicate, safe-parse, or result contract.",
  category: "correctness",
  limitations: ["Recognized predicate, safe-parse, normal-path sentinel, deliberate parse, generated-client, and configured logging patterns are excluded. Locally shadowed undefined bindings are not treated as sentinels; recognized handling patterns are not a proof that every control-flow path handles the error."],
  examples: [
    { id: "reported-fallback", title: "Report an error before returning a fallback", outcome: "no-match", files: [{ path: "src/load.ts", source: "function load() { try { return read(); } catch (error) { logger.warn('load failed', error); return null; } }" }], focusPath: "src/load.ts", expectedCount: 0, public: true },
    { id: "silent-fallback", title: "Do not turn an unreported error into absence", outcome: "match", files: [{ path: "src/load.ts", source: "function load() { try { return read(); } catch { return null; } }" }], focusPath: "src/load.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

type SentinelKind = "nullish" | "boolean" | "array" | "object" | "string";

/** Peel type-only wrappers while preserving runtime expressions such as `value!`. */
function unwrapSentinelExpression(
  arg: ESTree.Expression | null,
): ESTree.Expression | null {
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
function sentinelKind(arg: ESTree.Expression | null): SentinelKind | null {
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

/** Whether a returned expression is one of the swallowing sentinels we flag. */
function isSentinelArgument(arg: ESTree.Expression | null): boolean {
  const value = unwrapSentinelExpression(arg);
  if (value === null) {
    return false;
  }
  if (value.type === "Literal" && value.value === null) {
    return true;
  }
  if (value.type === "Literal" && value.value === false) {
    return true;
  }
  if (value.type === "Identifier" && value.name === "undefined") {
    return true;
  }
  if (value.type === "ArrayExpression" && value.elements.length === 0) {
    return true;
  }
  if (
    value.type === "ObjectExpression" &&
    value.properties.length === 0
  ) {
    return true;
  }
  return false;
}

function isFunctionNode(
  node: ESTree.Node,
): node is ESTree.Function | ESTree.ArrowFunctionExpression {
  return (
    node.type === "FunctionDeclaration" ||
    node.type === "FunctionExpression" ||
    node.type === "ArrowFunctionExpression"
  );
}

function isNode(value: unknown): value is ESTree.Node {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { type?: unknown }).type === "string"
  );
}

/** Walk a subtree without entering nested functions, stopping on a match. */
function walkWithinScope(
  node: ESTree.Node,
  visit: (current: ESTree.Node) => boolean,
): boolean {
  let found = false;

  const recurse = (current: ESTree.Node): void => {
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
    forEachOwnAstChild(current, child => {
      recurse(child);
      return found;
    });
  };

  recurse(node);
  return found;
}

/** Does this subtree throw (ignoring nested function scopes)? */
function containsThrow(node: ESTree.Node): boolean {
  return walkWithinScope(
    node,
    (current) => current.type === "ThrowStatement",
  );
}

/** True when a parameter pattern binds `name` (plain, default, rest, or destructured). */
function bindsName(param: ESTree.Node, name: string): boolean {
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
function subtreeReadsName(node: ESTree.Node, name: string): boolean {
  let found = false;

  const recurse = (current: ESTree.Node): void => {
    if (found) {
      return;
    }
    if (current.type === "Identifier" && current.name === name) {
      found = true;
      return;
    }
    if (shadowsName(current)) {
      return;
    }
    forEachOwnAstChild(current, child => {
      recurse(child);
      return found;
    }, key => !isNonReadingProperty(current, key));
  };

  /** Whether this function rebinds `name`. */
  const shadowsName = (fn: ESTree.Node): boolean =>
    isFunctionNode(fn) &&
    fn.params.some((param) =>
      bindsName(param, name),
    );

  recurse(node);
  return found;
}

/** Whether any call argument reads the caught-error binding. */
function argsIncludeBinding(
  args: readonly ESTree.Argument[],
  caughtName: string | null,
): boolean {
  if (caughtName === null) {
    return false;
  }
  return args.some((arg) => subtreeReadsName(arg, caughtName));
}

/** Whether a node is a parse-style call or constructor that throws on bad input. */
function isParseShapedNode(node: ESTree.Node): boolean {
  if (
    node.type === "CallExpression" &&
    node.callee.type === "MemberExpression" &&
    !node.callee.computed &&
    node.callee.property.type === "Identifier"
  ) {
    return node.callee.property.name === "parse";
  }
  if (
    node.type === "NewExpression" &&
    node.callee.type === "Identifier"
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

function isBodyDecodeNode(node: ESTree.Node): boolean {
  return (
    node.type === "CallExpression" &&
    node.callee.type === "MemberExpression" &&
    !node.callee.computed &&
    node.callee.property.type === "Identifier" &&
    BODY_DECODE_METHODS.has(node.callee.property.name)
  );
}

/** Pure validation and optional browser-storage reads around JSON parsing. */
function isSafeParseSupportCall(node: ESTree.CallExpression): boolean {
  const callee = node.callee;
  if (
    callee.type !== "MemberExpression" ||
    callee.computed ||
    callee.property.type !== "Identifier"
  ) {
    return false;
  }
  if (
    callee.property.name === "isArray" &&
    callee.object.type === "Identifier" &&
    callee.object.name === "Array"
  ) {
    return true;
  }
  if (callee.property.name !== "getItem") return false;
  if (
    callee.object.type === "Identifier" &&
    (callee.object.name === "localStorage" ||
      callee.object.name === "sessionStorage")
  ) {
    return true;
  }
  return (
    callee.object.type === "MemberExpression" &&
    !callee.object.computed &&
    callee.object.object.type === "Identifier" &&
    (callee.object.object.name === "window" ||
      callee.object.object.name === "globalThis") &&
    callee.object.property.type === "Identifier" &&
    (callee.object.property.name === "localStorage" ||
      callee.object.property.name === "sessionStorage")
  );
}

/** Body-decoding methods of a `Request` / `Response` — they throw on bad input. */
const BODY_DECODE_METHODS: ReadonlySet<string> = new Set([
  "json",
  "text",
  "arrayBuffer",
]);

/** Whether an enclosing predicate-named function returns `false` from its catch. */
function isNamedBooleanPredicate(
  catchNode: ESTree.CatchClause,
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
function enclosingFunctionName(node: ESTree.Node): string | null {
  let current: ESTree.Node | null | undefined = node.parent;
  while (current != null && current !== null) {
    if (isFunctionNode(current)) {
      if (
        "id" in current &&
        isNode(current.id) &&
        current.id.type === "Identifier"
      ) {
        return current.id.name;
      }
      const parent = current.parent;
      if (
        parent?.type === "VariableDeclarator" &&
        parent.id.type === "Identifier"
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
  catchNode: ESTree.CatchClause,
  kind: SentinelKind,
): boolean {
  if (kind !== "boolean") {
    return false;
  }
  let declared = enclosingReturnTypeNode(catchNode);
  if (
    declared?.type === "TSTypeReference" &&
    declared.typeName.type === "Identifier" &&
    declared.typeName.name === "Promise"
  ) {
    declared = declared.typeArguments?.params[0] ?? null;
  }
  return declared?.type === "TSBooleanKeyword";
}

/** The declared return type annotation of the nearest enclosing function, or null. */
function enclosingReturnTypeNode(
  node: ESTree.Node,
): ESTree.TSType | null {
  let current: ESTree.Node | null | undefined = node.parent;
  while (current != null && current !== null) {
    if (isFunctionNode(current) && "returnType" in current) {
      return current.returnType?.typeAnnotation ?? null;
    }
    current = current.parent;
  }
  return null;
}

/** Does the try body contain only deliberate parse/decode operations that may throw? */
function tryReturnsSafeParse(catchNode: ESTree.CatchClause): boolean {
  const tryBlock = tryBlockOf(catchNode);
  let sawSafeParse = false;
  let sawUnsafeOperation = false;

  const recurse = (current: ESTree.Node): void => {
    if (sawUnsafeOperation || (current !== tryBlock && isFunctionNode(current))) return;
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

  function visitChildren(current: ESTree.Node): void {
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
  if (catchNode.parent?.type !== "TryStatement") throw new Error("CatchClause has no TryStatement parent");
  return catchNode.parent.block;
}

/** Whether a normal path returns the same sentinel kind as the catch. */
function functionReturnsSameSentinelKindElsewhere(
  catchNode: ESTree.CatchClause,
  kind: SentinelKind,
): boolean {
  // Empty collections and objects are common successful results but say
  // nothing about whether operational failure may be converted into one.
  if (kind !== "nullish" && kind !== "boolean") return false;
  const functionBody = enclosingFunctionBody(catchNode);
  if (functionBody === null) {
    return false;
  }
  return walkWithinScope(functionBody, (current) => {
    if (current.type !== "ReturnStatement") {
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
  node: ESTree.Node,
): ESTree.BlockStatement | null {
  let current: ESTree.Node | null | undefined = node.parent;
  while (current != null && current !== null) {
    if (
      isFunctionNode(current) &&
      "body" in current &&
      isNode(current.body) &&
      current.body.type === "BlockStatement"
    ) {
      return current.body;
    }
    current = current.parent;
  }
  return null;
}

/** Sentinel kinds reachable through a direct, ternary, or fallback return. */
function returnedSentinelKinds(
  arg: ESTree.Expression | null,
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
function isWithin(node: ESTree.Node, ancestor: ESTree.Node): boolean {
  let current: ESTree.Node | null | undefined = node;
  while (current != null && current !== null) {
    if (current === ancestor) {
      return true;
    }
    current = current.parent;
  }
  return false;
}

export default createRule<Options, MessageIds>({
  name: "no-sentinel-return-on-catch",
  documentation: NO_SENTINEL_RETURN_ON_CATCH_DOCUMENTATION,
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
    if (isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)) {
      return {};
    }

    const matcher = createLogMatcher(loggingOptions);

    function logsOrReportsError(
      catchBody: ESTree.BlockStatement,
      caughtName: string | null,
    ): boolean {
      return walkWithinScope(catchBody, (current) => {
        if (current.type !== "CallExpression") {
          return false;
        }
        if (matcher.isLoggingCall(current)) {
          return caughtName === null || argsIncludeBinding(current.arguments, caughtName);
        }
        const name = calleeName(current.callee);
        return (
          name !== null &&
          REPORT_NAME_RE.test(name) &&
          (caughtName === null || argsIncludeBinding(current.arguments, caughtName))
        );
      });
    }

    return {
      CatchClause(node: ESTree.CatchClause): void {
        const body = node.body.body;
        if (body.length === 0) {
          return;
        }

        const last = body[body.length - 1];
        if (last === undefined || last.type !== "ReturnStatement") {
          return;
        }

        if (!isSentinelArgument(last.argument)) {
          return;
        }
        const returned = unwrapSentinelExpression(last.argument);
        if (returned?.type === "Identifier" && returned.name === "undefined" &&
          (findVariable(context.sourceCode.getScope(returned), returned.name)?.defs.length ?? 0) > 0) return;

        if (containsThrow(node.body)) {
          return;
        }

        const caughtName =
          node.param?.type === "Identifier"
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

function isNonReadingProperty(current: ESTree.Node, key: string): boolean {
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
