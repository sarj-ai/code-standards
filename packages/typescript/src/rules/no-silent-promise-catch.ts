/**
 * @fileoverview no-silent-promise-catch — a silent `.catch` or second `.then` handler deletes the rejection and returns a sentinel.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-silent-promise-catch.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


import { createRule, type RuleDocumentation } from "./_docs.js";
import { isScriptFile, isTestFile } from "./_paths.js";
import { isZodModule } from "./_zod.js";

type MessageIds = "silentCatch";
type Options = readonly [];

export const NO_SILENT_PROMISE_CATCH_DOCUMENTATION = {
  summary: "Disallow `.catch()` and second-argument `.then()` handlers that silently swallow a rejection; log, rethrow, or handle the error.",
  rationale: "A swallowed rejection hides failures and gives callers an indistinguishable fallback value.",
  remediation: "Log, rethrow, or explicitly recover from the rejection; explain intentional teardown suppression.",
  category: "correctness",
  limitations: ["Test files, teardown calls, explanatory comments, non-function handlers, and handlers that consume or report the error are excluded.", "Recognized imported Zod construction chains and their stable local aliases are excluded. Other untyped catch-like APIs are not proven to be Promises."],
  examples: [
    { id: "reported-rejection", title: "Report the rejection", outcome: "no-match", files: [{ path: "src/load.ts", source: "load().catch((error) => logger.error({ error }, 'load failed'));" }], focusPath: "src/load.ts", expectedCount: 0, public: true },
    { id: "silent-rejection", title: "Do not swallow the rejection", outcome: "match", files: [{ path: "src/load.ts", source: "load().catch(() => null);" }], focusPath: "src/load.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

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
  "tuple", "undefined", "union", "unknown",
]);
const ZOD_CHAIN_METHODS: ReadonlySet<string> = new Set([
  "array", "catch", "default", "describe", "max", "min", "nullable", "nullish",
  "optional", "readonly", "refine", "superRefine", "transform",
]);

/** True for a standard Fetch body parser — the receiver of a parse-fallback catch. */
function isBodyParseCall(node: ESTree.Expression): boolean {
  return (
    node.type === "CallExpression" &&
    node.arguments.length === 0 &&
    node.callee.type === "MemberExpression" &&
    !node.callee.computed &&
    node.callee.property.type === "Identifier" &&
    BODY_PARSE_METHODS.has(node.callee.property.name)
  );
}

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

const isExplanatory = (comment: { value: string }): boolean =>
  !DIRECTIVE_COMMENT_RE.test(comment.value);

/** True for `reader.cancel(reason)` / `stream.close()` — a teardown receiver. */
function isTeardownCall(node: ESTree.Expression): boolean {
  return (
    node.type === "CallExpression" &&
    node.callee.type === "MemberExpression" &&
    !node.callee.computed &&
    node.callee.property.type === "Identifier" &&
    TEARDOWN_METHODS.has(node.callee.property.name)
  );
}

/** Web Share rejects on ordinary user cancellation, which callers may ignore. */
function isCancelledWebShare(node: ESTree.Expression): boolean {
  return (
    node.type === "CallExpression" &&
    node.callee.type === "MemberExpression" &&
    !node.callee.computed &&
    node.callee.object.type === "Identifier" &&
    node.callee.object.name === "navigator" &&
    node.callee.property.type === "Identifier" &&
    node.callee.property.name === "share"
  );
}

/** True when the handler's whole body provably does nothing with the error. */
function isSilentHandler(
  handler: ESTree.ArrowFunctionExpression | ESTree.Function,
): boolean {
  const body = handler.body;

  if (body === null) return false;
  if (body.type !== "BlockStatement") {
    // Arrow expression body: `.catch(() => null)`
    return isSilentExpression(body);
  }

  if (body.body.length === 0) {
    // `.catch(() => {})` / `.catch(function () {})`
    return true;
  }

  if (body.body.length === 1) {
    const only = body.body[0];
    if (only !== undefined && only.type === "ReturnStatement") {
      // `.catch(() => { return null; })`
      return only.argument === null || isSilentExpression(only.argument);
    }
  }

  return false;
}

/** True for expressions that provably discard the error: bare literals,
 * `undefined`, empty object/array literals. */
