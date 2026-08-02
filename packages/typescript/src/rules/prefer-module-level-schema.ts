/**
 * @fileoverview prefer-module-level-schema — a Zod schema built inside a function is rebuilt on every call, every request, every render.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-module-level-schema.test.ts
 */

import { AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { isZodModule } from "./_zod.js";

type MessageIds = "hoistSchema";

type Options = readonly [
  {
    factories?: readonly string[];
    ignoreTestFiles?: boolean;
    minProperties?: number;
  }?,
];

/**
 * The object-like composites. Each builds a container plus one schema instance
 * per member, so the per-call cost is real rather than notional.
 */
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

/**
 * Two, not one — the value the "deliberately not flagged" list has always
 * PROMISED and never delivered. The gate is `properties.length <
 * minProperties`, so a default of 1 excludes `z.object({})` and nothing else,
 * while the documented exemption is the one-key inline schema.
 */
const DEFAULT_MIN_PROPERTIES = 2;

/** Wrappers that already pay the construction cost exactly once. */
const MEMO_CALLEES: ReadonlySet<string> = new Set([
  "lazy",
  "memo",
  "once",
  "useMemo",
]);

/**
 * Methods that CONSUME a value rather than extend the schema. The chain walk
 * stops before them: `z.object({...}).parse(raw)` closes over `raw`, but `raw`
 * is the input, not part of the schema, and the schema in front of it hoists
 * perfectly well.
 */
const TERMINAL_METHODS: ReadonlySet<string> = new Set([
  "isNullable",
  "isOptional",
  "parse",
  "parseAsync",
  "safeParse",
  "safeParseAsync",
  "spa",
]);

/**
 * Zod combinator methods that take a schema and return a schema. An enclosing
 * one means the reported factory is a FRAGMENT of a larger schema expression
 * rather than a schema in its own right — `AstroConfigSchema.extend({ … })`
 * is not a `z.*` call, so `isZodCall` cannot see it, and the fragment inside it
 * was reported on its own.
 */
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

/**
 * Callees that render text in the CURRENTLY ACTIVE locale.
 *
 * A zero-argument `() => z.object({ otp: z.string().length(6, t`…`) })` exists
 * PRECISELY so the Lingui macro runs after `i18n.activate(locale)`.
 * `closesOverNothing` skips `ImportBinding` defs, so `t` was invisible and the
 * rule advised a hoist that freezes every validation message in whatever locale
 * happened to be active at module-eval time — a correctness regression, not
 * noise. A tagged template is the macro spelling every i18n library uses.
 */
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

const FUNCTION_TYPES: ReadonlySet<AST_NODE_TYPES> = new Set([
  AST_NODE_TYPES.ArrowFunctionExpression,
  AST_NODE_TYPES.FunctionDeclaration,
  AST_NODE_TYPES.FunctionExpression,
]);

/**
 * The whole schema EXPRESSION, not just the factory call: climb out through
 * `.refine(...)`, `.superRefine(...)`, `.transform(...)`, `.default(...)` and
 * every other builder method applied to it.
 */
function schemaExpression(node: TSESTree.CallExpression): TSESTree.Node {
  let current: TSESTree.Node = node;
  for (;;) {
    const parent: TSESTree.Node | undefined = current.parent ?? undefined;
    if (parent === undefined) {
      return current;
    }
    if (
      parent.type === AST_NODE_TYPES.MemberExpression &&
      parent.object === current &&
      !parent.computed &&
      parent.property.type === AST_NODE_TYPES.Identifier &&
      TERMINAL_METHODS.has(parent.property.name)
    ) {
      return current;
    }
    if (
      (parent.type === AST_NODE_TYPES.MemberExpression &&
        parent.object === current) ||
      (parent.type === AST_NODE_TYPES.CallExpression &&
        parent.callee === current) ||
      (parent.type === AST_NODE_TYPES.TSAsExpression &&
        parent.expression === current) ||
      (parent.type === AST_NODE_TYPES.TSNonNullExpression &&
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
  node: TSESTree.Node,
): TSESTree.Node | undefined {
  let outermost: TSESTree.Node | undefined;
  let current: TSESTree.Node | undefined = node.parent ?? undefined;
  while (current !== undefined) {
    if (FUNCTION_TYPES.has(current.type)) {
      outermost = current;
    }
    current = current.parent ?? undefined;
  }
  return outermost;
}

/** Does any node in `root`'s subtree satisfy `predicate`? */
function subtreeSome(
  root: TSESTree.Node,
  predicate: (node: TSESTree.Node) => boolean,
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
    const candidate = value as Partial<TSESTree.Node> & Record<string, unknown>;
    if (typeof candidate.type !== "string") {
      return;
    }
    if (predicate(candidate as TSESTree.Node)) {
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
function readsReceiver(node: TSESTree.Node): boolean {
  return subtreeSome(
    node,
    (inner) =>
      inner.type === AST_NODE_TYPES.ThisExpression ||
      inner.type === AST_NODE_TYPES.Super ||
      (inner.type === AST_NODE_TYPES.Identifier && inner.name === "arguments"),
  );
}

/**
 * Does the schema build a string whose VALUE depends on when it is evaluated?
 *
 * See `I18N_CALLEE_NAMES`. Hoisting such a schema moves the render from
 * call time to module-eval time, which is a behaviour change, not a
 * refactor — so this is a hard bail rather than a heuristic penalty.
 */
function buildsLocalizedText(node: TSESTree.Node): boolean {
  return subtreeSome(node, (inner) => {
    if (inner.type === AST_NODE_TYPES.TaggedTemplateExpression) {
      return true;
    }
    if (inner.type !== AST_NODE_TYPES.CallExpression) {
      return false;
    }
    const { callee } = inner;
    if (callee.type === AST_NODE_TYPES.Identifier) {
      return I18N_CALLEE_NAMES.has(callee.name);
    }
    return (
      callee.type === AST_NODE_TYPES.MemberExpression &&
      !callee.computed &&
      callee.object.type === AST_NODE_TYPES.Identifier &&
      I18N_RECEIVER_NAMES.has(callee.object.name)
    );
  });
}

function collectReferences(
  scope: TSESLint.Scope.Scope,
  out: TSESLint.Scope.Reference[],
): void {
  out.push(...scope.references);
  for (const child of scope.childScopes) {
    collectReferences(child, out);
  }
}

export default createRule<Options, MessageIds>({
  name: "prefer-module-level-schema",
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
    const minProperties = options?.minProperties ?? DEFAULT_MIN_PROPERTIES;

    const sourceCode = context.sourceCode;
    const filename = context.filename;
    if (isGeneratedFile(filename, sourceCode.getText())) {
      return {};
    }
    if (ignoreTestFiles && isTestFile(filename)) {
      return {};
    }

    const zodNamespaces = new Set<string>();

    function isZodCall(node: TSESTree.Node): node is TSESTree.CallExpression {
      return (
        node.type === AST_NODE_TYPES.CallExpression &&
        node.callee.type === AST_NODE_TYPES.MemberExpression &&
        !node.callee.computed &&
        node.callee.object.type === AST_NODE_TYPES.Identifier &&
        zodNamespaces.has(node.callee.object.name)
      );
    }

    function isCovered(node: TSESTree.CallExpression): boolean {
      let current: TSESTree.Node | undefined = node.parent ?? undefined;
      while (current !== undefined) {
        if (
          current !== node &&
          isZodCall(current) &&
          current.callee.type === AST_NODE_TYPES.MemberExpression &&
          current.callee.property.type === AST_NODE_TYPES.Identifier &&
          factories.has(current.callee.property.name)
        ) {
          return true;
        }
        if (
          current.type === AST_NODE_TYPES.CallExpression &&
          ((current.callee.type === AST_NODE_TYPES.Identifier &&
            MEMO_CALLEES.has(current.callee.name)) ||
            (current.callee.type === AST_NODE_TYPES.MemberExpression &&
              !current.callee.computed &&
              current.callee.property.type === AST_NODE_TYPES.Identifier &&
              MEMO_CALLEES.has(current.callee.property.name)))
        ) {
          return true;
        }
        current = current.parent ?? undefined;
      }
      return false;
    }

    /**
     * The OUTERMOST schema expression `expression` is a part of.
     *
     * `schemaExpression` climbs the builder chain hanging off the factory call;
     * this climbs the other axis — out of the shape object, the array, and the
     * argument list of whatever Zod construct encloses it. It exists because a
     * reported factory can be a FRAGMENT of a schema that does not itself move,
     * and prising one key's value out of an expression that is rebuilt per call
     * anyway saves nothing.
     */
    function outermostSchemaExpression(
      expression: TSESTree.Node,
    ): TSESTree.Node {
      // `confirmed` only advances past a Zod construct. Walking OUT of a shape
      // object is provisional until the call wrapping it turns out to be one:
      // `tool({ inputSchema: z.object({…}), execute })` also puts a schema in an
      // object literal, and treating that literal as the schema would inherit
      // `execute`'s free variables.
      let confirmed = expression;
      let current = expression;
      for (;;) {
        const parent: TSESTree.Node | undefined = current.parent ?? undefined;
        if (parent === undefined) {
          return confirmed;
        }
        if (
          (parent.type === AST_NODE_TYPES.Property && parent.value === current) ||
          parent.type === AST_NODE_TYPES.ObjectExpression ||
          parent.type === AST_NODE_TYPES.ArrayExpression
        ) {
          current = parent;
          continue;
        }
        if (
          parent.type === AST_NODE_TYPES.CallExpression &&
          parent.arguments.includes(current as TSESTree.CallExpressionArgument) &&
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
    function isSchemaComposition(node: TSESTree.CallExpression): boolean {
      // The combinator test runs FIRST: `isZodCall` is a type predicate, so
      // putting it on the left of `||` narrows `node` to `never` in the right
      // operand and the member access stops compiling.
      const { callee } = node;
      const isCombinator =
        callee.type === AST_NODE_TYPES.MemberExpression &&
        !callee.computed &&
        callee.property.type === AST_NODE_TYPES.Identifier &&
        ZOD_COMBINATOR_METHODS.has(callee.property.name);
      return isCombinator || isZodCall(node);
    }

    /** No reference inside the schema resolves to a binding the function owns. */
    function closesOverNothing(
      node: TSESTree.Node,
      enclosing: TSESTree.Node,
    ): boolean {
      const references: TSESLint.Scope.Reference[] = [];
      collectReferences(sourceCode.getScope(node), references);
      const [schemaStart, schemaEnd] = node.range;
      const [functionStart, functionEnd] = enclosing.range;
      for (const reference of references) {
        const [identifierStart] = reference.identifier.range;
        if (identifierStart < schemaStart || identifierStart >= schemaEnd) {
          continue;
        }
        const resolved = reference.resolved;
        if (resolved === null) {
          continue;
        }
        for (const definition of resolved.defs) {
          if (definition.type === "ImportBinding") {
            continue;
          }
          const [defStart, defEnd] = definition.node.range;
          // A binding declared INSIDE the schema travels with it. The callback
          // parameters of `.refine((value) => …)` / `.superRefine((data, ctx) =>
          // …)` / `z.preprocess((value) => …, …)` are the whole class, and the
          // enclosing-range test alone answered "this closes over the function"
          // for every one of them — so any schema carrying a refinement was
          // silently unreportable. What the documented `documenso` case actually
          // needs is the callback reading an OUTER binding, and that still
          // resolves outside this range and still bails.
          if (defStart >= schemaStart && defEnd <= schemaEnd) {
            continue;
          }
          if (defStart >= functionStart && defEnd <= functionEnd) {
            return false;
          }
        }
      }
      return true;
    }

    /** How the enclosing function should be named in the message. */
    function ownerName(enclosing: TSESTree.Node): string {
      const parent = enclosing.parent ?? undefined;
      if (
        enclosing.type === AST_NODE_TYPES.FunctionDeclaration &&
        enclosing.id !== null
      ) {
        return enclosing.id.name;
      }
      if (
        parent !== undefined &&
        parent.type === AST_NODE_TYPES.VariableDeclarator &&
        parent.id.type === AST_NODE_TYPES.Identifier
      ) {
        return parent.id.name;
      }
      if (
        parent !== undefined &&
        (parent.type === AST_NODE_TYPES.MethodDefinition ||
          parent.type === AST_NODE_TYPES.Property) &&
        parent.key.type === AST_NODE_TYPES.Identifier
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
            specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier ||
            specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier ||
            (specifier.type === AST_NODE_TYPES.ImportSpecifier &&
              specifier.imported.type === AST_NODE_TYPES.Identifier &&
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
        const callee = node.callee as TSESTree.MemberExpression;
        if (callee.property.type !== AST_NODE_TYPES.Identifier) {
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
          shape.type === AST_NODE_TYPES.ObjectExpression &&
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
        // A fragment of a schema that cannot itself move is not reportable: the
        // enclosing expression is rebuilt on every call whatever we do to this
        // sub-schema. Only checked when an enclosing construct actually exists,
        // so `z.array(z.object({…}))` — where the whole expression IS hoistable
        // and `z.array` is not itself reportable — keeps reporting the inner
        // `z.object`, as the paired regression test requires.
        const outermost = outermostSchemaExpression(expression);
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
