/**
 * @fileoverview prefer-module-level-schema — a Zod schema built inside a function is rebuilt on every call, every request, every render.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-module-level-schema.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, Scope, Variable, Reference } from "@oxlint/plugins";


import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { isZodModule } from "./_zod.js";

type MessageIds = "hoistSchema";

export const PREFER_MODULE_LEVEL_SCHEMA_DOCUMENTATION = {
  summary: "Declare a Zod schema at module scope when it closes over nothing in the enclosing function",
  rationale: "A schema created inside a function is rebuilt on each call. Module scope can enable reuse across callers; local schemas already support local type inference.",
  remediation: "Move the closed schema declaration to module scope and reference it from the function.",
  category: "performance",
  limitations: ["Schemas that depend on local state or are wrapped in a recognized memoization helper are excluded.", "Eager calls outside the recognized Zod construction chain and new expressions are excluded. This is manual guidance, not a purity proof: review getters, callback effects, schema identity, error customization, and module initialization order before moving construction."],
  examples: [
    { id: "module-schema", title: "Declare the schema once", outcome: "no-match", files: [{ path: "src/handler.ts", source: "import { z } from 'zod'; const ZBody = z.object({ id: z.string(), name: z.string() }); export function handle(raw: unknown) { return ZBody.parse(raw); }" }], focusPath: "src/handler.ts", expectedCount: 0, public: true },
    { id: "local-schema", title: "Do not rebuild a closed schema", outcome: "match", files: [{ path: "src/handler.ts", source: "import { z } from 'zod'; export function handle(raw: unknown) { const ZBody = z.object({ id: z.string(), name: z.string() }); return ZBody.parse(raw); }" }], focusPath: "src/handler.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

type Options = readonly [
  {
    factories?: readonly string[];
    ignoreTestFiles?: boolean;
    memoCallees?: readonly string[];
    minProperties?: number;
  }?,
];

const DEFAULT_FACTORIES: readonly string[] = [
  "discriminatedUnion",
  "intersection",
  "looseObject",
  "object",
  "record",
  "strictObject",
  "tuple",
  "union",
];

const DEFAULT_MIN_PROPERTIES = 2;

const CONSTRUCTION_FACTORIES: ReadonlySet<string> = new Set([
  ...DEFAULT_FACTORIES,
  "any", "array", "bigint", "boolean", "custom", "date", "enum", "instanceof",
  "lazy", "literal", "map", "nan", "nativeEnum", "never", "null", "nullable",
  "nullish", "number", "optional", "preprocess", "promise", "set", "string",
  "symbol", "undefined", "unknown", "void",
]);

/** Wrappers that already pay the construction cost exactly once. */
const MEMO_CALLEES: ReadonlySet<string> = new Set([
  "lazy",
  "memo",
  "once",
  "useMemo",
]);

const TERMINAL_METHODS: ReadonlySet<string> = new Set([
  "isNullable",
  "isOptional",
  "parse",
  "parseAsync",
  "safeParse",
  "safeParseAsync",
  "spa",
]);

const ZOD_COMBINATOR_METHODS: ReadonlySet<string> = new Set([
  "and",
  "array",
  "catch",
  "catchall",
  "default",
  "extend",
  "merge",
  "or",
  "pipe",
  "refine",
  "superRefine",
  "transform",
]);

const I18N_CALLEE_NAMES: ReadonlySet<string> = new Set([
  "$t",
  "defineMessage",
  "gettext",
  "msg",
  "ngettext",
  "t",
  "translate",
]);

/** Receivers whose methods render locale-dependent text (`i18n._`, `intl.formatMessage`). */
const I18N_RECEIVER_NAMES: ReadonlySet<string> = new Set([
  "$i18n",
  "i18n",
  "intl",
]);

const FUNCTION_TYPES: ReadonlySet<ESTree.Node["type"]> = new Set([
  "ArrowFunctionExpression",
  "FunctionDeclaration",
  "FunctionExpression",
]);

/**
 * The whole schema EXPRESSION, not just the factory call: climb out through
 * `.refine(...)`, `.superRefine(...)`, `.transform(...)`, `.default(...)` and
 * every other builder method applied to it.
 */
