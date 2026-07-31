/**
 * @fileoverview Flag a Zod schema built INSIDE a function body when nothing in
 * that function is part of it. The schema is rebuilt from scratch on every
 * call, every request, every render.
 *
 * This is the Zod sibling of `prefer-module-level-constant`, and it exists
 * because that rule cannot reach here by construction: its hoist gate requires
 * every leaf of the initializer to be a LITERAL, and `z.object({ id:
 * z.string() })` is a call expression, so a schema never satisfies it. The two
 * rules are disjoint and share one rationale, in increasing order of severity:
 *
 * 1. Allocation. A Zod schema is not a literal — `z.object({...})` walks the
 *    shape, constructs a `ZodObject` plus one schema instance per key, and
 *    caches nothing. Doing that per request in a route handler, or per property
 *    read in a getter, is pure waste that a single hoist removes forever.
 * 2. Identity churn. A fresh schema object every render is a fresh reference
 *    every render, which silently defeats `useMemo`/`useEffect` dependency
 *    arrays and any resolver (`zodResolver`, `react-hook-form`) that compares
 *    schema identity to decide whether to re-validate.
 * 3. Discoverability. A schema buried in a function body cannot be exported,
 *    tested, reused, or `z.infer`-ed from. The next function that needs the
 *    same payload gets its own copy, and the copies drift — which is the defect
 *    `prefer-zod-infer` and `zod-naming-convention` also exist to prevent.
 *
 * WHAT FIRES — a call to one of the `factories` (default: the object-like
 * composites, see below) that sits inside a function and whose ENTIRE subtree
 * is free of anything the function owns. That last clause is the whole rule:
 * it is what makes "move this to module scope" provably correct rather than a
 * guess.
 *
 * DELIBERATELY NOT FLAGGED, each an FP class that was measured, not imagined:
 *
 *   - **It closes over a parameter, local, type parameter, or local type.**
 *     `function envelope<T extends z.ZodTypeAny>(inner: T) { return z.object({
 *     data: inner }) }` is a schema FACTORY, not a misplaced constant; hoisting
 *     it is a compile error. Resolved through the scope manager, so a TYPE
 *     reference counts too — `z.custom<Inner>()` where `Inner` is declared in
 *     the function body pins the schema there just as firmly as a value would.
 *   - **It reads `this` / `super` / `arguments`.** A schema inside a getter that
 *     splices in `this.base` belongs to the instance. Verified against a
 *     fixture rather than assumed: the free-variable check alone says
 *     `get s() { return z.object({ a: this.base }); }` is hoistable, and it is
 *     not, so `this` is a separate bail.
 *   - **It is already memoized** — wrapped in `useMemo`, `memo`, `once`, or
 *     `lazy`. The cost the rule is about has already been paid once.
 *   - **It is nested inside another Zod call.** Only the OUTERMOST factory in an
 *     expression is reported, so `z.array(z.object({...}))` is one finding, not
 *     two, and the `z.lazy(() => z.object({...}))` recursion idiom — whose
 *     callback exists precisely so the schema is NOT built eagerly — is never
 *     reported at all.
 *   - **An object schema with fewer than `minProperties` keys.** `z.object({})`
 *     as a placeholder shape, or a one-key `z.object({ reason: z.string()
 *     }).parse(body)` written inline at its only use, reads better where it is.
 *     `dub/apps/web/lib/ai/create-support-ticket.ts:28` (`inputSchema:
 *     z.object({})`) is the empty case; the default of 1 excludes it.
 *   - **Test files** (`ignoreTestFiles`, default true) and **generated files**.
 *     A schema inside a `describe` block is fixture data that belongs next to
 *     the assertion, and codegen re-emits its own layout on every run.
 *
 * `z.array` and `z.enum` are NOT in the default `factories` list even though
 * they measured 138 and 28 more hoistable hits. They are thin wrappers around
 * an already-built schema or a literal list; the allocation argument is much
 * weaker and the reports are mostly noise. Repos that want them can say so:
 * `{ factories: ["object", "array", "enum"] }`.
 *
 * NO AUTOFIX, for the same reason `prefer-module-level-constant` has none:
 * hoisting must choose an insertion point, may collide with an existing
 * module-scope name, and — where the schema references a module constant
 * declared BELOW the function — must also reorder the module to avoid a TDZ
 * error. All three are judgement calls, and a wrong automated hoist is worse
 * than a warning.
 *
 * MEASURED, rule as shipped, over 30,546 .ts/.tsx files in 17 repos (7
 * first-party plus zod, trpc, dub, openstatus, formbricks, documenso, unkey,
 * midday, papermark, cal.com); 3,644 of those files import Zod.
 *
 *   378 reports, in 12 of the 17 repos — openstatus 211, midday 60, unkey 30,
 *   formbricks 23, papermark 19, cal.com 18, dub 9, trpc 1, zod 1, plus 6
 *   across two of the seven first-party repos and 0 in the other five.
 *
 * The chain walk is worth 7 of those 378 on its own: reporting over the
 * `z.object` node alone produced 385, and the 7 extra were schemas whose
 * `.superRefine` / `.catch` argument closed over a parameter. Every one of them
 * is now a `valid` case in the tests.
 *
 * Public examples, read in full and confirmed:
 *   - `openstatus/packages/tinybird/src/client.ts` — 211 in one file, each
 *     inside a `public get pipeName()` accessor, so two `z.object`s are rebuilt
 *     on every property READ.
 *   - `unkey/web/internal/clickhouse/src/telemetry.ts:7` — `schema: z.object({
 *     request_id, time, runtime, platform, versions })` inside
 *     `insertSDKTelemetry(ch)`, rebuilt per insert.
 *   - `cal.com/packages/trpc/server/routers/viewer/admin/createCoupon.handler.ts:75`
 *     — `const schema = z.object({ promotionCode, couponId })` rebuilt per
 *     request and used once, on the next line.
 *   - `cal.com/apps/web/components/settings/SecondaryEmailModal.tsx:34` —
 *     `zodResolver(z.object({ email: emailSchema }))` in a component body: a
 *     new schema AND a new resolver on every render, cost 2 above.
 *   - `papermark/app/(ee)/api/workflows/[workflowId]/steps/route.ts:39,155,353`
 *     — the SAME `z.object({ workflowId, teamId })` written out three times in
 *     one file, once per handler. Cost 3, made literal.
 *
 * External coverage was checked before this rule was written, not after.
 * `ESLint#calculateConfigForFile` against the shipped `eslint.strict.mjs`
 * resolves 204 enabled rules; a fixture holding this exact pattern drew zero
 * reports from all of them — `prefer-module-level-constant` and
 * `unicorn/consistent-function-scoping` included. `eslint-plugin-zod@4.9.0`,
 * whose `prefer-nullish` and `no-any-schema` this change enables outright, has
 * no rule in this area either.
 */

