/**
 * @fileoverview no-generic-json-parser — Parse known JSON fields with an object schema instead of an open JSON or record parser.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-generic-json-parser.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { unwrapExpression } from "./_unwrap-expression.js";
import { isZodModule } from "./_zod.js";

const OPEN_FACTORIES: ReadonlySet<string> = new Set(["any", "unknown", "json", "record", "partialRecord"]);
const WRAPPERS: ReadonlySet<string> = new Set(["optional", "nullable", "nullish", "default", "catch", "readonly", "brand", "describe", "meta"]);

export const NO_GENERIC_JSON_PARSER_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Parse known JSON fields with an object schema instead of an open JSON or record parser.",
  rationale: "An open JSON parser checks serialization or value kinds without declaring required fields, leaving application reads outside the validation contract.",
  remediation: "Define a focused z.object schema for the fields being read and infer its output type. Keep generic JSON at deliberate opaque forwarding or storage boundaries.",
  category: "correctness",
  limitations: [
    "Checks static property reads on direct or stable-const aliases of Zod parse/parseAsync outputs from json, any, unknown, record and partialRecord schemas. Resolves runtime Zod imports, local const schema aliases and identity-preserving schema wrappers.",
    "Dynamic dictionary indexing, opaque JSON forwarding/storage, imported schemas, recursive lazy definitions, custom validator implementations, mutable aliases, safeParse envelopes and transformation/refinement callbacks are excluded. Generated/vendor files are excluded; maintained tests are checked.",
    "The rule identifies a missing declared field contract; it does not infer all external payload fields or automatically change runtime validation.",
  ],
  examples: [
    { id: "open-record-read", title: "Generic validation does not declare the field", outcome: "match", files: [{ path: "src/request.ts", source: "import { z } from 'zod'; const JsonSchema = z.record(z.string(), z.unknown()); function load(raw: unknown) { const body = JsonSchema.parse(raw); return body.version; }" }], focusPath: "src/request.ts", expectedCount: 1, public: true },
    { id: "focused-record-read", title: "Declare only the fields being read", outcome: "no-match", files: [{ path: "src/request.ts", source: "import { z } from 'zod'; const VersionSchema = z.object({ version: z.number().int().positive() }); function load(raw: unknown) { return VersionSchema.parse(raw).version; }" }], focusPath: "src/request.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

export default createRule<[], "genericParser">({
  name: "no-generic-json-parser",
  documentation: NO_GENERIC_JSON_PARSER_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: NO_GENERIC_JSON_PARSER_DOCUMENTATION.summary },
    schema: [],
    messages: { genericParser: "The generic parser does not declare `{{field}}`; parse a focused object schema for the fields this code reads." },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text)) return {};
    const sourceCode = context.sourceCode;
    function binding(node: TSESTree.Identifier): TSESLint.Scope.Variable | null {
      return ASTUtils.findVariable(sourceCode.getScope(node), node.name);
    }
    function initializer(node: TSESTree.Identifier): TSESTree.Expression | null {
      const variable = binding(node);
      const definition = variable?.defs[0];
      if (variable?.defs.length !== 1 || definition?.node.type !== AST_NODE_TYPES.VariableDeclarator ||
        definition.node.parent.kind !== "const" || definition.node.init === null ||
        definition.node.range[1] >= node.range[0] || variable.references.some(reference => reference.isWrite() && !reference.init)) return null;
      return definition.node.init;
    }
    function parser(node: TSESTree.Node, seen = new Set<TSESTree.Node>(), awaited = false): TSESTree.CallExpression | null {
      node = unwrapExpression(node);
      if (seen.has(node)) return null;
      seen.add(node);
      if (node.type === AST_NODE_TYPES.AwaitExpression) return parser(node.argument, seen, true);
      if (node.type === AST_NODE_TYPES.Identifier) {
        const value = initializer(node);
        return value === null ? null : parser(value, seen, awaited);
      }
      if (node.type !== AST_NODE_TYPES.CallExpression || node.callee.type !== AST_NODE_TYPES.MemberExpression ||
        !["parse", "parseAsync"].includes(ASTUtils.getPropertyName(node.callee) ?? "")) return null;
      if (ASTUtils.getPropertyName(node.callee) === "parseAsync" && !awaited) return null;
      return openSchema(node.callee.object) ? node : null;
    }
function openSchema(node: TSESTree.Node, seen = new Set<TSESTree.Node>()): boolean {
      node = unwrapExpression(node);
      if (seen.has(node)) return false;
      seen.add(node);
      if (node.type === AST_NODE_TYPES.Identifier) {
        const value = initializer(node);
        return value !== null && openSchema(value, seen);
      }
      if (node.type !== AST_NODE_TYPES.CallExpression) return false;
      const name = factory(node.callee);
      if (name !== null) return OPEN_FACTORIES.has(name);
      const callee = unwrapExpression(node.callee);
      return callee.type === AST_NODE_TYPES.MemberExpression && WRAPPERS.has(ASTUtils.getPropertyName(callee) ?? "") && openSchema(callee.object, seen);
    }
function factory(node: TSESTree.Node): string | null {
      node = unwrapExpression(node);
      if (node.type === AST_NODE_TYPES.Identifier) {
        const definition = binding(node)?.defs[0]?.node;
        if (definition?.type !== AST_NODE_TYPES.ImportSpecifier || definition.parent.type !== AST_NODE_TYPES.ImportDeclaration || definition.importKind === "type" ||
          definition.parent.importKind === "type" || !isZodModule(definition.parent.source.value)) return null;
        return definition.imported.type === AST_NODE_TYPES.Identifier ? definition.imported.name : definition.imported.value;
      }
      if (node.type !== AST_NODE_TYPES.MemberExpression) return null;
      const receiver = unwrapExpression(node.object);
      if (receiver.type !== AST_NODE_TYPES.Identifier) return null;
      const definition = binding(receiver)?.defs[0]?.node;
      if (definition === undefined || (definition.type !== AST_NODE_TYPES.ImportSpecifier && definition.type !== AST_NODE_TYPES.ImportNamespaceSpecifier) || definition.parent.type !== AST_NODE_TYPES.ImportDeclaration ||
        definition.parent.importKind === "type" || !isZodModule(definition.parent.source.value)) return null;
      if (definition.type === AST_NODE_TYPES.ImportSpecifier && (definition.importKind === "type" ||
        (definition.imported.type === AST_NODE_TYPES.Identifier ? definition.imported.name : definition.imported.value) !== "z")) return null;
      return ASTUtils.getPropertyName(node);
    }
    const reported = new Set<TSESTree.CallExpression>();
    return {
      MemberExpression(node): void {
        const field = ASTUtils.getPropertyName(node);
        if (field === null) return;
        const call = parser(node.object);
        if (call === null || reported.has(call)) return;
        reported.add(call);
        context.report({ node: call, messageId: "genericParser", data: { field } });
      },
    };
  },
});