function schemaExpression(node: ESTree.CallExpression): ESTree.Node {
  let current: ESTree.Node = node;
  for (;;) {
    const parent: ESTree.Node | undefined = current.parent ?? undefined;
    if (parent == null) {
      return current;
    }
    if (
      parent.type === "MemberExpression" &&
      parent.object === current &&
      !parent.computed &&
      parent.property.type === "Identifier" &&
      TERMINAL_METHODS.has(parent.property.name)
    ) {
      return current;
    }
    if (
      (parent.type === "MemberExpression" &&
        parent.object === current) ||
      (parent.type === "CallExpression" &&
        parent.callee === current) ||
      (parent.type === "TSAsExpression" &&
        parent.expression === current) ||
      (parent.type === "TSNonNullExpression" &&
        parent.expression === current)
    ) {
      current = parent;
      continue;
    }
    return current;
  }
}

/** The outermost function ancestor — hoisting targets module scope, not the nearest body. */
function outermostEnclosingFunction(
  node: ESTree.Node,
): ESTree.Node | undefined {
  let outermost: ESTree.Node | undefined;
  let current: ESTree.Node | null | undefined = node.parent ?? undefined;
  while (current != null) {
    if (FUNCTION_TYPES.has(current.type)) {
      outermost = current;
    }
    current = current.parent ?? undefined;
  }
  return outermost;
}

/** Does any node in `root`'s subtree satisfy `predicate`? */
function subtreeSome(
  root: ESTree.Node,
  predicate: (node: ESTree.Node) => boolean,
  skipDeferredFunctions = false,
): boolean {
  let found = false;
  const visit = (value: unknown): void => {
    if (found || value === null || typeof value !== "object") {
      return;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        visit(item);
      }
      return;
    }
    const candidate = value as Partial<ESTree.Node> & Record<string, unknown>;
    if (typeof candidate.type !== "string") {
      return;
    }
    if (skipDeferredFunctions && FUNCTION_TYPES.has(candidate.type)) return;
    if (predicate(candidate as ESTree.Node)) {
      found = true;
      return;
    }
    for (const key of Object.keys(candidate)) {
      if (key === "parent" || key === "loc" || key === "range") {
        continue;
      }
      visit(candidate[key]);
    }
  };
  visit(root);
  return found;
}

/** `this` / `super` / `arguments` anywhere inside pins the schema to its receiver. */
function readsReceiver(node: ESTree.Node): boolean {
  return subtreeSome(
    node,
    (inner) =>
      inner.type === "ThisExpression" ||
      inner.type === "Super" ||
      (inner.type === "Identifier" && inner.name === "arguments"),
  );
}

function buildsLocalizedText(node: ESTree.Node): boolean {
  return subtreeSome(node, (inner) => {
    if (inner.type === "TaggedTemplateExpression") {
      return true;
    }
    if (inner.type !== "CallExpression") {
      return false;
    }
    const { callee } = inner;
    if (callee.type === "Identifier") {
      return I18N_CALLEE_NAMES.has(callee.name);
    }
    return (
      callee.type === "MemberExpression" &&
      !callee.computed &&
      callee.object.type === "Identifier" &&
      I18N_RECEIVER_NAMES.has(callee.object.name)
    );
  });
}

function collectReferences(
  scope: Scope,
  out: Reference[],
): void {
  out.push(...scope.references);
  for (const child of scope.childScopes) {
    collectReferences(child, out);
  }
}

