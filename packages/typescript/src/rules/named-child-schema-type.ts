/** @fileoverview named-child-schema-type — reuse the complete type of a named child passed to a Zod record. */
import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";
import { importSpecifierName } from "./_import-specifier-name.js";
import { isGeneratedFile } from "./_paths.js";

import { isZodModule } from "./_zod.js";

type MessageIds = "namedChildType";
type Options = readonly [];
const UNRESOLVED_TYPE_NODES: ReadonlySet<AST_NODE_TYPES> = new Set([
  AST_NODE_TYPES.TSTypeQuery, AST_NODE_TYPES.TSImportType, AST_NODE_TYPES.TSTypeParameter,
  AST_NODE_TYPES.TSAnyKeyword, AST_NODE_TYPES.TSUnknownKeyword,
]);

export const NAMED_CHILD_SCHEMA_TYPE_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Reference a named Zod record child's complete schema type instead of repeating its explicit annotation.",
  rationale: "Repeating a child schema's generic contract creates a second maintained declaration even though the record already uses that child at runtime.",
  remediation: "Replace only the matching record type argument with `typeof ChildSchema`; retain the outer annotation required by isolatedDeclarations and every runtime schema operation.",
  category: "maintainability",
  autofix: "none",
  limitations: [
    "Only direct module-level const z.record calls with two arguments, a ZodRecord annotation, and an earlier local const child with a complete explicit Zod type are inspected.",
    "The entire generic child annotation must match token for token; input/output, defaults, transforms, readonly modifiers and brands are never compared by output shape alone.",
    "Bare leaf types, broad ZodType constraints, type queries, imported or unqualified type references, annotation cycles, comments on the repeated argument, mutable bindings and generated files are excluded.",
    "Import aliases and namespace imports resolve through scope bindings. Independent public contract pins require review; this warning does not remove annotations or change runtime validation.",
  ],
  examples: [
    { id: "named-child", title: "Reference the named child contract", outcome: "no-match", files: [{ path: "src/record.ts", source: 'import { z } from "zod"; const KeySchema: z.ZodEnum<{ a: "a"; b: "b" }> = z.enum(["a", "b"]); export const RecordSchema: z.ZodRecord<typeof KeySchema, z.ZodString> = z.record(KeySchema, z.string());' }], focusPath: "src/record.ts", expectedCount: 0, public: true },
    { id: "copied-child", title: "Do not repeat the complete child annotation", outcome: "match", files: [{ path: "src/record.ts", source: 'import { z } from "zod"; const KeySchema: z.ZodEnum<{ a: "a"; b: "b" }> = z.enum(["a", "b"]); export const RecordSchema: z.ZodRecord<z.ZodEnum<{ a: "a"; b: "b" }>, z.ZodString> = z.record(KeySchema, z.string());' }], focusPath: "src/record.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

function isModuleConst(node: TSESTree.VariableDeclarator): boolean {
  if (node.parent.kind !== "const" || node.id.type !== AST_NODE_TYPES.Identifier) return false;
  const parent = node.parent.parent;
  return parent.type === AST_NODE_TYPES.Program ||
    (parent.type === AST_NODE_TYPES.ExportNamedDeclaration && parent.parent.type === AST_NODE_TYPES.Program);
}

export default createRule<Options, MessageIds>({
  name: "named-child-schema-type",
  documentation: NAMED_CHILD_SCHEMA_TYPE_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: NAMED_CHILD_SCHEMA_TYPE_DOCUMENTATION.summary },
    schema: [],
    messages: { namedChildType: "Use `typeof {{name}}` for this exact child contract; keep the outer schema annotation and runtime operations." },
  },
  defaultOptions: [],
  create(context) {
    const source = context.sourceCode;
    if (isGeneratedFile(context.filename, source.text)) return {};
    const namespaces = new Set<TSESLint.Scope.Variable>();
    const bindingOf = (node: TSESTree.Identifier): TSESLint.Scope.Variable | null =>
      ASTUtils.findVariable(source.getScope(node), node.name);

    function namespaceOf(type: TSESTree.TSTypeReference): TSESLint.Scope.Variable | null {
      if (type.typeName.type !== AST_NODE_TYPES.TSQualifiedName || type.typeName.left.type !== AST_NODE_TYPES.Identifier) return null;
      const binding = bindingOf(type.typeName.left);
      return binding !== null && namespaces.has(binding) ? binding : null;
    }

    function closedType(node: TSESTree.Node, namespace: TSESLint.Scope.Variable): boolean {
      if (UNRESOLVED_TYPE_NODES.has(node.type)) return false;
      if (node.type === AST_NODE_TYPES.TSTypeReference && namespaceOf(node) !== namespace) return false;
      return !forEachOwnAstChild(node, (child) => !closedType(child, namespace));
    }

    function inspectChild(argument: TSESTree.Node, repeated: TSESTree.TypeNode, namespace: TSESLint.Scope.Variable, parent: TSESTree.VariableDeclarator): void {
      if (argument.type !== AST_NODE_TYPES.Identifier || repeated.type !== AST_NODE_TYPES.TSTypeReference || repeated.typeArguments === undefined) return;
      if (repeated.typeName.type !== AST_NODE_TYPES.TSQualifiedName || /^(?:ZodType|ZodSchema|ZodTypeAny)$/u.test(repeated.typeName.right.name)) return;
      const variable = bindingOf(argument);
      const definition = variable?.defs.length === 1 ? variable.defs[0] : undefined;
      if (definition?.type !== "Variable" || !isModuleConst(definition.node)) return;
      const child = definition.node;
      if (child.id.type !== AST_NODE_TYPES.Identifier || child.init === null || child.range[0] >= parent.range[0]) return;
      const annotation = child.id.typeAnnotation?.typeAnnotation;
      if (annotation === undefined || factoryNamespace(child.init) !== namespace || !closedType(annotation, namespace)) return;
      if (source.getCommentsInside(repeated).length > 0 || source.getCommentsBefore(repeated).length > 0) return;
      const expected = source.getTokens(annotation);
      const actual = source.getTokens(repeated);
      if (expected.length !== actual.length || expected.some((token, index) => token.type !== actual[index]?.type || token.value !== actual[index]?.value)) return;
      context.report({ node: repeated, messageId: "namedChildType", data: { name: argument.name } });
    }

    function factoryNamespace(expression: TSESTree.Node): TSESLint.Scope.Variable | null {
      if (expression.type !== AST_NODE_TYPES.CallExpression || expression.callee.type !== AST_NODE_TYPES.MemberExpression) return null;
      const object = expression.callee.object;
      return object.type === AST_NODE_TYPES.Identifier ? bindingOf(object) : factoryNamespace(object);
    }

    return {
      ImportDeclaration(node): void {
        if (node.importKind === "type" || !isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (specifier.type !== AST_NODE_TYPES.ImportNamespaceSpecifier &&
            (specifier.type !== AST_NODE_TYPES.ImportSpecifier || specifier.importKind === "type" || importSpecifierName(specifier) !== "z")) continue;
          const binding = bindingOf(specifier.local);
          if (binding !== null) namespaces.add(binding);
        }
      },
      VariableDeclarator(node): void {
        if (!isModuleConst(node) || node.id.type !== AST_NODE_TYPES.Identifier || node.init?.type !== AST_NODE_TYPES.CallExpression) return;
        const call = node.init;
        if (call.arguments.length !== 2 || call.callee.type !== AST_NODE_TYPES.MemberExpression || call.callee.object.type !== AST_NODE_TYPES.Identifier || ASTUtils.getPropertyName(call.callee) !== "record") return;
        const annotation = node.id.typeAnnotation?.typeAnnotation;
        if (annotation?.type !== AST_NODE_TYPES.TSTypeReference || annotation.typeName.type !== AST_NODE_TYPES.TSQualifiedName || annotation.typeName.right.name !== "ZodRecord") return;
        const namespace = namespaceOf(annotation);
        if (namespace === null || bindingOf(call.callee.object) !== namespace || annotation.typeArguments?.params.length !== 2) return;
        for (const [index, argument] of call.arguments.entries()) {
          const repeated = annotation.typeArguments.params[index];
          if (repeated !== undefined) inspectChild(argument, repeated, namespace, node);
        }
      },
    };
  },
});