import {
  AST_NODE_TYPES,
  ESLintUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

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

const DEFAULT_MIN_PROPERTIES = 1;

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

const FUNCTION_TYPES: ReadonlySet<AST_NODE_TYPES> = new Set([
  AST_NODE_TYPES.ArrowFunctionExpression,
  AST_NODE_TYPES.FunctionDeclaration,
  AST_NODE_TYPES.FunctionExpression,
]);

/**
 * The whole schema EXPRESSION, not just the factory call: climb out through
 * `.refine(...)`, `.superRefine(...)`, `.transform(...)`, `.default(...)` and
 * every other builder method applied to it.
 *
 * This is load-bearing, and it was a measured false positive before it existed.
 * `documenso/apps/remix/app/components/dialogs/sign-field-checkbox-dialog.tsx:32`
 * is `z.object({ values: ... }).superRefine((data, ctx) => { ...fieldMeta... })`
 * inside a component — the `z.object` subtree closes over nothing, but the
 * `superRefine` callback reads a component PROP, so the schema cannot move. The
 * free-variable check has to see the callback, which means it has to run over
 * the chain rather than over the factory call alone.
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

/** `this` / `super` / `arguments` anywhere inside pins the schema to its receiver. */
function readsReceiver(node: TSESTree.Node): boolean {
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
    if (
      candidate.type === AST_NODE_TYPES.ThisExpression ||
      candidate.type === AST_NODE_TYPES.Super ||
      (candidate.type === AST_NODE_TYPES.Identifier &&
        candidate.name === "arguments")
    ) {
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
  visit(node);
  return found;
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

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/tree/main/packages/typescript#${name}`,
)<Options, MessageIds>({
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

    /**
     * True when some ancestor between `node` and module scope already accounts
     * for this schema: a REPORTABLE Zod factory (so one expression yields one
     * finding, anchored at its outermost reportable node), or a memo wrapper
     * (`useMemo`, `memo`, `once`, `z.lazy`) that already pays the cost once.
     *
     * A Zod call that is NOT a reportable factory does not cover, which is what
     * keeps `z.array(z.object({...}))` reportable under the default options:
     * `z.array` is excluded from `factories`, and swallowing the `z.object`
     * inside it would silently drop the finding entirely.
     */
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
