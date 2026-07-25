/**
 * @fileoverview TS port of SARJ026 (`prefer-namedtuple-over-tuple-return`). A
 * multi-field value returned across a module boundary should be an object with
 * named fields, not a positional tuple the caller has to unpack by position.
 *
 * `export async function fetchDoc(): Promise<[string, Headers, string | null]>`
 * forces every call site to remember which slot is which, and the names live
 * only in the destructuring at the call site — so two call sites can and do
 * disagree. Returning `{ body, headers, contentType }` names each field once, at
 * the definition, and a wrong-field access becomes a type error instead of a
 * silently wrong value.
 *
 * Fires on an *exported* function (or exported class method) whose declared
 * return type is a tuple of two or more elements — directly or wrapped in
 * `Promise<...>`.
 *
 * The permitted tuple uses are deliberately NOT flagged, matching the Python
 * rule's tuning plus the TS-specific idioms:
 *
 * - **Homogeneous tuples** — `[number, number]`, `[Date, Date]`: a pair of the
 *   same thing (a range, a coordinate), not distinct fields.
 * - **Variadic tuples** — `[string, ...number[]]`: an immutable sequence, not a
 *   fixed record.
 * - **Labeled tuple members** — `[status: number, body: string]`: TypeScript
 *   surfaces those names at the call site, which is the whole point of the rule.
 * - **Discriminated tags** — `["ok", T]` with a literal first element: the tuple
 *   IS the discriminated union.
 * - **React hooks** — any `use*` function. `[value, setValue]` is the
 *   established contract of the entire hooks ecosystem; renaming at the call
 *   site is the intended affordance, not a hazard.
 * - Single-element tuples, unannotated returns, and non-exported helpers, whose
 *   two or three call sites live in the same file as the definition.
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

type MessageIds = "noPositionalTupleReturn";
type Options = readonly [];

const MIN_ELEMENTS = 2;

/** Type wrappers whose single type argument is the value actually returned. */
const AWAITABLE_TYPES: ReadonlySet<string> = new Set(["Promise", "PromiseLike", "Awaited"]);

/** The tuple type a return annotation resolves to, unwrapping `Promise<...>`. */
function tupleReturnType(node: TSESTree.TypeNode): TSESTree.TSTupleType | null {
  if (node.type === AST_NODE_TYPES.TSTupleType) {
    return node;
  }
  if (
    node.type === AST_NODE_TYPES.TSTypeReference &&
    node.typeName.type === AST_NODE_TYPES.Identifier &&
    AWAITABLE_TYPES.has(node.typeName.name)
  ) {
    const argument = node.typeArguments?.params[0];
    return argument === undefined ? null : tupleReturnType(argument);
  }
  return null;
}

/** Source text with all whitespace runs collapsed, for structural comparison. */
function normalizedText(sourceCode: { getText: (node: TSESTree.Node) => string }, node: TSESTree.Node): string {
  return sourceCode.getText(node).replaceAll(/\s+/g, " ").trim();
}

/**
 * True when the tuple is one of the permitted shapes: variadic, labeled, tagged
 * by a leading literal type, or structurally homogeneous.
 */
function isPermittedTuple(
  tuple: TSESTree.TSTupleType,
  sourceCode: { getText: (node: TSESTree.Node) => string },
): boolean {
  const elements = tuple.elementTypes;
  if (elements.length < MIN_ELEMENTS) {
    return true;
  }
  if (elements.some((element) => element.type === AST_NODE_TYPES.TSRestType)) {
    return true;
  }
  if (elements.some((element) => element.type === AST_NODE_TYPES.TSNamedTupleMember)) {
    return true;
  }
  if (elements[0]?.type === AST_NODE_TYPES.TSLiteralType) {
    return true;
  }
  const texts = new Set(elements.map((element) => normalizedText(sourceCode, element)));
  return texts.size === 1;
}

/** The declared name of a function-ish node, or null for an anonymous one. */
function functionName(node: TSESTree.Node): string | null {
  if (node.type === AST_NODE_TYPES.FunctionDeclaration) {
    return node.id?.name ?? null;
  }
  const parent = node.parent;
  if (parent?.type === AST_NODE_TYPES.VariableDeclarator && parent.id.type === AST_NODE_TYPES.Identifier) {
    return parent.id.name;
  }
  if (
    (parent?.type === AST_NODE_TYPES.MethodDefinition ||
      parent?.type === AST_NODE_TYPES.PropertyDefinition ||
      parent?.type === AST_NODE_TYPES.Property) &&
    parent.key.type === AST_NODE_TYPES.Identifier
  ) {
    return parent.key.name;
  }
  return null;
}

/**
 * True when the function is reachable from outside the module — the boundary the
 * rule is about. Walks to the top-level statement that contains it and asks
 * whether that statement is exported.
 */
function isExported(node: TSESTree.Node): boolean {
  for (let current: TSESTree.Node | undefined | null = node; current != null; current = current.parent) {
    const parent = current.parent;
    if (
      parent?.type === AST_NODE_TYPES.ExportNamedDeclaration ||
      parent?.type === AST_NODE_TYPES.ExportDefaultDeclaration
    ) {
      return true;
    }
  }
  return false;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-positional-tuple-return",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow returning a positional tuple of distinct fields from an exported function; return a named object so call sites cannot mismatch slots.",
    },
    schema: [],
    messages: {
      noPositionalTupleReturn:
        "Exported `{{name}}` returns a positional {{count}}-tuple, so every call site re-invents the field names and can disagree. Return a named object (or label the tuple members) instead.",
    },
  },
  defaultOptions: [],
  create(context) {
    const check = (
      node:
        | TSESTree.FunctionDeclaration
        | TSESTree.FunctionExpression
        | TSESTree.ArrowFunctionExpression,
    ): void => {
      const annotation = node.returnType?.typeAnnotation;
      if (annotation === undefined) {
        return;
      }
      const tuple = tupleReturnType(annotation);
      if (tuple === null || isPermittedTuple(tuple, context.sourceCode)) {
        return;
      }
      const name = functionName(node);
      if (name === null || name.startsWith("_") || /^use[A-Z]/.test(name)) {
        return;
      }
      if (!isExported(node)) {
        return;
      }
      context.report({
        node: tuple,
        messageId: "noPositionalTupleReturn",
        data: { name, count: String(tuple.elementTypes.length) },
      });
    };
    return {
      FunctionDeclaration: check,
      FunctionExpression: check,
      ArrowFunctionExpression: check,
    };
  },
});
