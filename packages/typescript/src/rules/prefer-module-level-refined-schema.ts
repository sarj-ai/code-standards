/**
 * @fileoverview prefer-module-level-refined-schema — hoist closed Zod scalar, format, and wrapper schemas.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-module-level-refined-schema.test.ts
 */
import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { isZodModule } from "./_zod.js";

type MessageIds = "hoistRefinedSchema";
type Options = [];

const BENCHMARK_PATH_RE = /(^|[/\\])(?:benchmarks?|bench)[/\\]/;

// Factories already owned by prefer-module-level-schema stay out of this rule.
// lazy is intentionally absent because its callback defers construction.
const FACTORIES: ReadonlySet<string> = new Set([
  "array", "base64", "base64url", "bigint", "boolean", "cidrv4",
  "cidrv6", "codec", "custom", "date", "datetime", "duration", "email",
  "emoji", "enum", "file",
  "function", "hash", "hex", "hostname", "instanceof", "ipv4", "ipv6",
  "json", "jwt", "literal", "map", "nan", "nativeEnum", "never", "null",
  "nullable", "nullish", "number", "optional", "partialRecord", "preprocess",
  "promise", "set", "string", "stringbool", "symbol", "templateLiteral",
  "time", "undefined", "url", "uuid", "void",
]);
const COMPOSITE_FACTORIES: ReadonlySet<string> = new Set([
  "discriminatedUnion", "intersection", "looseObject", "object", "record",
  "strictObject", "tuple", "union",
]);
const FACTORY_NAMESPACES: ReadonlySet<string> = new Set(["coerce", "iso"]);
const NON_SCHEMA_TERMINALS: ReadonlySet<string> = new Set([
  "decode", "decodeAsync", "encode", "encodeAsync", "flattenError",
  "formatError", "implement", "isNullable", "isOptional", "parse",
  "parseAsync", "prettifyError", "registry", "safeDecode",
  "safeDecodeAsync", "safeEncode", "safeEncodeAsync", "safeParse",
  "safeParseAsync", "spa", "toJSONSchema", "treeifyError",
]);
const MEMO_CALLEES: ReadonlySet<string> = new Set([
  "lazy", "memo", "once", "useMemo",
]);
const I18N_CALLEE_NAMES: ReadonlySet<string> = new Set([
  "$t", "defineMessage", "gettext", "msg", "ngettext", "t", "translate",
]);
const I18N_RECEIVER_NAMES: ReadonlySet<string> = new Set([
  "$i18n", "i18n", "intl",
]);
const FUNCTION_TYPES: ReadonlySet<AST_NODE_TYPES> = new Set([
  AST_NODE_TYPES.ArrowFunctionExpression,
  AST_NODE_TYPES.FunctionDeclaration,
  AST_NODE_TYPES.FunctionExpression,
]);

