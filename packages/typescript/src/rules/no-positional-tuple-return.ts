/**
 * @fileoverview no-positional-tuple-return — a positional tuple return names its fields only at the call site, so call sites disagree.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-positional-tuple-return.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "noPositionalTupleReturn";
type Options = readonly [];
type FunctionNode =
  | TSESTree.FunctionDeclaration
  | TSESTree.FunctionExpression
  | TSESTree.ArrowFunctionExpression
  | TSESTree.TSEmptyBodyFunctionExpression;

export const noPositionalTupleReturnDocumentation = {
  summary: "Disallow returning a multi-field tuple from a named function; return a named object so call sites cannot mismatch slots.",
  rationale: "Tuple fields are identified only by position, so reordering can preserve types while changing meaning.",
  remediation: "Return an object whose property names describe each value.",
  category: "maintainability",
  limitations: ["Declared or syntax-proven multi-field tuple returns on named functions and public type surfaces are inspected; anonymous inline callbacks and syntax-proven TanStack Query key factories are excluded."],
  examples: [
    { id: "named-object-return", title: "Return named fields", outcome: "no-match", files: [{ path: "src/download.ts", source: "export function download(): { body: string; status: number } { return impl(); }" }], focusPath: "src/download.ts", expectedCount: 0, public: true },
    { id: "tuple-return", title: "Do not expose positional fields", outcome: "match", files: [{ path: "src/download.ts", source: "export function download(): [string, number] { return impl(); }" }], focusPath: "src/download.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

const MIN_ELEMENTS = 2;

/** Type wrappers whose single type argument is the value actually returned. */
const AWAITABLE_TYPES: ReadonlySet<string> = new Set(["Promise", "PromiseLike", "Awaited", "Readonly"]);

function staticMemberName(key: TSESTree.PropertyName): string | null {
  if (key.type === AST_NODE_TYPES.Identifier) return key.name;
  if (key.type === AST_NODE_TYPES.Literal && typeof key.value === "string") {
    return key.value;
  }
  return null;
}

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

function tupleExpression(
  node: TSESTree.Expression,
  aliases: ReadonlyMap<string, TSESTree.TypeNode>,
): TSESTree.ArrayExpression | null {
  if (node.type !== AST_NODE_TYPES.TSAsExpression && node.type !== AST_NODE_TYPES.TSSatisfiesExpression) {
    return null;
  }
  if (node.expression.type !== AST_NODE_TYPES.ArrayExpression || node.expression.elements.length < MIN_ELEMENTS) {
    return null;
  }
  if (
    node.type === AST_NODE_TYPES.TSAsExpression &&
    node.typeAnnotation.type === AST_NODE_TYPES.TSTypeReference &&
    node.typeAnnotation.typeName.type === AST_NODE_TYPES.Identifier &&
    node.typeAnnotation.typeName.name === "const"
  ) return node.expression;
  return tupleReturnType(node.typeAnnotation, aliases) === null ? null : node.expression;
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
    return parent.key.name;
  }
  return null;
}

/**
 * TanStack Query key factories intentionally return readonly arrays as opaque
 * cache identities, not positional records.  Recognize only the conventional,
 * syntax-proven factory shape: a const object named `*Keys`, frozen with
 * `as const`, and anchored by an `all: [...] as const` key.
 */
function isQueryKeyFactory(node: FunctionNode): boolean {
  let wrapped: TSESTree.Node = node;
  while (
    (wrapped.parent?.type === AST_NODE_TYPES.TSAsExpression ||
      wrapped.parent?.type === AST_NODE_TYPES.TSSatisfiesExpression ||
      wrapped.parent?.type === AST_NODE_TYPES.TSNonNullExpression) &&
    wrapped.parent.expression === wrapped
  ) wrapped = wrapped.parent;
  const property = wrapped.parent;
  if (property?.type !== AST_NODE_TYPES.Property || property.value !== wrapped) return false;
  const object = property.parent;
  if (object.type !== AST_NODE_TYPES.ObjectExpression) return false;
  const assertion = object.parent;
  if (
    assertion.type !== AST_NODE_TYPES.TSAsExpression ||
    assertion.expression !== object ||
    assertion.typeAnnotation.type !== AST_NODE_TYPES.TSTypeReference ||
    assertion.typeAnnotation.typeName.type !== AST_NODE_TYPES.Identifier ||
    assertion.typeAnnotation.typeName.name !== "const"
  ) return false;
  const declarator = assertion.parent;
  if (
    declarator.type !== AST_NODE_TYPES.VariableDeclarator ||
    declarator.id.type !== AST_NODE_TYPES.Identifier ||
    !/Keys$/i.test(declarator.id.name) ||
    declarator.parent.type !== AST_NODE_TYPES.VariableDeclaration ||
    declarator.parent.kind !== "const"
  ) return false;
  return object.properties.some((candidate) => {
    if (candidate.type !== AST_NODE_TYPES.Property || staticMemberName(candidate.key) !== "all") return false;
    return candidate.value.type === AST_NODE_TYPES.TSAsExpression &&
      candidate.value.expression.type === AST_NODE_TYPES.ArrayExpression &&
      candidate.value.typeAnnotation.type === AST_NODE_TYPES.TSTypeReference &&
      candidate.value.typeAnnotation.typeName.type === AST_NODE_TYPES.Identifier &&
      candidate.value.typeAnnotation.typeName.name === "const";
  });
}

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