function isSilentExpression(node: ESTree.Expression): boolean {
  switch (node.type) {
    case "Literal":
      // null / number / string / boolean literals (regex literals excluded —
      // nobody writes `.catch(() => /x/)` and they are not sentinel values).
      return !("regex" in node);
    case "Identifier":
      return node.name === "undefined";
    case "UnaryExpression":
      // `void 0` — the other spelling of undefined.
      return (
        node.operator === "void" &&
        node.argument.type === "Literal"
      );
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

export default createRule<Options, MessageIds>({
  name: "no-silent-promise-catch",
  documentation: NO_SILENT_PROMISE_CATCH_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow `.catch()` and second-argument `.then()` handlers that silently swallow a rejection; log, rethrow, or handle the error.",
    },
    schema: [],
    messages: {
      silentCatch:
        "This rejection handler swallows the error without logging, rethrowing, or handling it — failures become invisible and callers get an indistinguishable sentinel. Log the error (and only then map to a fallback), or let it propagate.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(sourceOrigin(context).filename) || isScriptFile(sourceOrigin(context).filename)) {
      return {};
    }

    function isZodSchema(node: ESTree.Node, seen = new Set<ESTree.Node>()): boolean {
      if (seen.has(node)) return false;
      seen.add(node);
      if (node.type === "Identifier") {
        const binding = findVariable(context.sourceCode.getScope(node), node.name);
        if (binding === null || binding.references.some((reference) => reference.isWrite() && reference.init !== true)) return false;
        const [definition] = binding.defs;
        return binding.defs.length === 1 && definition?.node.type === "VariableDeclarator" &&
          definition.node.init !== null && isZodSchema(definition.node.init, seen);
      }
      if (node.type !== "CallExpression" || node.callee.type !== "MemberExpression" ||
        node.callee.computed || node.callee.property.type !== "Identifier") return false;
      const { object, property } = node.callee;
      if (object.type === "Identifier" && ZOD_CONSTRUCTORS.has(property.name)) {
        const binding = findVariable(context.sourceCode.getScope(object), object.name);
        if (binding?.defs.some((definition) => {
          const specifier = definition.node;
          return (specifier.type === "ImportNamespaceSpecifier" || specifier.type === "ImportDefaultSpecifier" ||
            (specifier.type === "ImportSpecifier" && specifier.imported.type === "Identifier" && specifier.imported.name === "z")) &&
            specifier.parent?.type === "ImportDeclaration" && isZodModule(String(specifier.parent.source.value));
        })) return true;
      }
      return ZOD_CHAIN_METHODS.has(property.name) && isZodSchema(object, seen);
    }

    const hasExplanatoryComment = (
      call: ESTree.CallExpression,
      handler: ESTree.ArrowFunctionExpression | ESTree.Function,
    ): boolean => {
      const sourceCode = context.sourceCode;
      if (sourceCode.getCommentsInside(handler).some(isExplanatory)) {
        return true;
      }
      // Walk out to the enclosing statement so a comment above or beside
      // `lazyRoutePromise.catch(() => {});` is found rather than one sitting
      // between the receiver and `.catch`.
      let statement: ESTree.Node = call;
      while (
        statement.parent != null &&
        statement.parent !== null &&
        !statement.type.endsWith("Statement") &&
        statement.type !== "VariableDeclaration"
      ) {
        statement = statement.parent;
      }
      if (sourceCode.getCommentsBefore(statement).some(isExplanatory)) {
        return true;
      }
      return sourceCode
        .getCommentsAfter(statement)
        .some(
          (c) => isExplanatory(c) && c.loc.start.line === statement.loc.end.line,
        );
    };

    return {
      CallExpression(node: ESTree.CallExpression): void {
        if (
          node.callee.type !== "MemberExpression" ||
          node.callee.computed ||
          node.callee.property.type !== "Identifier"
        ) {
          return;
        }

        const method = node.callee.property.name;
        const handlerIndex = method === "catch" ? 0 : method === "then" ? 1 : null;
        if (handlerIndex === null) return;
        if (method === "catch" && isZodSchema(node.callee.object)) return;

        if (isBodyParseCall(node.callee.object)) {
          return;
        }

        if (isTeardownCall(node.callee.object)) {
          return;
        }

        if (isCancelledWebShare(node.callee.object)) {
          return;
        }

        // `p.catch(() => null).then(...)` — the next link consumes the fallback,
        // so it is a recovery step, not a value handed back to an outside caller.
        if (
          node.parent?.type === "MemberExpression" &&
          node.parent.object === node &&
          !node.parent.computed &&
          node.parent.property.type === "Identifier" &&
          node.parent.property.name === "then"
        ) {
          return;
        }

        const expectedArguments = method === "catch" ? 1 : 2;
        if (node.arguments.length !== expectedArguments) {
          return;
        }
        const handler = node.arguments[handlerIndex];
        if (
          handler === undefined ||
          (handler.type !== "ArrowFunctionExpression" &&
            handler.type !== "FunctionExpression")
        ) {
          return;
        }

        if (hasExplanatoryComment(node, handler)) {
          return;
        }

        if (isSilentHandler(handler)) {
          // Anchor on the CallExpression, not the handler: when the handler
          // sits on a later line than the call (multi-line `.catch(`), a
          // handler-anchored report escapes an `eslint-disable-next-line`
          // above the call AND marks that directive as unused.
          context.report({ node, messageId: "silentCatch" });
        }
      },
    };
  },
});
