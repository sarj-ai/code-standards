/**
 * @fileoverview named-child-schema-type — reuse the complete type of a named child passed to a Zod record.
 *
 * Port of the 18.x `named-child-schema-type` rule. Same algorithm; the
 * generated-file gate runs in `before()`, which also resets the per-file Zod
 * namespaces. Oxlint sets an absent `typeArguments` to `null` where TS-ESTree
 * leaves it `undefined`; both count as absent here.
 */

import { defineRule, type ESTree, type Identifier, type Node, type SourceCode, type TsVariable } from "../types.js";
import { forEachOwnAstChild, parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { isZodModule } from "../utils/zod.js";

const NAME = "named-child-schema-type";

const UNRESOLVED_TYPE_NODES: ReadonlySet<string> = new Set([
  "TSTypeQuery", "TSImportType", "TSTypeParameter",
  "TSAnyKeyword", "TSUnknownKeyword",
]);

function isModuleConst(node: ESTree.VariableDeclarator): boolean {
  const declaration = parentOf(node) as ESTree.VariableDeclaration;
  if (declaration.kind !== "const" || node.id.type !== "Identifier") return false;
  const parent = parentOf(declaration);
  return parent?.type === "Program" ||
    (parent?.type === "ExportNamedDeclaration" && parentOf(parent)?.type === "Program");
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: { description: "Reference a named Zod record child's complete schema type instead of repeating its explicit annotation.", url: docsUrl(NAME) },
    schema: [],
    messages: { namedChildType: "Use `typeof {{name}}` or one shared named type alias for this exact child contract; keep the outer schema annotation and runtime operations." },
  },
  createOnce(context) {
    let source: SourceCode;
    let namespaces = new Set<TsVariable>();
    const bindingOf = (node: Identifier): TsVariable | null =>
      findVariable(source.getScope(node), node.name);

    function namespaceOf(type: ESTree.TSTypeReference): TsVariable | null {
      if (type.typeName.type !== "TSQualifiedName" || type.typeName.left.type !== "Identifier") return null;
      const binding = bindingOf(type.typeName.left);
      return binding !== null && namespaces.has(binding) ? binding : null;
    }

    function closedType(node: Node, namespace: TsVariable): boolean {
      if (UNRESOLVED_TYPE_NODES.has(node.type)) return false;
      if (node.type === "TSTypeReference" && namespaceOf(node) !== namespace) return false;
      return !forEachOwnAstChild(node, (child) => !closedType(child, namespace));
    }

    function inspectChild(argument: Node, repeated: ESTree.TSType, namespace: TsVariable, parent: ESTree.VariableDeclarator): void {
      if (argument.type !== "Identifier" || repeated.type !== "TSTypeReference" || (repeated.typeArguments === undefined || repeated.typeArguments === null)) return;
      if (repeated.typeName.type !== "TSQualifiedName" || /^(?:ZodType|ZodSchema|ZodTypeAny)$/u.test(repeated.typeName.right.name)) return;
      const annotation = earlierChildAnnotation(argument, namespace, parent);
      if (annotation === null || source.getCommentsInside(repeated).length > 0 || source.getCommentsBefore(repeated).length > 0) return;
      if (!sameTokens(annotation, repeated)) return;
      context.report({
        node: repeated,
        messageId: "namedChildType",
        data: { name: argument.name },
        fix: (fixer) => fixer.replaceText(repeated, `typeof ${source.getText(argument)}`),
      });
    }

    /** The closed explicit annotation of a module schema `argument` names, declared above `parent` from the same namespace. */
    function earlierChildAnnotation(argument: Identifier, namespace: TsVariable, parent: ESTree.VariableDeclarator): ESTree.TSType | null {
      const variable = bindingOf(argument);
      const definition = variable?.defs.length === 1 ? variable.defs[0] : undefined;
      if (definition?.type !== "Variable" || !isModuleConst(definition.node as ESTree.VariableDeclarator)) return null;
      const child = definition.node as ESTree.VariableDeclarator;
      if (child.id.type !== "Identifier" || child.init === null || child.range[0] >= parent.range[0]) return null;
      const annotation = child.id.typeAnnotation?.typeAnnotation;
      if (annotation === undefined || factoryNamespace(child.init) !== namespace || !closedType(annotation, namespace)) return null;
      return annotation;
    }

    function sameTokens(expected: Node, actual: Node): boolean {
      const expectedTokens = source.getTokens(expected);
      const actualTokens = source.getTokens(actual);
      return expectedTokens.length === actualTokens.length && expectedTokens.every((token, index) =>
        token.type === actualTokens[index]?.type && token.value === actualTokens[index]?.value);
    }

    function factoryNamespace(expression: Node): TsVariable | null {
      if (expression.type !== "CallExpression" || expression.callee.type !== "MemberExpression") return null;
      const object = expression.callee.object;
      return object.type === "Identifier" ? bindingOf(object) : factoryNamespace(object);
    }

    /** `const X: z.ZodRecord<K, V> = z.record(k, v)` at module level, both from one Zod namespace. */
    function annotatedRecord(node: ESTree.VariableDeclarator) {
      const call = node.init;
      if (call?.type !== "CallExpression" || call.arguments.length !== 2 || !isModuleConst(node) || node.id.type !== "Identifier") return null;
      const { callee } = call;
      if (callee.type !== "MemberExpression" || callee.object.type !== "Identifier" || getPropertyName(callee) !== "record") return null;
      const annotation = zodRecordAnnotation(node.id.typeAnnotation?.typeAnnotation);
      if (annotation === null || bindingOf(callee.object) !== annotation.namespace) return null;
      return { call, ...annotation };
    }

    /** `z.ZodRecord<K, V>` and the Zod namespace binding it is qualified by. */
    function zodRecordAnnotation(annotation: ESTree.TSType | undefined) {
      if (annotation?.type !== "TSTypeReference" || annotation.typeName.type !== "TSQualifiedName" || annotation.typeName.right.name !== "ZodRecord") return null;
      const namespace = namespaceOf(annotation);
      if (namespace === null || annotation.typeArguments?.params.length !== 2) return null;
      return { namespace, typeArguments: annotation.typeArguments.params };
    }

    return {
      before(): boolean | void {
        source = context.sourceCode;
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, source.text)) return false;
        namespaces = new Set<TsVariable>();
      },
      ImportDeclaration(node: ESTree.ImportDeclaration): void {
        if (node.importKind === "type" || !isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (specifier.type !== "ImportNamespaceSpecifier" &&
            (specifier.type !== "ImportSpecifier" || specifier.importKind === "type" || importSpecifierName(specifier) !== "z")) continue;
          const binding = bindingOf(specifier.local);
          if (binding !== null) namespaces.add(binding);
        }
      },
      VariableDeclarator(node: ESTree.VariableDeclarator): void {
        const record = annotatedRecord(node);
        if (record === null) return;
        for (const [index, argument] of record.call.arguments.entries()) {
          const repeated = record.typeArguments[index];
          if (repeated !== undefined) inspectChild(argument, repeated, record.namespace, node);
        }
      },
    };
  },
});
