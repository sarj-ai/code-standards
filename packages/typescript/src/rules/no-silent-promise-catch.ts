/**
 * @fileoverview no-silent-promise-catch — rejection handlers must not silently swallow the error.
 *
 * Port of the 18.x `no-silent-promise-catch` rule. Same algorithm; the
 * test/script file gate runs in `before()`.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-silent-promise-catch.test.ts
 */

import type { Comment } from "@oxlint/plugins";

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isScriptFile, isTestFile } from "../utils/paths.js";
import { findVariable, staticPropertyName } from "../utils/static-string.js";
import { isZodModule } from "../utils/zod.js";

const NAME = "no-silent-promise-catch";

type Handler = ESTree.ArrowFunctionExpression | ESTree.Function;
type Identifier = Extract<Node, { type: "Identifier" }>;

const BODY_PARSE_METHODS: ReadonlySet<string> = new Set([
  "arrayBuffer",
  "blob",
  "bytes",
  "formData",
  "json",
  "text",
]);

const ZOD_CONSTRUCTORS: ReadonlySet<string> = new Set([
  "any", "array", "bigint", "boolean", "custom", "date", "enum", "literal",
  "map", "never", "null", "number", "object", "record", "set", "string",
  "tuple", "undefined", "union", "unknown", "url",
]);
const ZOD_CHAIN_METHODS: ReadonlySet<string> = new Set([
  "array", "catch", "default", "describe", "max", "min", "nullable", "nullish",
  "optional", "readonly", "refine", "superRefine", "transform",
]);

const ZOD_COERCIONS: ReadonlySet<string> = new Set(["bigint", "boolean", "number", "string"]);

const TEARDOWN_METHODS: ReadonlySet<string> = new Set([
  "cancel",
  "close",
  "abort",
  "destroy",
  "dispose",
  "release",
  "unlock",
  "disconnect",
]);

const DIRECTIVE_COMMENT_RE =
  /^\s*(eslint-|@ts-|prettier-ignore|biome-ignore|c8 |v8 |istanbul )/;

const isExplanatory = (comment: Comment): boolean => !DIRECTIVE_COMMENT_RE.test(comment.value);

function memberCallee(node: Node): ESTree.MemberExpression | null {
  if (node.type !== "CallExpression") return null;
  const callee = unwrapExpression(node.callee);
  return callee.type === "MemberExpression" ? callee : null;
}

function nonEmptyStatements(block: ESTree.BlockStatement): readonly Node[] {
  return (block.body as readonly Node[]).filter((statement) => statement.type !== "EmptyStatement");
}

/** True when the handler's whole body provably does nothing with the error. */
function isSilentHandler(handler: Handler): boolean {
  const body = handler.body;
  if (body === null) return false;
  if (body.type !== "BlockStatement") {
    // Arrow expression body: `.catch(() => null)`
    return isSilentExpression(body);
  }
  const statements = nonEmptyStatements(body);
  // `.catch(() => {})` / `.catch(function () {})`
  if (statements.length === 0) return true;
  if (statements.length === 1) {
    const only = statements[0];
    if (only !== undefined && only.type === "ReturnStatement") {
      // `.catch(() => { return null; })`
      return only.argument === null || isSilentExpression(only.argument);
    }
  }
  return false;
}

/** True for expressions that provably discard the error: bare literals,
 * `undefined`, empty object/array literals. */
function isSilentExpression(node: Node): boolean {
  switch (node.type) {
    case "Literal":
      // null / number / string / boolean literals (regex literals excluded —
      // nobody writes `.catch(() => /x/)` and they are not sentinel values).
      return !("regex" in node);
    case "Identifier":
      return node.name === "undefined";
    case "UnaryExpression":
      // `void 0` — the other spelling of undefined.
      return node.operator === "void" && node.argument.type === "Literal";
    case "ObjectExpression":
      return node.properties.length === 0;
    case "ArrayExpression":
      return node.elements.length === 0;
    case "TSAsExpression":
      // `.catch(() => null as Foo | null)` is still silent.
      return isSilentExpression(node.expression);
    default:
      return false;
  }
}

