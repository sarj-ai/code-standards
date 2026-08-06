/**
 * @fileoverview no-positional-tuple-return — a positional tuple crossing a module boundary names its fields only at the call site, so call sites disagree.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-positional-tuple-return.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "noPositionalTupleReturn";
type Options = readonly [];

const MIN_ELEMENTS = 2;

/** Type wrappers whose single type argument is the value actually returned. */
const AWAITABLE_TYPES: ReadonlySet<string> = new Set(["Promise", "PromiseLike", "Awaited", "Readonly"]);

/** The first boundary tuple in a return annotation, unwrapping transparent wrappers and unions. */
function tupleReturnType(
  node: TSESTree.TypeNode,
  aliases: ReadonlyMap<string, TSESTree.TypeNode>,
  resolving: ReadonlySet<string> = new Set(),
): TSESTree.TSTupleType | null {
  if (node.type === AST_NODE_TYPES.TSTupleType) {
    return node;
  }
  if (
    node.type === AST_NODE_TYPES.TSTypeReference &&
    node.typeName.type === AST_NODE_TYPES.Identifier &&
    AWAITABLE_TYPES.has(node.typeName.name)
  ) {
    const argument = node.typeArguments?.params.at(0);
    return argument === undefined ? null : tupleReturnType(argument, aliases, resolving);
  }
  if (
    node.type === AST_NODE_TYPES.TSTypeReference &&
    node.typeName.type === AST_NODE_TYPES.Identifier &&
    !resolving.has(node.typeName.name)
  ) {
    const target = aliases.get(node.typeName.name);
    if (target !== undefined) return tupleReturnType(target, aliases, new Set([...resolving, node.typeName.name]));
  }
  if (node.type === AST_NODE_TYPES.TSTypeOperator && node.operator === "readonly") {
    return node.typeAnnotation === undefined ? null : tupleReturnType(node.typeAnnotation, aliases, resolving);
  }
  if (node.type === AST_NODE_TYPES.TSUnionType || node.type === AST_NODE_TYPES.TSIntersectionType) {
    for (const member of node.types) {
      const tuple = tupleReturnType(member, aliases, resolving);
      if (tuple !== null) return tuple;
    }
  }
  return null;
}

/** The declared name of a function-ish node, or null for an anonymous one. */
function functionName(node: TSESTree.Node): string | null {
  if (node.type === AST_NODE_TYPES.FunctionDeclaration) {
    if (node.id !== null) return node.id.name;
    return node.parent?.type === AST_NODE_TYPES.ExportDefaultDeclaration ? "default" : null;
  }
  let wrapped = node;
  while (
    (wrapped.parent?.type === AST_NODE_TYPES.TSAsExpression ||
      wrapped.parent?.type === AST_NODE_TYPES.TSSatisfiesExpression ||
      wrapped.parent?.type === AST_NODE_TYPES.TSNonNullExpression) &&
    wrapped.parent.expression === wrapped
  ) {
    wrapped = wrapped.parent;
  }
  const parent = wrapped.parent;
  if (parent?.type === AST_NODE_TYPES.ExportDefaultDeclaration) return "default";
  if (parent?.type === AST_NODE_TYPES.VariableDeclarator && parent.id.type === AST_NODE_TYPES.Identifier) {
    return parent.id.name;
  }
  if (
    (parent?.type === AST_NODE_TYPES.MethodDefinition ||
      parent?.type === AST_NODE_TYPES.TSAbstractMethodDefinition ||
      parent?.type === AST_NODE_TYPES.PropertyDefinition ||
      parent?.type === AST_NODE_TYPES.Property) &&
    parent.key.type === AST_NODE_TYPES.Identifier
  ) {
    if (
      (parent.type === AST_NODE_TYPES.MethodDefinition ||
        parent.type === AST_NODE_TYPES.TSAbstractMethodDefinition ||
        parent.type === AST_NODE_TYPES.PropertyDefinition) &&
      (parent.accessibility === "private" ||
        parent.accessibility === "protected")
    ) return null;
    return parent.key.name;
  }
  return null;
}

