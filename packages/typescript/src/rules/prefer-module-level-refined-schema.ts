/**
 * @fileoverview prefer-module-level-refined-schema — hoist closed, repeatedly refined Zod scalar and array schemas.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-module-level-refined-schema.test.ts
 */
import { AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { isZodModule } from "./_zod.js";

type MessageIds = "hoistRefinedSchema";
type Options = [];
const FACTORIES: ReadonlySet<string> = new Set([
  "array",
  "bigint",
  "boolean",
  "date",
  "number",
  "string",
]);
const REFINEMENTS: ReadonlySet<string> = new Set([
  "brand",
  "check",
  "email",
  "finite",
  "int",
  "length",
  "max",
  "min",
  "multipleOf",
  "nonempty",
  "positive",
  "regex",
  "refine",
  "safe",
  "superRefine",
  "transform",
  "trim",
  "url",
  "uuid",
]);

export const PREFER_MODULE_LEVEL_REFINED_SCHEMA_DOCUMENTATION = {
  summary: "Declare closed, refined Zod scalar and array schemas at module scope.",
  rationale: "A closed validation pipeline created inside a function is rebuilt on every invocation and obscures a reusable constraint.",
  remediation: "Move the validation schema to module scope and call parse on the shared schema.",
  category: "performance",
  limitations: ["Only direct Zod scalar/array chains with at least two refinement methods and no non-literal arguments are reported."],
  examples: [
    { id: "module-refinement", title: "Share the validation schema", outcome: "no-match", files: [{ path: "src/options.ts", source: "import { z } from 'zod'; const BatchSize = z.number().int().min(1).max(1000); export function parse(value: unknown) { return BatchSize.parse(value); }" }], focusPath: "src/options.ts", expectedCount: 0, public: true },
    { id: "local-refinement", title: "Do not rebuild a closed validation chain", outcome: "match", files: [{ path: "src/options.ts", source: "import { z } from 'zod'; export function parse(value: unknown) { return z.number().int().min(1).max(1000).parse(value); }" }], focusPath: "src/options.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

function enclosingFunction(node: TSESTree.Node): TSESTree.Node | undefined {
  let current = node.parent ?? undefined;
  while (current !== undefined) {
    if ([AST_NODE_TYPES.ArrowFunctionExpression, AST_NODE_TYPES.FunctionDeclaration, AST_NODE_TYPES.FunctionExpression].includes(current.type)) return current;
    current = current.parent ?? undefined;
  }
  return undefined;
}

function collectReferences(scope: TSESLint.Scope.Scope, output: TSESLint.Scope.Reference[]): void {
  output.push(...scope.references);
  for (const child of scope.childScopes) collectReferences(child, output);
}

export default createRule<Options, MessageIds>({
  name: "prefer-module-level-refined-schema",
  documentation: PREFER_MODULE_LEVEL_REFINED_SCHEMA_DOCUMENTATION,
  meta: { type: "suggestion", docs: { description: "Declare closed, refined Zod scalar and array schemas at module scope." }, schema: [], messages: { hoistRefinedSchema: "Move this closed refined Zod schema to module scope and reuse it for parsing." } },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    const namespaces = new Set<string>();
    return {
      ImportDeclaration(node): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) if (specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier || specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier ||
          (specifier.type === AST_NODE_TYPES.ImportSpecifier && specifier.imported.type === AST_NODE_TYPES.Identifier && specifier.imported.name === "z")) namespaces.add(specifier.local.name);
      },
      CallExpression(node): void {
        const enclosing = enclosingFunction(node);
        if (enclosing === undefined || node.parent?.type !== AST_NODE_TYPES.MemberExpression || node.parent.object !== node) return;
        if (node.callee.type !== AST_NODE_TYPES.MemberExpression || node.callee.computed || node.callee.object.type !== AST_NODE_TYPES.Identifier ||
          !namespaces.has(node.callee.object.name) || node.callee.property.type !== AST_NODE_TYPES.Identifier || !FACTORIES.has(node.callee.property.name)) return;
        let current: TSESTree.Node = node;
        let refinements = 0;
        while (current.parent?.type === AST_NODE_TYPES.MemberExpression && current.parent.object === current && !current.parent.computed && current.parent.property.type === AST_NODE_TYPES.Identifier &&
          current.parent.parent?.type === AST_NODE_TYPES.CallExpression && current.parent.parent.callee === current.parent) {
          const call: TSESTree.CallExpression = current.parent.parent;
          if (["parse", "parseAsync", "safeParse", "safeParseAsync"].includes(current.parent.property.name)) break;
          if (REFINEMENTS.has(current.parent.property.name)) refinements += 1;
          current = call;
        }
        if (refinements < 2) return;
        const references: TSESLint.Scope.Reference[] = [];
        collectReferences(context.sourceCode.getScope(current), references);
        const [start, end] = current.range;
        const [functionStart, functionEnd] = enclosing.range;
        for (const reference of references) {
          const [referenceStart] = reference.identifier.range;
          if (referenceStart < start || referenceStart >= end || reference.resolved === null) continue;
          for (const definition of reference.resolved.defs) {
            if (definition.type === "ImportBinding") continue;
            if (definition.node.type === AST_NODE_TYPES.VariableDeclarator && definition.node.parent.type === AST_NODE_TYPES.VariableDeclaration && definition.node.parent.kind !== "const") return;
            const [definitionStart, definitionEnd] = definition.node.range;
            if (definitionStart >= start && definitionEnd <= end) continue;
            if (definitionStart >= functionStart && definitionEnd <= functionEnd) return;
          }
        }
        context.report({ node, messageId: "hoistRefinedSchema" });
      },
    } satisfies TSESLint.RuleListener;
  },
});
