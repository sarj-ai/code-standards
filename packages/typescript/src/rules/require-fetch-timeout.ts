/**
 * @fileoverview require-fetch-timeout — a `fetch` with no signal hangs for as long as the upstream stalls, holding the caller open with it.
 *
 * Port of the 18.x `require-fetch-timeout` rule. Untyped.
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { nativeFetchReference } from "../utils/native-fetch-reference.js";
import { isScriptFile, isTestFile, matchesAnyPattern } from "../utils/paths.js";
import { findVariable, getPropertyName, staticPropertyName } from "../utils/static-string.js";

const NAME = "require-fetch-timeout";

type Identifier = Extract<Node, { type: "Identifier" }>;
type EmptySignal = "null" | "undefined";
type SignalState = EmptySignal | "absent" | "unknown";
type Options = readonly [{ allowIn?: readonly string[] }?];


function emptySignal(
  expression: Node,
  resolvesToGlobal: (identifier: Identifier) => boolean,
): EmptySignal | null {
  const value = unwrapExpression(expression);
  if (value.type === "Literal" && value.value === null)
    return "null";
  if (
    value.type === "Identifier" &&
    value.name === "undefined" &&
    resolvesToGlobal(value)
  )
    return "undefined";
  if (
    value.type === "UnaryExpression" &&
    value.operator === "void"
  ) {
    const argument = unwrapExpression(value.argument);
    if (argument.type === "Literal" && argument.value === 0)
      return "undefined";
  }
  return null;
}

function initSignalState(
  argument: Node,
  resolvesToGlobal: (identifier: Identifier) => boolean,
  sourceCode: SourceCode,
): SignalState {
  const init = unwrapExpression(argument);
  if (init.type !== "ObjectExpression") return "unknown";
  let state: SignalState = "absent";
  for (const prop of init.properties) {
    if (prop.type === "SpreadElement") {
      state = "unknown";
      continue;
    }
    if (prop.kind !== "init" || hasUnprovedPrototype(prop)) return "unknown";
    const name = staticPropertyName(prop, sourceCode);
    if (name === "signal") {
      state = !prop.method
        ? (emptySignal(prop.value, resolvesToGlobal) ?? "unknown")
        : "unknown";
    } else if (
      !prop.computed &&
      name === "__proto__" &&
      state === "absent"
    ) {
      state = "unknown";
    } else if (prop.computed && name === null) {
      state = "unknown";
    }
  }
  return state;
}

function hasUnprovedPrototype(property: ESTree.ObjectProperty): boolean {
  if (
    property.computed ||
    property.method ||
    property.shorthand ||
    getPropertyName(property) !== "__proto__"
  )
    return false;
  const prototype = unwrapExpression(property.value);
  if (prototype.type === "Literal" && prototype.value === null)
    return false;
  if (prototype.type !== "ObjectExpression") return true;
  return prototype.properties.some(
    (member) =>
      member.type === "SpreadElement" ||
      member.kind !== "init" ||
      (!member.computed && getPropertyName(member) === "__proto__") ||
      (member.computed && member.key.type !== "Literal"),
  );
}

/** True for a URL spelled inline rather than a forwarded Request. */
function isInlineUrl(
  argument: Node,
  resolvesToGlobal: (identifier: Identifier) => boolean,
): boolean {
  const node = unwrapExpression(argument);
  return (
    (node.type === "Literal" && typeof node.value === "string") ||
    node.type === "TemplateLiteral" ||
    (node.type === "NewExpression" &&
      node.callee.type === "Identifier" &&
      node.callee.name === "URL" &&
      resolvesToGlobal(node.callee))
  );
}

/** `ref.name = …` for a statically named field other than `signal` and `__proto__`. */
function writesNonSignalField(ref: Node): boolean {
  const member = parentOf(ref);
  if (member?.type !== "MemberExpression" || member.object !== ref || member.computed) return false;
  const assignment = parentOf(member);
  return member.property.type === "Identifier" &&
    member.property.name !== "signal" &&
    member.property.name !== "__proto__" &&
    assignment?.type === "AssignmentExpression" &&
    assignment.left === member;
}