/**
 * True when an ancestor statement carries the `export` keyword inline —
 * `export function f`, `export const f =`, `export default function f`.
 */
function isInlineExported(node: TSESTree.Node): boolean {
  if (moduleScopeBindingName(node) === null) return false;
  for (let current: TSESTree.Node | undefined | null = node; current != null; current = current.parent) {
    const parent = current.parent;
    if (
      parent?.type === AST_NODE_TYPES.ExportNamedDeclaration ||
      parent?.type === AST_NODE_TYPES.ExportDefaultDeclaration
    ) {
      return true;
    }
  }
  return false;
}

/**
 * The module-scope binding the function lives under — `split` for a top-level
 * `function split`, `Repo` for a method of a top-level `class Repo`. That is the
 * name an `export { … }` specifier elsewhere in the file would refer to. Null
 * when the function is not anchored to a named top-level declaration.
 */
function moduleScopeBindingName(node: TSESTree.Node): string | null {
  let current: TSESTree.Node = node;
  while (current.parent != null && current.parent.type !== AST_NODE_TYPES.Program) {
    current = current.parent;
  }
  if (current.parent?.type !== AST_NODE_TYPES.Program) {
    return null;
  }
  let topLevel: TSESTree.Node | null = current;
  if (
    current.type === AST_NODE_TYPES.ExportNamedDeclaration ||
    current.type === AST_NODE_TYPES.ExportDefaultDeclaration
  ) {
    topLevel = current.declaration;
  }
  if (topLevel === null) return null;
  if (topLevel.type === AST_NODE_TYPES.FunctionDeclaration) {
    if (topLevel !== node) return null;
    return topLevel.id?.name ?? (current.type === AST_NODE_TYPES.ExportDefaultDeclaration ? "default" : null);
  }
  if (
    (topLevel.type === AST_NODE_TYPES.ArrowFunctionExpression ||
      topLevel.type === AST_NODE_TYPES.FunctionExpression) &&
    topLevel === node &&
    current.type === AST_NODE_TYPES.ExportDefaultDeclaration
  ) {
    return "default";
  }
  if (topLevel.type === AST_NODE_TYPES.ClassDeclaration) {
    let owner: TSESTree.Node | undefined = node.parent;
    while (owner != null && owner.parent !== topLevel.body) owner = owner.parent;
    return (owner?.type === AST_NODE_TYPES.MethodDefinition ||
      owner?.type === AST_NODE_TYPES.TSAbstractMethodDefinition ||
      owner?.type === AST_NODE_TYPES.PropertyDefinition) &&
      owner.value === node
      ? topLevel.id?.name ?? (current.type === AST_NODE_TYPES.ExportDefaultDeclaration ? "default" : null)
      : null;
  }
  if (topLevel.type === AST_NODE_TYPES.VariableDeclaration) {
    for (const declarator of topLevel.declarations) {
      let initializer = declarator.init;
      while (
        initializer?.type === AST_NODE_TYPES.TSAsExpression ||
        initializer?.type === AST_NODE_TYPES.TSSatisfiesExpression ||
        initializer?.type === AST_NODE_TYPES.TSNonNullExpression
      ) initializer = initializer.expression;
      if (
        declarator.id.type === AST_NODE_TYPES.Identifier &&
        initializer === node
      ) return declarator.id.name;
      if (
        declarator.id.type === AST_NODE_TYPES.Identifier &&
        (initializer?.type === AST_NODE_TYPES.ClassExpression ||
          initializer?.type === AST_NODE_TYPES.ObjectExpression)
      ) {
        let owner: TSESTree.Node | undefined = node.parent;
        const container = initializer.type === AST_NODE_TYPES.ClassExpression ? initializer.body : initializer;
        while (owner != null && owner.parent !== container) owner = owner.parent;
        if (
          (owner?.type === AST_NODE_TYPES.MethodDefinition ||
            owner?.type === AST_NODE_TYPES.PropertyDefinition ||
            owner?.type === AST_NODE_TYPES.Property) &&
          owner.value === node
        ) return declarator.id.name;
      }
    }
  }
  return null;
}