function hasRecoveryContinuation(call: ESTree.CallExpression, sourceCode: SourceCode): boolean {
  let current: Node = call;
  for (;;) {
    const member = parentOf(current);
    if (member?.type !== "MemberExpression" || member.object !== current || staticPropertyName(member, sourceCode) !== "then") return false;
    const next = parentOf(member);
    if (member.optional || next?.type !== "CallExpression" || next.callee !== member ||
      !isIdentityContinuation(next, sourceCode)) return true;
    current = next;
  }
}

function isIdentityContinuation(call: ESTree.CallExpression, sourceCode: SourceCode): boolean {
  const argument = call.arguments[0];
  if (call.optional || call.arguments.length !== 1 || argument === undefined) return false;
  const handler = unwrapExpression(argument);
  if (handler.type !== "ArrowFunctionExpression" || handler.async || handler.params.length !== 1) return false;
  const parameter = handler.params[0] as Node | undefined;
  const value = returnedIdentifier(handler.body);
  if (parameter?.type !== "Identifier" || value?.type !== "Identifier") return false;
  const binding = findVariable(sourceCode.getScope(parameter), parameter.name);
  return binding !== null && findVariable(sourceCode.getScope(value), value.name) === binding;
}

/** The identifier an arrow returns, from a concise body or a lone `return`. */
function returnedIdentifier(body: Node): Node | null {
  let returned: Node | null = body;
  if (body.type === "BlockStatement") {
    const statements = nonEmptyStatements(body);
    const only = statements[0];
    returned = statements.length === 1 && only?.type === "ReturnStatement" ? only.argument : null;
  }
  const value = returned === null ? null : unwrapExpression(returned);
  return value?.type === "Identifier" ? value : null;
}

/** A single-declaration, never-reassigned `const`-like binding's initializer is a Zod schema. */
function isZodBinding(node: Identifier, sourceCode: SourceCode, seen: Set<Node>): boolean {
  const binding = findVariable(sourceCode.getScope(node), node.name);
  if (binding === null || binding.references.some((reference) => reference.isWrite() && reference.init !== true)) return false;
  const [definition] = binding.defs;
  const declarator = definition?.node;
  return binding.defs.length === 1 && declarator?.type === "VariableDeclarator" &&
    declarator.init !== null && isZodSchema(declarator.init, sourceCode, seen);
}

function isZodSchema(node: Node, sourceCode: SourceCode, seen = new Set<Node>()): boolean {
  if (seen.has(node)) return false;
  seen.add(node);
  if (node.type === "Identifier") return isZodBinding(node, sourceCode, seen);
  const callee = memberCallee(node);
  const method = callee === null ? null : staticPropertyName(callee, sourceCode);
  if (callee === null || method === null) return false;
  let object: Node = callee.object;
  if (object.type === "MemberExpression" && staticPropertyName(object, sourceCode) === "coerce" && ZOD_COERCIONS.has(method)) {
    object = object.object;
  }
  if (object.type === "Identifier" && ZOD_CONSTRUCTORS.has(method) && isZodImport(object, sourceCode)) return true;
  return ZOD_CHAIN_METHODS.has(method) && isZodSchema(object, sourceCode, seen);
}

/** `identifier` is bound by a namespace, default or `{ z }` import from a Zod module. */
function isZodImport(identifier: Identifier, sourceCode: SourceCode): boolean {
  const binding = findVariable(sourceCode.getScope(identifier), identifier.name);
  return binding?.defs.some((definition) => {
    const specifier = definition.node;
    const declaration = parentOf(specifier);
    return (specifier.type === "ImportNamespaceSpecifier" || specifier.type === "ImportDefaultSpecifier" ||
      (specifier.type === "ImportSpecifier" && specifier.imported.type === "Identifier" && specifier.imported.name === "z")) &&
      declaration?.type === "ImportDeclaration" && isZodModule(String(declaration.source.value));
  }) ?? false;
}

/** The inline function handling rejection in `.catch(fn)` / `.then(onFulfilled, fn)`. */
function rejectionHandler(node: ESTree.CallExpression, method: string | null): Handler | null {
  const handlerIndex = method === "catch" ? 0 : method === "then" ? 1 : null;
  const argument = handlerIndex === null || node.arguments.length !== handlerIndex + 1 ? undefined : node.arguments[handlerIndex];
  const handler = argument === undefined ? null : unwrapExpression(argument);
  return handler?.type === "ArrowFunctionExpression" || handler?.type === "FunctionExpression" ? handler : null;
}