export const PREFER_MODULE_LEVEL_REFINED_SCHEMA_DOCUMENTATION = {
  summary:
    "Declare closed Zod scalar, format, and wrapper schemas at module scope.",
  rationale:
    "A closed validation pipeline created inside a function is rebuilt on every invocation and obscures a reusable constraint.",
  remediation:
    "Move the validation schema to module scope, name it with a PascalCase Schema suffix, and call parse on the shared schema.",
  category: "performance",
  limitations: [
    "Composite object/record/tuple/union schemas are owned by prefer-module-level-schema.",
    "Schemas that depend on function-local or mutable state, localized text, receiver state, lazy construction, or recognized memoization are excluded.",
    "Literal string z.enum domains are owned by prefer-shared-zod-enum.",
  ],
  examples: [
    {
      id: "module-refinement",
      title: "Share the validation schema",
      outcome: "no-match",
      files: [{
        path: "src/options.ts",
        source: "import { z } from 'zod'; const BatchSizeSchema = z.number().int().min(1).max(1000); export function parse(value: unknown) { return BatchSizeSchema.parse(value); }",
      }],
      focusPath: "src/options.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "local-refinement",
      title: "Do not rebuild a closed validation chain",
      outcome: "match",
      files: [{
        path: "src/options.ts",
        source: "import { z } from 'zod'; export function parse(value: unknown) { return z.string().trim().min(1).max(128).parse(value); }",
      }],
      focusPath: "src/options.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function outermostEnclosingFunction(
  node: TSESTree.Node,
): TSESTree.Node | undefined {
  let outermost: TSESTree.Node | undefined;
  let current = node.parent ?? undefined;
  while (current !== undefined) {
    if (FUNCTION_TYPES.has(current.type)) outermost = current;
    current = current.parent ?? undefined;
  }
  return outermost;
}

function collectReferences(
  scope: TSESLint.Scope.Scope,
  output: TSESLint.Scope.Reference[],
): void {
  output.push(...scope.references);
  for (const child of scope.childScopes) collectReferences(child, output);
}

function subtreeSome(
  root: TSESTree.Node,
  predicate: (node: TSESTree.Node) => boolean,
): boolean {
  let found = false;
  const visit = (value: unknown): void => {
    if (found || value === null || typeof value !== "object") return;
    if (Array.isArray(value)) {
      for (const item of value) visit(item);
      return;
    }
    const candidate = value as Partial<TSESTree.Node> & Record<string, unknown>;
    if (typeof candidate.type !== "string") return;
    if (predicate(candidate as TSESTree.Node)) {
      found = true;
      return;
    }
    for (const key of Object.keys(candidate)) {
      if (key === "parent" || key === "loc" || key === "range") continue;
      visit(candidate[key]);
    }
  };
  visit(root);
  return found;
}

function readsReceiver(node: TSESTree.Node): boolean {
  return subtreeSome(
    node,
    (inner) =>
      inner.type === AST_NODE_TYPES.ThisExpression ||
      inner.type === AST_NODE_TYPES.Super ||
      (inner.type === AST_NODE_TYPES.Identifier && inner.name === "arguments"),
  );
}

function buildsLocalizedText(node: TSESTree.Node): boolean {
  return subtreeSome(node, (inner) => {
    if (inner.type === AST_NODE_TYPES.TaggedTemplateExpression) return true;
    if (inner.type !== AST_NODE_TYPES.CallExpression) return false;
    const { callee } = inner;
    if (callee.type === AST_NODE_TYPES.Identifier)
      return I18N_CALLEE_NAMES.has(callee.name);
    return (
      callee.type === AST_NODE_TYPES.MemberExpression &&
      !callee.computed &&
      callee.object.type === AST_NODE_TYPES.Identifier &&
      I18N_RECEIVER_NAMES.has(callee.object.name)
    );
  });
}

function calleeChainRoot(node: TSESTree.Node): TSESTree.Identifier | null {
  let current = node;
  for (;;) {
    if (current.type === AST_NODE_TYPES.Identifier) return current;
    if (current.type === AST_NODE_TYPES.MemberExpression) {
      current = current.object;
      continue;
    }
    if (current.type === AST_NODE_TYPES.CallExpression) {
      current = current.callee;
      continue;
    }
    return null;
  }
}

function chainMemberNames(node: TSESTree.Node): readonly string[] {
  const names: string[] = [];
  let current = node;
  for (;;) {
    if (current.type === AST_NODE_TYPES.MemberExpression) {
      if (current.computed || current.property.type !== AST_NODE_TYPES.Identifier)
        return [];
      names.push(current.property.name);
      current = current.object;
      continue;
    }
    if (current.type === AST_NODE_TYPES.CallExpression) {
      current = current.callee;
      continue;
    }
    break;
  }
  names.reverse();
  return names;
}

function schemaExpression(node: TSESTree.CallExpression): TSESTree.Node {
  let current: TSESTree.Node = node;
  for (;;) {
    const parent: TSESTree.Node | undefined = current.parent ?? undefined;
    if (
      parent?.type === AST_NODE_TYPES.MemberExpression &&
      parent.object === current &&
      !parent.computed &&
      parent.property.type === AST_NODE_TYPES.Identifier &&
      parent.parent?.type === AST_NODE_TYPES.CallExpression &&
      parent.parent.callee === parent
    ) {
      if (NON_SCHEMA_TERMINALS.has(parent.property.name)) return current;
      current = parent.parent;
      continue;
    }
    if (
      parent?.type === AST_NODE_TYPES.TSAsExpression ||
      parent?.type === AST_NODE_TYPES.TSNonNullExpression ||
      parent?.type === AST_NODE_TYPES.TSSatisfiesExpression ||
      parent?.type === AST_NODE_TYPES.TSTypeAssertion
    ) {
      current = parent;
      continue;
    }
    return current;
  }
}

export default createRule<Options, MessageIds>({
  name: "prefer-module-level-refined-schema",
  documentation: PREFER_MODULE_LEVEL_REFINED_SCHEMA_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Declare closed Zod scalar, format, and wrapper schemas at module scope.",
    },
    schema: [],
    messages: {
      hoistRefinedSchema:
        "Move this closed Zod schema to module scope, give it a PascalCase Schema name, and reuse it for parsing.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (
      isTestFile(context.filename) ||
      BENCHMARK_PATH_RE.test(context.filename) ||
      isGeneratedFile(context.filename, context.sourceCode.text)
    )
      return {};

    const zodBindings = new Set<TSESLint.Scope.Variable>();

    function resolvedBinding(
      identifier: TSESTree.Identifier,
    ): TSESLint.Scope.Variable | null {
      return ASTUtils.findVariable(
        context.sourceCode.getScope(identifier),
        identifier.name,
      );
    }

    function recordZodBinding(identifier: TSESTree.Identifier): void {
      const binding = resolvedBinding(identifier);
      if (binding !== null) zodBindings.add(binding);
    }

    function factoryName(
      node: TSESTree.CallExpression,
      allowed: ReadonlySet<string>,
    ): string | null {
      if (node.callee.type !== AST_NODE_TYPES.MemberExpression) return null;
      const root = calleeChainRoot(node.callee);
      if (root === null) return null;
      const binding = resolvedBinding(root);
      if (binding === null || !zodBindings.has(binding)) return null;
      const names = chainMemberNames(node.callee);
      if (names.length === 1 && allowed.has(names[0] ?? ""))
        return names[0] ?? null;
      if (
        names.length === 2 &&
        FACTORY_NAMESPACES.has(names[0] ?? "") &&
        allowed.has(names[1] ?? "")
      )
        return names[1] ?? null;
      return null;
    }

    function isSharedEnumDomain(
      node: TSESTree.CallExpression,
      factory: string,
    ): boolean {
      if (factory !== "enum") return false;
      const [argument] = node.arguments;
      return (
        argument?.type === AST_NODE_TYPES.ArrayExpression &&
        argument.elements.length >= 2 &&
        argument.elements.every(
          (element) =>
            element?.type === AST_NODE_TYPES.Literal &&
            typeof element.value === "string",
        )
      );
    }

    function isNestedInOwnedFactory(node: TSESTree.CallExpression): boolean {
      let current: TSESTree.Node = node;
      while (current.parent != null) {
        current = current.parent;
        if (FUNCTION_TYPES.has(current.type)) return false;
        if (
          current.type === AST_NODE_TYPES.CallExpression &&
          (factoryName(current, FACTORIES) !== null ||
            factoryName(current, COMPOSITE_FACTORIES) !== null)
        )
          return true;
      }
      return false;
    }

    function isMemoized(node: TSESTree.Node): boolean {
      let current = node.parent ?? undefined;
      while (current !== undefined) {
        if (
          current.type === AST_NODE_TYPES.CallExpression &&
          ((current.callee.type === AST_NODE_TYPES.Identifier &&
            MEMO_CALLEES.has(current.callee.name)) ||
            (current.callee.type === AST_NODE_TYPES.MemberExpression &&
              !current.callee.computed &&
              current.callee.property.type === AST_NODE_TYPES.Identifier &&
              MEMO_CALLEES.has(current.callee.property.name)))
        )
          return true;
        current = current.parent ?? undefined;
      }
      return false;
    }

    function closesOverNothing(
      node: TSESTree.Node,
      enclosing: TSESTree.Node,
    ): boolean {
      const references: TSESLint.Scope.Reference[] = [];
      collectReferences(context.sourceCode.getScope(node), references);
      const [start, end] = node.range;
      const [functionStart, functionEnd] = enclosing.range;
      for (const reference of references) {
        const [referenceStart] = reference.identifier.range;
        if (referenceStart < start || referenceStart >= end) continue;
        const resolved = reference.resolved;
        if (resolved === null) continue;
        for (const definition of resolved.defs) {
          if (definition.type === "ImportBinding") {
            const parent = reference.identifier.parent;
            if (
              parent?.type === AST_NODE_TYPES.CallExpression &&
              parent.callee === reference.identifier &&
              !zodBindings.has(resolved)
            )
              return false;
            continue;
          }
          if (
            definition.node.type === AST_NODE_TYPES.VariableDeclarator &&
            definition.node.parent.type === AST_NODE_TYPES.VariableDeclaration &&
            definition.node.parent.kind !== "const"
          )
            return false;
          const [definitionStart, definitionEnd] = definition.node.range;
          if (definitionStart >= start && definitionEnd <= end) continue;
          if (
            definitionStart >= functionStart &&
            definitionEnd <= functionEnd
          )
            return false;
        }
      }
      return true;
    }

    return {
      ImportDeclaration(node): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier ||
            specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier ||
            (specifier.type === AST_NODE_TYPES.ImportSpecifier &&
              (specifier.imported.type === AST_NODE_TYPES.Identifier
                ? specifier.imported.name === "z"
                : specifier.imported.value === "z"))
          )
            recordZodBinding(specifier.local);
        }
      },
      CallExpression(node): void {
        const factory = factoryName(node, FACTORIES);
        if (
          factory === null ||
          isSharedEnumDomain(node, factory) ||
          isNestedInOwnedFactory(node) ||
          isMemoized(node)
        )
          return;
        const enclosing = outermostEnclosingFunction(node);
        if (enclosing === undefined) return;
        const expression = schemaExpression(node);
        if (
          readsReceiver(expression) ||
          buildsLocalizedText(expression) ||
          !closesOverNothing(expression, enclosing)
        )
          return;
        context.report({ node, messageId: "hoistRefinedSchema" });
      },
    } satisfies TSESLint.RuleListener;
  },
});