/**
 * Local names this module puts on its public surface through a *detached* export
 * statement: `export { split }`, `export { split as s }`, `export default split`,
 * `export = split`. A re-export (`export { x } from "./other"`) names a binding
 * owned by another module, and a type-only export (`export type { x }`) does not
 * expose the value, so neither counts.
 */
function specifierExportedNames(program: TSESTree.Program): ReadonlySet<string> {
  const names = new Set<string>();
  for (const statement of program.body) {
    if (
      statement.type === AST_NODE_TYPES.ExportNamedDeclaration &&
      statement.declaration == null &&
      statement.source == null &&
      statement.exportKind !== "type"
    ) {
      for (const specifier of statement.specifiers) {
        if (specifier.exportKind !== "type" && specifier.local.type === AST_NODE_TYPES.Identifier) {
          names.add(specifier.local.name);
        }
      }
      continue;
    }
    if (
      statement.type === AST_NODE_TYPES.ExportDefaultDeclaration &&
      statement.declaration.type === AST_NODE_TYPES.Identifier
    ) {
      names.add(statement.declaration.name);
      continue;
    }
    if (
      statement.type === AST_NODE_TYPES.TSExportAssignment &&
      statement.expression.type === AST_NODE_TYPES.Identifier
    ) {
      names.add(statement.expression.name);
    }
  }
  return names;
}

function exportedTypeNames(program: TSESTree.Program): ReadonlySet<string> {
  const names = new Set<string>();
  for (const statement of program.body) {
    if (statement.type !== AST_NODE_TYPES.ExportNamedDeclaration || statement.source !== null) continue;
    if (
      statement.declaration?.type === AST_NODE_TYPES.TSInterfaceDeclaration ||
      statement.declaration?.type === AST_NODE_TYPES.TSTypeAliasDeclaration
    ) names.add(statement.declaration.id.name);
    for (const specifier of statement.specifiers) names.add(specifier.local.name);
  }
  for (const statement of program.body) {
    if (
      statement.type === AST_NODE_TYPES.ExportDefaultDeclaration &&
      (statement.declaration.type === AST_NODE_TYPES.TSInterfaceDeclaration ||
        statement.declaration.type === AST_NODE_TYPES.TSTypeAliasDeclaration)
    ) names.add(statement.declaration.id.name);
  }
  return names;
}

function typeAliases(program: TSESTree.Program): ReadonlyMap<string, TSESTree.TypeNode> {
  const aliases = new Map<string, TSESTree.TypeNode>();
  for (const statement of program.body) {
    const declaration = statement.type === AST_NODE_TYPES.ExportNamedDeclaration
      ? statement.declaration
      : statement;
    if (declaration?.type === AST_NODE_TYPES.TSTypeAliasDeclaration) {
      aliases.set(declaration.id.name, declaration.typeAnnotation);
    }
  }
  return aliases;
}

function callableReturnType(
  node: TSESTree.TypeNode,
  aliases: ReadonlyMap<string, TSESTree.TypeNode>,
  resolving: ReadonlySet<string> = new Set(),
): TSESTree.TypeNode | null {
  if (node.type === AST_NODE_TYPES.TSFunctionType) return node.returnType?.typeAnnotation ?? null;
  if (
    node.type === AST_NODE_TYPES.TSTypeReference &&
    node.typeName.type === AST_NODE_TYPES.Identifier &&
    !resolving.has(node.typeName.name)
  ) {
    const target = aliases.get(node.typeName.name);
    if (target !== undefined) {
      return callableReturnType(target, aliases, new Set([...resolving, node.typeName.name]));
    }
  }
  return null;
}