function moduleScopeBindingName(node: TSESTree.Node): string | null {
  let current: TSESTree.Node = node;
  while (current.parent != null && current.parent.type !== AST_NODE_TYPES.Program) {
    current = current.parent;
  }
  if (current.parent?.type !== AST_NODE_TYPES.Program) return null;
  let topLevel: TSESTree.Node | null = current;
  if (
    current.type === AST_NODE_TYPES.ExportNamedDeclaration ||
    current.type === AST_NODE_TYPES.ExportDefaultDeclaration
  ) topLevel = current.declaration;
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
  ) return "default";
  if (topLevel.type === AST_NODE_TYPES.ClassDeclaration) {
    let owner: TSESTree.Node | undefined = node.parent;
    while (owner != null && owner.parent !== topLevel.body) owner = owner.parent;
    return (owner?.type === AST_NODE_TYPES.MethodDefinition ||
      owner?.type === AST_NODE_TYPES.TSAbstractMethodDefinition ||
      owner?.type === AST_NODE_TYPES.PropertyDefinition) && owner.value === node
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
      if (declarator.id.type === AST_NODE_TYPES.Identifier && initializer === node) return declarator.id.name;
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
            owner?.type === AST_NODE_TYPES.Property) && owner.value === node
        ) return declarator.id.name;
      }
    }
  }
  return null;
}

function isExportedInterface(
  node: TSESTree.TSInterfaceDeclaration,
  exports: ReadonlySet<string>,
): boolean {
  return node.parent.type === AST_NODE_TYPES.ExportNamedDeclaration ||
    node.parent.type === AST_NODE_TYPES.ExportDefaultDeclaration ||
    (node.parent.type === AST_NODE_TYPES.Program && exports.has(node.id.name));
}

export default createRule<Options, MessageIds>({
  name: "no-positional-tuple-return",
  documentation: noPositionalTupleReturnDocumentation,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow returning a multi-field tuple from a named function; return a named object so call sites cannot mismatch slots.",
    },
    schema: [],
    messages: {
      noPositionalTupleReturn:
        "`{{name}}` returns a {{count}}-field tuple, so callers depend on positional slots that can be reordered silently. Return a named object instead.",
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
    const reportedFunctions = new WeakSet<FunctionNode>();
    const functionStack: FunctionNode[] = [];
    const report = (annotation: TSESTree.TypeNode, name: string): void => {
      const tuple = tupleReturnType(annotation, aliases);
      if (tuple === null || tuple.elementTypes.length < MIN_ELEMENTS) return;
      context.report({
        node: annotation,
        messageId: "noPositionalTupleReturn",
        data: { name, count: String(tuple.elementTypes.length) },
      });
    };
    const reportExpression = (node: FunctionNode, expression: TSESTree.Expression): void => {
      if (reportedFunctions.has(node)) return;
      const tuple = tupleExpression(expression, aliases);
      const name = functionName(node);
      if (tuple === null || name === null) return;
      reportedFunctions.add(node);
      context.report({
        node: tuple,
        messageId: "noPositionalTupleReturn",
        data: { name, count: String(tuple.elements.length) },
      });
    };
    const check = (node: FunctionNode): void => {
      if (isQueryKeyFactory(node)) return;
      const annotation = node.returnType?.typeAnnotation;
      if (annotation === undefined) {
        if (node.type === AST_NODE_TYPES.ArrowFunctionExpression && node.expression) {
          reportExpression(node, node.body);
        }
        return;
      }
      const name = functionName(node);
      if (name === null) {
        return;
      }
      report(annotation, name);
    };
    const enterFunction = (node: FunctionNode): void => {
      functionStack.push(node);
      check(node);
    };
    const exitFunction = (): void => {
      functionStack.pop();
    };
    return {
      FunctionDeclaration: enterFunction,
      "FunctionDeclaration:exit": exitFunction,
      FunctionExpression: enterFunction,
      "FunctionExpression:exit": exitFunction,
      ArrowFunctionExpression: enterFunction,
      "ArrowFunctionExpression:exit": exitFunction,
      TSEmptyBodyFunctionExpression: enterFunction,
      "TSEmptyBodyFunctionExpression:exit": exitFunction,
      ReturnStatement(node): void {
        const owner = functionStack.at(-1);
        if (owner === undefined || owner.returnType !== undefined || node.argument === null) return;
        reportExpression(owner, node.argument);
      },
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
        const memberName = staticMemberName(node.key);
        if (
          (owner === null || !isExportedInterface(owner, typeExports)) &&
          (alias === null || !typeExports.has(alias.id.name)) ||
          node.returnType === undefined ||
          memberName === null
        ) return;
        report(node.returnType.typeAnnotation, `${owner?.id.name ?? alias?.id.name ?? "type"}.${memberName}`);
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
        const memberName = staticMemberName(node.key);
        if (
          ((owner === null || !isExportedInterface(owner, typeExports)) &&
            (alias === null || !typeExports.has(alias.id.name))) ||
          memberName === null ||
          annotation === undefined
        ) return;
        const returnType = callableReturnType(annotation, aliases);
        if (returnType !== null) {
          report(returnType, `${owner?.id.name ?? alias?.id.name ?? "type"}.${memberName}`);
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