/** Receivers whose rejection is an expected, ignorable outcome. */
function isIgnorableReceiver(receiver: Node, method: string | null, sourceCode: SourceCode): boolean {
  return (method === "catch" && isZodSchema(receiver, sourceCode)) ||
    isBodyParseCall(receiver, sourceCode) ||
    isTeardownCall(receiver, sourceCode) ||
    isCancelledWebShare(receiver, sourceCode);
}

/** True for a standard Fetch body parser — the receiver of a parse-fallback catch. */
function isBodyParseCall(node: Node, sourceCode: SourceCode): boolean {
  const callee = memberCallee(node);
  if (callee === null || (node as ESTree.CallExpression).arguments.length !== 0) return false;
  const method = staticPropertyName(callee, sourceCode);
  return method !== null && BODY_PARSE_METHODS.has(method);
}

/** True for `reader.cancel(reason)` / `stream.close()` — a teardown receiver. */
function isTeardownCall(node: Node, sourceCode: SourceCode): boolean {
  const callee = memberCallee(node);
  if (callee === null) return false;
  const method = staticPropertyName(callee, sourceCode);
  return method !== null && TEARDOWN_METHODS.has(method);
}

/** Web Share rejects on ordinary user cancellation, which callers may ignore. */
function isCancelledWebShare(node: Node, sourceCode: SourceCode): boolean {
  const callee = memberCallee(node);
  return (
    callee !== null &&
    callee.object.type === "Identifier" &&
    callee.object.name === "navigator" &&
    staticPropertyName(callee, sourceCode) === "share"
  );
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow `.catch()` and second-argument `.then()` handlers that silently swallow a rejection; log, rethrow, or handle the error.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      silentCatch:
        "This rejection handler swallows the error without logging, rethrowing, or handling it — failures become invisible and callers get an indistinguishable sentinel. Log the error (and only then map to a fallback), or let it propagate.",
    },
  },
  createOnce(context) {
    const hasExplanatoryComment = (call: ESTree.CallExpression, handler: Handler): boolean => {
      const sourceCode = context.sourceCode;
      if (sourceCode.getCommentsInside(handler).some(isExplanatory)) return true;
      // Walk out to the enclosing statement so a comment above or beside
      // `lazyRoutePromise.catch(() => {});` is found rather than one sitting
      // between the receiver and `.catch`.
      let statement: Node = call;
      for (let parent = parentOf(statement);
        parent !== null && !statement.type.endsWith("Statement") && statement.type !== "VariableDeclaration";
        parent = parentOf(statement)) {
        statement = parent;
      }
      if (sourceCode.getCommentsBefore(statement).some(isExplanatory)) return true;
      const endLine = statement.loc.end.line;
      return sourceCode.getCommentsAfter(statement).some((c) => isExplanatory(c) && c.loc.start.line === endLine);
    };

    return {
      before() {
        const file = { filename: context.filename, cwd: context.cwd };
        if (isTestFile(file) || isScriptFile(file)) return false;
        return undefined;
      },
      CallExpression(node) {
        const sourceCode = context.sourceCode;
        const callee = unwrapExpression(node.callee);
        if (callee.type !== "MemberExpression") return;
        const method = staticPropertyName(callee, sourceCode);
        const handler = rejectionHandler(node, method);
        // Cheap structural checks run first; every exemption below is a pure predicate.
        if (handler === null || !isSilentHandler(handler)) return;
        if (isIgnorableReceiver(callee.object, method, sourceCode)) return;
        if (hasRecoveryContinuation(node, sourceCode) || hasExplanatoryComment(node, handler)) return;
        // Anchor on the CallExpression, not the handler: when the handler
        // sits on a later line than the call (multi-line `.catch(`), a
        // handler-anchored report escapes an `eslint-disable-next-line`
        // above the call AND marks that directive as unused.
        context.report({ node, messageId: "silentCatch" });
      },
    };
  },
});