function publiclyReachableTypeNames(
  program: TSESTree.Program,
  exported: ReadonlySet<string>,
): ReadonlySet<string> {
  const names = new Set(exported);
  const interfaces = new Map<string, readonly TSESTree.TSInterfaceHeritage[]>();
  for (const statement of program.body) {
    const declaration = statement.type === AST_NODE_TYPES.ExportNamedDeclaration
      ? statement.declaration
      : statement;
    if (declaration?.type === AST_NODE_TYPES.TSInterfaceDeclaration) {
      interfaces.set(declaration.id.name, declaration.extends);
    }
  }
  for (let pass = 0; pass < interfaces.size; pass += 1) {
    let changed = false;
    for (const name of [...names]) {
      for (const heritage of interfaces.get(name) ?? []) {
        if (heritage.expression.type === AST_NODE_TYPES.Identifier && !names.has(heritage.expression.name)) {
          names.add(heritage.expression.name);
          changed = true;
        }
      }
    }
    if (!changed) break;
  }
  return names;
}

function owningInterface(node: TSESTree.Node): TSESTree.TSInterfaceDeclaration | null {
  for (let current = node.parent; current !== undefined; current = current.parent) {
    if (current.type === AST_NODE_TYPES.TSInterfaceDeclaration) return current;
    if (current.type === AST_NODE_TYPES.Program) return null;
  }
  return null;
}

function owningTypeAlias(node: TSESTree.Node): TSESTree.TSTypeAliasDeclaration | null {
  for (let current = node.parent; current !== undefined; current = current.parent) {
    if (current.type === AST_NODE_TYPES.TSTypeAliasDeclaration) return current;
    if (current.type === AST_NODE_TYPES.Program) return null;
  }
  return null;
}

function owningClass(
  node: TSESTree.Node,
): TSESTree.ClassDeclaration | TSESTree.ClassExpression | null {
  for (let current = node.parent; current !== undefined; current = current.parent) {
    if (current.type === AST_NODE_TYPES.ClassDeclaration || current.type === AST_NODE_TYPES.ClassExpression) {
      return current;
    }
    if (current.type === AST_NODE_TYPES.Program) return null;
  }
  return null;
}

function isExportedClass(
  node: TSESTree.ClassDeclaration | TSESTree.ClassExpression,
  specifierExports: ReadonlySet<string>,
): boolean {
  if (
    node.parent.type === AST_NODE_TYPES.ExportNamedDeclaration ||
    node.parent.type === AST_NODE_TYPES.ExportDefaultDeclaration
  ) return true;
  if (node.type === AST_NODE_TYPES.ClassDeclaration) {
    return node.id !== null && node.parent.type === AST_NODE_TYPES.Program && specifierExports.has(node.id.name);
  }
  if (
    node.parent.type === AST_NODE_TYPES.VariableDeclarator &&
    node.parent.id.type === AST_NODE_TYPES.Identifier
  ) return specifierExports.has(node.parent.id.name) || isInlineExported(node);
  return false;
}

function isExportedInterface(
  node: TSESTree.TSInterfaceDeclaration,
  exports: ReadonlySet<string>,
): boolean {
  return node.parent.type === AST_NODE_TYPES.ExportNamedDeclaration ||
    node.parent.type === AST_NODE_TYPES.ExportDefaultDeclaration ||
    (node.parent.type === AST_NODE_TYPES.Program && exports.has(node.id.name));
}

/**
 * True when the function is reachable from outside the module — the boundary the
 * rule is about. Either the declaration is exported inline, or its module-scope
 * binding is exported later through an export specifier.
 */
function isExported(node: TSESTree.Node, specifierExports: ReadonlySet<string>): boolean {
  if (isInlineExported(node)) {
    return true;
  }
  if (specifierExports.size === 0) {
    return false;
  }
  const binding = moduleScopeBindingName(node);
  return binding !== null && specifierExports.has(binding);
}

