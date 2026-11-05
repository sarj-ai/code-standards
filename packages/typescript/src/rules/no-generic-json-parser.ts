/**
 * @fileoverview no-generic-json-parser — Parse known JSON fields with an object schema instead of an open JSON or record parser.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-generic-json-parser.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";
import { directArgumentCall, outerExpression, unwrapExpression } from "./_unwrap-expression.js";
import { stableConstInitializer, stableValueBinding, typeOnlyReference, writtenMember } from "./_stable-value-binding.js";
import { successfulParseRead } from "./_successful-parse-read.js";
import { isZodModule } from "./_zod.js";

const OPEN_FACTORIES: ReadonlySet<string> = new Set(["any", "unknown", "json", "record", "partialRecord"]);
const WRAPPERS: ReadonlySet<string> = new Set(["optional", "nullable", "nullish", "default", "catch", "readonly", "brand", "describe", "meta"]);

export const NO_GENERIC_JSON_PARSER_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Parse known JSON fields with an object schema instead of an open JSON or record parser.",
  rationale: "An open JSON parser checks serialization or value kinds without declaring required fields, leaving application reads outside the validation contract.",
  remediation: "Define a focused z.object schema for the fields being read and infer its output type. Keep generic JSON at deliberate opaque forwarding or storage boundaries.",
  category: "correctness",
  requiresTypeInformation: false,
  runtimeImports: ["zod"],
  references: ["https://github.com/dmmulroy/anti-slop/blob/13909c9e07590f5a85d93c62712259fe14a883f7/src/rules/no-unsafe-dictionary-type.ts"],
  limitations: [
    "Checks static property reads on direct or stable-const aliases of Zod parse/parseAsync outputs and proven successful safeParse/awaited safeParseAsync data from json, any, unknown, record and partialRecord schemas. Resolves runtime Zod imports, local const schema aliases and identity-preserving schema wrappers.",
    "Dynamic dictionary indexing, opaque JSON forwarding/storage, imported schemas, recursive lazy definitions, custom validator implementations, mutable aliases, unproven success guards and transformation/refinement callbacks are excluded. Subsequent parser validation with a specific or unresolved contract and meaningful typed/finite-key records are preserved. Generated/vendor files are excluded; maintained tests are checked.",
    "The rule identifies a missing declared field contract; it does not infer all external payload fields or automatically change runtime validation.",
  ],
  examples: [
    { id: "open-record-read", title: "Generic validation does not declare the field", outcome: "match", files: [{ path: "src/request.ts", source: "import { z } from 'zod'; const JsonSchema = z.record(z.string(), z.unknown()); function load(raw: unknown) { const body = JsonSchema.parse(raw); return body.version; }" }], focusPath: "src/request.ts", expectedCount: 1, public: true },
    { id: "focused-record-read", title: "Declare only the fields being read", outcome: "no-match", files: [{ path: "src/request.ts", source: "import { z } from 'zod'; const VersionSchema = z.object({ version: z.number().int().positive() }); function load(raw: unknown) { return VersionSchema.parse(raw).version; }" }], focusPath: "src/request.ts", expectedCount: 0, public: true },
    {"id": "safe-parse-fields-before", "scenarioId": "safe-parse-fields", "title": "Validate the fields consumed after success — before", "outcome": "match", "files": [{"path": "src/example.ts", "source": "import { z } from 'zod'; function load(raw: unknown) { const result = z.record(z.string(), z.unknown()).safeParse(raw); if (!result.success) return; return result.data.id; }"}], "focusPath": "src/example.ts", "expectedCount": 1, "public": true},
    {"id": "safe-parse-fields-after", "scenarioId": "safe-parse-fields", "title": "Validate the fields consumed after success — after", "outcome": "no-match", "files": [{"path": "src/example.ts", "source": "import { z } from 'zod'; function load(raw: unknown) { const result = z.object({ id: z.string() }).safeParse(raw); if (!result.success) return; return result.data.id; }"}], "focusPath": "src/example.ts", "expectedCount": 0, "public": true},
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
    function initializer(node: TSESTree.Identifier): TSESTree.Expression | null {
      return stableConstInitializer(sourceCode, node)?.value ?? null;
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
      if (node.type === AST_NODE_TYPES.MemberExpression && ASTUtils.getPropertyName(node) === "data") {
        const call = safeParser(node.object);
        return call !== null && stableResult(node.object) &&
          successfulParseRead(node, call, value => safeParser(value)) ? call : null;
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
        return value !== null && stableSchema(node) && openSchema(value, seen);
      }
      if (node.type !== AST_NODE_TYPES.CallExpression) return false;
      const name = factory(node.callee);
      if (name === "record" || name === "partialRecord") {
        const key = node.arguments[0];
        const value = node.arguments[1] ?? key;
        const finiteKey = key?.type === AST_NODE_TYPES.CallExpression &&
          ["enum", "literal", "nativeEnum"].includes(factory(key.callee) ?? "");
        return !finiteKey && value !== undefined && openSchema(value, new Set(seen));
      }
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

    function binding(node: TSESTree.Identifier): TSESLint.Scope.Variable | null {
      return ASTUtils.findVariable(sourceCode.getScope(node), node.name);
    }
    function safeParser(node: TSESTree.Node, seen = new Set<TSESTree.Node>(), awaited = false): TSESTree.CallExpression | null {
      node = unwrapExpression(node);
      if (seen.has(node)) return null;
      seen.add(node);
      if (node.type === AST_NODE_TYPES.AwaitExpression) {
        const argument = unwrapExpression(node.argument);
        if (argument.type === AST_NODE_TYPES.Identifier) {
          const local = stableConstInitializer(sourceCode, argument);
          if (local === null || !local.variable.references.every(reference =>
            reference.init === true || typeOnlyReference(reference) || reference.identifier === argument)) return null;
        }
        return safeParser(argument, seen, true);
      }
      if (node.type === AST_NODE_TYPES.Identifier) {
        const value = initializer(node);
        return value === null ? null : safeParser(value, seen, awaited);
      }
      if (node.type !== AST_NODE_TYPES.CallExpression || node.callee.type !== AST_NODE_TYPES.MemberExpression) return null;
      const method = ASTUtils.getPropertyName(node.callee);
      if (method !== "safeParse" && method !== "safeParseAsync" ||
        method === "safeParseAsync" && !awaited) return null;
      return openSchema(node.callee.object) ? node : null;
    }
    function stableSchema(node: TSESTree.Identifier): boolean {
      const chain = new Set<TSESLint.Scope.Variable>();
      let root = stableConstInitializer(sourceCode, node);
      while (root !== null) {
        if (chain.has(root.variable)) return false;
        chain.add(root.variable);
        const value = unwrapExpression(root.value);
        if (value.type !== AST_NODE_TYPES.Identifier) return stableSchemaAliases(root.variable, new Set());
        root = stableConstInitializer(sourceCode, value);
      }
      return false;
    }
    function stableSchemaAliases(variable: TSESLint.Scope.Variable, seen: Set<TSESLint.Scope.Variable>): boolean {
      if (seen.has(variable)) return true;
      seen.add(variable);
      return stableValueBinding(variable) && variable.references.every(reference => {
        if (reference.init === true || typeOnlyReference(reference)) return true;
        if (reference.isWrite()) return false;
        const value = outerExpression(reference.identifier);
        const parent = value.parent;
        if (parent == null) return false;
        if (parent.type === AST_NODE_TYPES.MemberExpression && parent.object === value) {
          const name = ASTUtils.getPropertyName(parent);
          return !writtenMember(parent) && name !== null &&
            (WRAPPERS.has(name) || ["parse", "parseAsync", "safeParse", "safeParseAsync"].includes(name));
        }
        const alias = parent.type === AST_NODE_TYPES.VariableDeclarator && parent.init === value ? localAlias(parent) : undefined;
        return alias !== undefined && stableSchemaAliases(alias, seen);
      });
    }
    function opaqueReturn(node: TSESTree.Node): boolean {
      const value = outerExpression(node);
      if (value.parent == null || value.parent.type !== AST_NODE_TYPES.ReturnStatement &&
        !(value.parent.type === AST_NODE_TYPES.ArrowFunctionExpression && value.parent.body === value)) return false;
      for (let current: TSESTree.Node = value.parent; current.parent != null; current = current.parent) {
        if (current.type === AST_NODE_TYPES.FunctionDeclaration || current.type === AST_NODE_TYPES.FunctionExpression ||
          current.type === AST_NODE_TYPES.ArrowFunctionExpression)
          return current.returnType?.typeAnnotation.type === AST_NODE_TYPES.TSUnknownKeyword;
      }
      return false;
    }
    function validationArgument(node: TSESTree.Node): boolean {
      const call = directArgumentCall(node);
      return call !== null && call.arguments[0] === outerExpression(node) &&
        call.callee.type === AST_NODE_TYPES.MemberExpression &&
        ["parse", "parseAsync", "safeParse", "safeParseAsync"].includes(ASTUtils.getPropertyName(call.callee) ?? "") &&
        !openSchema(call.callee.object);
    }
    function validatedField(node: TSESTree.MemberExpression): boolean {
      if (validationArgument(node)) return true;
      const value = outerExpression(node);
      const parent = value.parent;
      if (parent == null) return false;
      if (parent.type !== AST_NODE_TYPES.VariableDeclarator || parent.init !== value ||
        parent.id.type !== AST_NODE_TYPES.Identifier || parent.parent.kind !== "const") return false;
      const identifier = parent.id;
      const variable = sourceCode.getDeclaredVariables(parent).find(candidate => candidate.identifiers.includes(identifier));
      return variable !== undefined && stableValueBinding(variable) &&
        variable.references.some(reference => reference.isRead()) &&
        variable.references.every(reference => reference.init === true || typeOnlyReference(reference) ||
          !reference.isWrite() && validationArgument(reference.identifier));
    }
    function localAlias(node: TSESTree.VariableDeclarator): TSESLint.Scope.Variable | undefined {
      if (node.parent.kind !== "const" || node.id.type !== AST_NODE_TYPES.Identifier) return undefined;
      const identifier = node.id;
      const variable = sourceCode.getDeclaredVariables(node).find(candidate => candidate.identifiers.includes(identifier));
      return variable !== undefined && stableValueBinding(variable) ? variable : undefined;
    }
    function stableData(variable: TSESLint.Scope.Variable, seen = new Set<TSESLint.Scope.Variable>()): boolean {
      if (seen.has(variable)) return true;
      seen.add(variable);
      return stableValueBinding(variable) && variable.references.every(reference => {
        if (reference.init === true || typeOnlyReference(reference)) return true;
        if (reference.isWrite()) return false;
        const value = outerExpression(reference.identifier);
        const parent = value.parent;
        if (parent == null) return false;
        if (parent.type === AST_NODE_TYPES.MemberExpression && parent.object === value) return !writtenMember(parent);
        if (validationArgument(value)) return true;
        const alias = parent.type === AST_NODE_TYPES.VariableDeclarator && parent.init === value ? localAlias(parent) : undefined;
        return alias !== undefined && stableData(alias, seen);
      });
    }
    function stableResult(node: TSESTree.Node): boolean {
      node = unwrapExpression(node);
      if (node.type !== AST_NODE_TYPES.Identifier) return false;
      const chain = new Set<TSESLint.Scope.Variable>();
      let root = stableConstInitializer(sourceCode, node);
      while (root !== null) {
        if (chain.has(root.variable)) return false;
        chain.add(root.variable);
        const value = unwrapExpression(root.value);
        if (value.type !== AST_NODE_TYPES.Identifier) return validResult(root.variable, new Set());
        root = stableConstInitializer(sourceCode, value);
      }
      return false;
    }
    function validResult(variable: TSESLint.Scope.Variable, seen: Set<TSESLint.Scope.Variable>): boolean {
      if (seen.has(variable)) return true;
      seen.add(variable);
      return stableValueBinding(variable) && variable.references.every(reference => {
        if (reference.init === true || typeOnlyReference(reference)) return true;
        if (reference.isWrite()) return false;
        const value = outerExpression(reference.identifier);
        const parent = value.parent;
        if (parent == null) return false;
        if (parent.type === AST_NODE_TYPES.VariableDeclarator && parent.init === value) {
          const alias = localAlias(parent);
          return alias !== undefined && validResult(alias, seen);
        }
        if (parent.type !== AST_NODE_TYPES.MemberExpression || parent.object !== value || writtenMember(parent)) return false;
        const key = ASTUtils.getPropertyName(parent);
        if (key === "success" || key === "error") return true;
        if (key !== "data") return false;
        const data = outerExpression(parent);
        const consumer = data.parent;
        if (consumer == null) return false;
        if (consumer.type === AST_NODE_TYPES.MemberExpression && consumer.object === data) return !writtenMember(consumer);
        if (validationArgument(data)) return true;
        const alias = consumer.type === AST_NODE_TYPES.VariableDeclarator && consumer.init === data ? localAlias(consumer) : undefined;
        return alias !== undefined && stableData(alias);
      });
    }
    const reported = new Set<TSESTree.CallExpression>();
    return {
      MemberExpression(node): void {
        const field = ASTUtils.getPropertyName(node);
        if (field === null || writtenMember(node) || validatedField(node) || opaqueReturn(node)) return;
        const call = parser(node.object);
        if (call === null || reported.has(call)) return;
        reported.add(call);
        context.report({ node: call, messageId: "genericParser", data: { field } });
      },
    };
  },
});
