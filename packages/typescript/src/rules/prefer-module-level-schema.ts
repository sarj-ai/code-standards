/**
 * @fileoverview prefer-module-level-schema — a Zod schema built inside a function is rebuilt on every call, every request, every render.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-module-level-schema.test.ts
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/prefer-module-level-schema.md
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