export default defineRule({
  meta: {
    defaultOptions: [{}],
    type: "problem",
    docs: {
      description:
        "Require an explicit abort signal on locally analyzable global fetch calls.",
      url: docsUrl(NAME),
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          allowIn: {
            description:
              "Glob patterns for wrapper modules exempt from the rule. Matched against the ABSOLUTE file path, so anchor with a `**/` prefix (e.g. `**/http-client.ts`).",
            type: "array",
            items: { type: "string" },
          },
        },
      },
    ],
    messages: {
      missingSignal:
        "This `fetch()` has no explicit abort signal. Pass `AbortSignal.timeout(ms)` for a deadline, or an owner-managed signal for cancellation.",
    },
  },
  createOnce(context) {
    let sourceCode: SourceCode;

    /** True when `identifier` resolves to the global (no local binding shadows it). */
    function resolvesToGlobal(identifier: Identifier): boolean {
      const scope = sourceCode.getScope(identifier);
      const variable = findVariable(scope, identifier.name);
      return variable === null || variable.defs.length === 0;
    }

    /** Prove a same-scope const object cannot acquire a signal before use. */
    function localConstInitSignalState(
      identifier: Identifier,
    ): SignalState {
      const variable = findVariable(
        sourceCode.getScope(identifier),
        identifier.name,
      );
      if (variable?.defs.length !== 1) return "unknown";
      const definition = variable.defs[0];
      if (definition?.type !== "Variable") return "unknown";
      const declarator = definition.node as ESTree.VariableDeclarator;
      const init = declarator.init;
      if (
        (definition.parent as ESTree.VariableDeclaration).kind !== "const" ||
        init === null ||
        unwrapExpression(init).type !== "ObjectExpression"
      ) {
        return "unknown";
      }
      for (const { identifier: ref } of variable.references) {
        if (ref !== identifier && ref !== definition.name && !writesNonSignalField(ref)) return "unknown";
      }
      return initSignalState(init, resolvesToGlobal, sourceCode);
    }

    function isForwardedRequest(
      argument: ESTree.Argument,
    ): boolean {
      let value = unwrapExpression(argument);
      if (value.type === "Identifier") {
        const binding = findVariable(
          sourceCode.getScope(value),
          value.name,
        );
        const definition =
          binding?.defs.length === 1 ? binding.defs[0] : undefined;
        if (definition?.type !== "Variable") return false;
        const init = (definition.node as ESTree.VariableDeclarator).init;
        if (
          (definition.parent as ESTree.VariableDeclaration).kind !== "const" ||
          init === null ||
          binding?.references.some(
            (reference) => reference.isWrite() && reference.init !== true,
          )
        )
          return false;
        value = unwrapExpression(init);
      }
      if (value.type !== "NewExpression") return false;
      const callee = unwrapExpression(value.callee);
      return (
        callee.type === "Identifier" &&
        callee.name === "Request" &&
        resolvesToGlobal(callee)
      );
    }

    return {
      before() {
        sourceCode = context.sourceCode;
        // `isTestFile` knows jscodeshift's `__testfixtures__/` spelling, so the
        // local pattern this rule used to keep for it decided nothing.
        const file = { filename: context.filename, cwd: context.cwd };
        if (isTestFile(file) || isScriptFile(file)) return false;
        const allowIn = (context.options[0] as Options[0])?.allowIn ?? [];
        return !(allowIn.length > 0 && matchesAnyPattern(context.filename, allowIn));
      },
      CallExpression(node: ESTree.CallExpression): void {
        const unwrappedNodeCallee = unwrapExpression(node.callee);
        if (!nativeFetchReference(unwrappedNodeCallee, sourceCode)) {
          return;
        }

        // Proxy passthrough: a lone non-string argument is a Request (or
        // equivalent) being forwarded — the inbound request owns the
        // lifetime, and a fresh signal cannot be attached without an init.
        const [first, rawInit] = node.arguments;
        const init =
          rawInit === undefined ? undefined : unwrapExpression(rawInit);
        const state =
          init === undefined
            ? "unknown"
            : init.type === "Identifier"
              ? localConstInitSignalState(init)
              : initSignalState(init, resolvesToGlobal, sourceCode);
        if (
          first !== undefined &&
          ((node.arguments.length === 1 &&
            !isInlineUrl(first, resolvesToGlobal)) ||
            (isForwardedRequest(first) && state !== "null"))
        ) {
          return;
        }

        if (
          init === undefined ||
          state !== "unknown" ||
          (first !== undefined &&
            isInlineUrl(first, resolvesToGlobal) &&
            emptySignal(init, resolvesToGlobal) !== null)
        ) {
          context.report({ node, messageId: "missingSignal" });
        }
      },
    };
  },
});