export default createRule<Options, MessageIds>({
  name: "prefer-module-level-schema",
  documentation: PREFER_MODULE_LEVEL_SCHEMA_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Declare a Zod schema at module scope when it closes over nothing in the enclosing function",
    },
    schema: [
      {
        type: "object",
        properties: {
          factories: {
            type: "array",
            items: { type: "string" },
            description:
              "Zod factory names to check. Defaults to the object-like composites; add `array` / `enum` to widen.",
          },
          ignoreTestFiles: {
            type: "boolean",
            description:
              "Skip test files, where a fixture schema belongs next to its assertion.",
          },
          memoCallees: {
            type: "array",
            items: { type: "string" },
            description:
              "Wrappers that construct their callback at most once. Defaults to lazy, memo, once, and useMemo.",
          },
          minProperties: {
            type: "number",
            minimum: 0,
            description:
              "Minimum key count before an object-like schema is reported.",
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      hoistSchema:
        "Move this `{{factory}}` schema to module scope. It uses nothing from `{{owner}}`, so it is rebuilt on every call for no benefit and cannot be exported, reused, or `z.infer`-ed from where it is.",
    },
  },
  defaultOptions: [{}],
  create(context, [options]) {
    const factories = new Set(options?.factories ?? DEFAULT_FACTORIES);
    const ignoreTestFiles = options?.ignoreTestFiles ?? true;
    const memoCallees = new Set(options?.memoCallees ?? MEMO_CALLEES);
    const minProperties = options?.minProperties ?? DEFAULT_MIN_PROPERTIES;

    const sourceCode = context.sourceCode;
    const filename = sourceOrigin(context).filename;
    if (isGeneratedFile(filename, sourceCode.getText())) {
      return {};
    }
    if (ignoreTestFiles && isTestFile(filename)) {
      return {};
    }

    const zodNamespaces = new Set<string>();

    function isZodCall(node: ESTree.Node): node is ESTree.CallExpression {
      return (
        node.type === "CallExpression" &&
        node.callee.type === "MemberExpression" &&
        !node.callee.computed &&
        node.callee.object.type === "Identifier" &&
        zodNamespaces.has(node.callee.object.name)
      );
    }

    function isSchemaConstruction(node: ESTree.CallExpression): boolean {
      const callee = node.callee;
      if (callee.type !== "MemberExpression" || callee.computed ||
        callee.property.type !== "Identifier" || TERMINAL_METHODS.has(callee.property.name)) return false;
      if (callee.object.type === "CallExpression") return isSchemaConstruction(callee.object);
      return isZodCall(node) && CONSTRUCTION_FACTORIES.has(callee.property.name);
    }

    function hasEagerComputation(node: ESTree.Node): boolean {
      return subtreeSome(node, (inner) =>
        inner.type === "NewExpression" ||
        inner.type === "TaggedTemplateExpression" ||
        (inner.type === "CallExpression" && !isSchemaConstruction(inner)), true);
    }

    function isCovered(node: ESTree.CallExpression): boolean {
      let current: ESTree.Node | null | undefined = node.parent ?? undefined;
      while (current != null) {
        if (
          current !== node &&
          isZodCall(current) &&
          current.callee.type === "MemberExpression" &&
          current.callee.property.type === "Identifier" &&
          factories.has(current.callee.property.name)
        ) {
          return true;
        }
        if (
          current.type === "CallExpression" &&
          ((current.callee.type === "Identifier" &&
            memoCallees.has(current.callee.name)) ||
            (current.callee.type === "MemberExpression" &&
              !current.callee.computed &&
              current.callee.property.type === "Identifier" &&
              memoCallees.has(current.callee.property.name)))
        ) {
          return true;
        }
        current = current.parent ?? undefined;
      }
      return false;
    }

    function outermostSchemaExpression(
      expression: ESTree.Node,
    ): ESTree.Node {
      let confirmed = expression;
      let current = expression;
      for (;;) {
        const parent: ESTree.Node | undefined = current.parent ?? undefined;
        if (parent == null) {
          return confirmed;
        }
        if (
          (parent.type === "Property" && parent.value === current) ||
          parent.type === "ObjectExpression" ||
          parent.type === "ArrayExpression"
        ) {
          current = parent;
          continue;
        }
        if (
          parent.type === "CallExpression" &&
          parent.arguments.includes(current as ESTree.Argument) &&
          isSchemaComposition(parent)
        ) {
          current = schemaExpression(parent);
          confirmed = current;
          continue;
        }
        return confirmed;
      }
    }

    /** A `z.*(…)` call, or a Zod combinator method applied to an existing schema. */
    function isSchemaComposition(node: ESTree.CallExpression): boolean {
      // The combinator test runs FIRST: `isZodCall` is a type predicate, so
      // putting it on the left of `||` narrows `node` to `never` in the right
      // operand and the member access stops compiling.
      const { callee } = node;
      const isCombinator =
        callee.type === "MemberExpression" &&
        !callee.computed &&
        callee.property.type === "Identifier" &&
        ZOD_COMBINATOR_METHODS.has(callee.property.name);
      return isCombinator || isZodCall(node);
    }

    /** No reference inside the schema resolves to a binding the function owns. */
    function closesOverNothing(
      node: ESTree.Node,
      enclosing: ESTree.Node,
    ): boolean {
      const references: Reference[] = [];
      collectReferences(sourceCode.getScope(node), references);
      const [schemaStart, schemaEnd] = node.range;
      const [functionStart, functionEnd] = enclosing.range;
      function hasSafeDefinitions(reference: Reference, resolved: Variable): boolean {
        for (const definition of resolved.defs) {
          if (definition.type === "ImportBinding") {
            const parent = reference.identifier.parent;
            if (
              parent?.type === "CallExpression" &&
              parent.callee === reference.identifier &&
              !zodNamespaces.has(reference.identifier.name)
            ) {
              return false;
            }
            continue;
          }
          if (
            definition.node.type === "VariableDeclarator" &&
            definition.node.parent?.type === "VariableDeclaration" &&
            definition.node.parent.kind !== "const"
          ) {
            return false;
          }
          const [defStart, defEnd] = definition.node.range;
          if (defStart >= schemaStart && defEnd <= schemaEnd) {
            continue;
          }
          if (defStart >= functionStart && defEnd <= functionEnd) {
            return false;
          }
        }
        return true;
      }

      for (const reference of references) {
        const [identifierStart] = reference.identifier.range;
        if (identifierStart < schemaStart || identifierStart >= schemaEnd) {
          continue;
        }
        const resolved = reference.resolved;
        if (resolved === null) {
          continue;
        }
        if (!hasSafeDefinitions(reference, resolved)) return false;
      }
      return true;
    }

    /** How the enclosing function should be named in the message. */
    function ownerName(enclosing: ESTree.Node): string {
      const parent = enclosing.parent ?? undefined;
      if (
        enclosing.type === "FunctionDeclaration" &&
        enclosing.id !== null
      ) {
        return enclosing.id.name;
      }
      if (
        parent != null &&
        parent.type === "VariableDeclarator" &&
        parent.id.type === "Identifier"
      ) {
        return parent.id.name;
      }
      if (
        parent != null &&
        (parent.type === "MethodDefinition" ||
          parent.type === "Property") &&
        parent.key.type === "Identifier"
      ) {
        return parent.key.name;
      }
      return "this function";
    }

    return {
      ImportDeclaration(node): void {
        if (!isZodModule(node.source.value)) {
          return;
        }
        for (const specifier of node.specifiers) {
          if (
            specifier.type === "ImportNamespaceSpecifier" ||
            specifier.type === "ImportDefaultSpecifier" ||
            (specifier.type === "ImportSpecifier" &&
              specifier.imported.type === "Identifier" &&
              specifier.imported.name === "z")
          ) {
            zodNamespaces.add(specifier.local.name);
          }
        }
      },
      CallExpression(node): void {
        if (zodNamespaces.size === 0 || !isZodCall(node)) {
          return;
        }
        const callee = node.callee as ESTree.MemberExpression;
        if (callee.property.type !== "Identifier") {
          return;
        }
        const factory = callee.property.name;
        if (!factories.has(factory)) {
          return;
        }
        const enclosing = outermostEnclosingFunction(node);
        if (enclosing === undefined) {
          return;
        }
        if (isCovered(node)) {
          return;
        }
        const shape = node.arguments[0];
        if (
          shape !== undefined &&
          shape.type === "ObjectExpression" &&
          shape.properties.length < minProperties
        ) {
          return;
        }
        const expression = schemaExpression(node);
        if (readsReceiver(expression)) {
          return;
        }
        if (buildsLocalizedText(expression)) {
          return;
        }
        const outermost = outermostSchemaExpression(expression);
        if (hasEagerComputation(outermost)) return;
        if (
          outermost !== expression &&
          (readsReceiver(outermost) ||
            buildsLocalizedText(outermost) ||
            !closesOverNothing(outermost, enclosing))
        ) {
          return;
        }
        if (!closesOverNothing(expression, enclosing)) {
          return;
        }
        context.report({
          node,
          messageId: "hoistSchema",
          data: { factory: `z.${factory}`, owner: ownerName(enclosing) },
        });
      },
    };
  },
});