export default createRule<Options, MessageIds>({
  name: "no-positional-tuple-return",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow returning a multi-field tuple from an exported function; return a named object so call sites cannot mismatch slots.",
    },
    schema: [],
    messages: {
      noPositionalTupleReturn:
        "Exported `{{name}}` returns a {{count}}-field tuple, so consumers depend on positional slots that can be reordered silently. Return a named object instead.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    const specifierExports = specifierExportedNames(context.sourceCode.ast);
    const typeExports = publiclyReachableTypeNames(
      context.sourceCode.ast,
      exportedTypeNames(context.sourceCode.ast),
    );
    const aliases = typeAliases(context.sourceCode.ast);
    const report = (annotation: TSESTree.TypeNode, name: string): void => {
      const tuple = tupleReturnType(annotation, aliases);
      if (tuple === null || tuple.elementTypes.length < MIN_ELEMENTS) return;
      context.report({
        // Report the public boundary's annotation, not a shared alias declaration.
        // Otherwise every exported function returning the same alias produces a
        // stack of diagnostics at the alias's single source location.
        node: annotation,
        messageId: "noPositionalTupleReturn",
        data: { name, count: String(tuple.elementTypes.length) },
      });
    };
    const check = (
      node:
        | TSESTree.FunctionDeclaration
        | TSESTree.FunctionExpression
        | TSESTree.ArrowFunctionExpression
        | TSESTree.TSEmptyBodyFunctionExpression,
    ): void => {
      const annotation = node.returnType?.typeAnnotation;
      if (annotation === undefined) {
        return;
      }
      const name = functionName(node);
      if (name === null) {
        return;
      }
      if (!isExported(node, specifierExports)) {
        return;
      }
      report(annotation, name);
    };
    return {
      FunctionDeclaration: check,
      FunctionExpression: check,
      ArrowFunctionExpression: check,
      TSEmptyBodyFunctionExpression: check,
      TSDeclareFunction(node): void {
        if (
          node.id === null ||
          node.returnType === undefined ||
          (node.parent.type !== AST_NODE_TYPES.ExportNamedDeclaration &&
            node.parent.type !== AST_NODE_TYPES.ExportDefaultDeclaration &&
            !specifierExports.has(node.id.name))
        ) return;
        report(node.returnType.typeAnnotation, node.id.name);
      },
      TSCallSignatureDeclaration(node): void {
        const owner = owningInterface(node);
        if (owner === null || !isExportedInterface(owner, typeExports) || node.returnType === undefined) return;
        report(node.returnType.typeAnnotation, `${owner.id.name}.call`);
      },
      TSMethodSignature(node): void {
        const owner = owningInterface(node);
        const alias = owningTypeAlias(node);
        if (
          (owner === null || !isExportedInterface(owner, typeExports)) &&
          (alias === null || !typeExports.has(alias.id.name)) ||
          node.returnType === undefined ||
          node.key.type !== AST_NODE_TYPES.Identifier
        ) return;
        report(node.returnType.typeAnnotation, `${owner?.id.name ?? alias?.id.name ?? "type"}.${node.key.name}`);
      },
      TSTypeAliasDeclaration(node): void {
        if (!typeExports.has(node.id.name)) return;
        const returnType = callableReturnType(node.typeAnnotation, aliases);
        if (returnType !== null) report(returnType, node.id.name);
      },
      TSPropertySignature(node): void {
        const owner = owningInterface(node);
        const alias = owningTypeAlias(node);
        const annotation = node.typeAnnotation?.typeAnnotation;
        if (
          ((owner === null || !isExportedInterface(owner, typeExports)) &&
            (alias === null || !typeExports.has(alias.id.name))) ||
          node.key.type !== AST_NODE_TYPES.Identifier ||
          annotation === undefined
        ) return;
        const returnType = callableReturnType(annotation, aliases);
        if (returnType !== null) {
          report(returnType, `${owner?.id.name ?? alias?.id.name ?? "type"}.${node.key.name}`);
        }
      },
      PropertyDefinition(node): void {
        if (node.accessibility === "private" || node.accessibility === "protected") return;
        const owner = owningClass(node);
        const annotation = node.typeAnnotation?.typeAnnotation;
        if (owner === null || !isExportedClass(owner, specifierExports) || annotation === undefined) return;
        const returnType = callableReturnType(annotation, aliases);
        if (returnType !== null) {
          const name = node.key.type === AST_NODE_TYPES.Identifier ? node.key.name : "property";
          report(returnType, name);
        }
      },
    };
  },
});
