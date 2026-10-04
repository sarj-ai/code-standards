/**
 * @fileoverview no-positional-tuple-return — a positional tuple return names its fields only at the call site, so call sites disagree.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-positional-tuple-return.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, SourceCode } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "noPositionalTupleReturn";
type Options = readonly [];
interface TypeAliases {
  get(identifier: ESTree.BindingIdentifier): ESTree.TSType | undefined;
}
type FunctionNode =
  | ESTree.Function | ESTree.ArrowFunctionExpression;

export const NO_POSITIONAL_TUPLE_RETURN_DOCUMENTATION = {
  summary:
    "Disallow returning a multi-field tuple from a named function; return a named object so call sites cannot mismatch slots.",
  rationale:
    "Tuple fields are identified only by position, so reordering can preserve types while changing meaning.",
  remediation: "Return an object whose property names describe each value.",
  category: "maintainability",
  limitations: [
    "Declared or syntax-proven multi-field tuple returns on named functions and public type surfaces are inspected; anonymous inline callbacks and syntax-proven TanStack Query key factories are excluded.",
  ],
  examples: [
    {
      id: "named-object-return",
      title: "Return named fields",
      outcome: "no-match",
      files: [
        {
          path: "src/download.ts",
          source:
            "export function download(): { body: string; status: number } { return impl(); }",
        },
      ],
      focusPath: "src/download.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "tuple-return",
      title: "Do not expose positional fields",
      outcome: "match",
      files: [
        {
          path: "src/download.ts",
          source:
            "export function download(): [string, number] { return impl(); }",
        },
      ],
      focusPath: "src/download.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

const MIN_ELEMENTS = 2;

/** Type wrappers whose single type argument is the value actually returned. */
const AWAITABLE_TYPES: ReadonlySet<string> = new Set([
  "Promise",
  "PromiseLike",
  "Awaited",
  "Readonly",
]);

function staticMemberName(key: ESTree.PropertyKey): string | null {
  if (key.type === "Identifier") return key.name;
  if (key.type === "Literal" && typeof key.value === "string") {
    return key.value;
  }
  return null;
}

/** The first boundary tuple in a return annotation, unwrapping transparent wrappers and unions. */
function tupleReturnType(
  node: ESTree.TSType,
  aliases: TypeAliases,
  resolving: ReadonlySet<string> = new Set(),
): ESTree.TSTupleType | null {
  if (node.type === "TSTupleType") {
    return node;
  }
  if (
    node.type === "TSTypeReference" &&
    node.typeName.type === "Identifier" &&
    AWAITABLE_TYPES.has(node.typeName.name)
  ) {
    const argument = node.typeArguments?.params.at(0);
    return argument === undefined
      ? null
      : tupleReturnType(argument, aliases, resolving);
  }
  if (
    node.type === "TSTypeReference" &&
    node.typeName.type === "Identifier" &&
    !resolving.has(node.typeName.name)
  ) {
    const target = aliases.get(node.typeName);
    if (target !== undefined)
      return tupleReturnType(
        target,
        aliases,
        new Set([...resolving, node.typeName.name]),
      );
  }
  if (node.type === "TSTypeOperator" && node.operator === "readonly") {
    return node.typeAnnotation === undefined
      ? null
      : tupleReturnType(node.typeAnnotation, aliases, resolving);
  }
  if (node.type === "TSUnionType" || node.type === "TSIntersectionType") {
    for (const member of node.types) {
      const tuple = tupleReturnType(member, aliases, resolving);
      if (tuple !== null) return tuple;
    }
  }
  return null;
}

function tupleExpression(
  node: ESTree.Expression,
  aliases: TypeAliases,
): ESTree.ArrayExpression | null {
  if (node.type !== "TSAsExpression" && node.type !== "TSSatisfiesExpression") {
    return null;
  }
  if (
    node.expression.type !== "ArrayExpression" ||
    node.expression.elements.length < MIN_ELEMENTS
  ) {
    return null;
  }
  if (
    node.type === "TSAsExpression" &&
    node.typeAnnotation.type === "TSTypeReference" &&
    node.typeAnnotation.typeName.type === "Identifier" &&
    node.typeAnnotation.typeName.name === "const"
  )
    return node.expression;
  return tupleReturnType(node.typeAnnotation, aliases) === null
    ? null
    : node.expression;
}

/** The declared name of a function-ish node, or null for an anonymous one. */
function functionName(node: ESTree.Node): string | null {
  if (node.type === "FunctionDeclaration") {
    if (node.id !== null) return node.id.name;
    return node.parent?.type === "ExportDefaultDeclaration" ? "default" : null;
  }
  let wrapped = node;
  while (
    (wrapped.parent?.type === "TSAsExpression" ||
      wrapped.parent?.type === "TSSatisfiesExpression" ||
      wrapped.parent?.type === "TSNonNullExpression") &&
    wrapped.parent.expression === wrapped
  ) {
    wrapped = wrapped.parent;
  }
  const parent = wrapped.parent;
  if (parent?.type === "ExportDefaultDeclaration") return "default";
  if (
    parent?.type === "VariableDeclarator" &&
    parent.id.type === "Identifier"
  ) {
    return parent.id.name;
  }
  if (
    (parent?.type === "MethodDefinition" ||
      parent?.type === "TSAbstractMethodDefinition" ||
      parent?.type === "PropertyDefinition" ||
      parent?.type === "Property") &&
    parent.key.type === "Identifier"
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
  let wrapped: ESTree.Node = node;
  while (
    (wrapped.parent?.type === "TSAsExpression" ||
      wrapped.parent?.type === "TSSatisfiesExpression" ||
      wrapped.parent?.type === "TSNonNullExpression") &&
    wrapped.parent.expression === wrapped
  )
    wrapped = wrapped.parent;
  const property = wrapped.parent;
  if (property?.type !== "Property" || property.value !== wrapped) return false;
  const object = property.parent;
  if (object.type !== "ObjectExpression") return false;
  const assertion = object.parent;
  if (
    assertion.type !== "TSAsExpression" ||
    assertion.expression !== object ||
    assertion.typeAnnotation.type !== "TSTypeReference" ||
    assertion.typeAnnotation.typeName.type !== "Identifier" ||
    assertion.typeAnnotation.typeName.name !== "const"
  )
    return false;
  const declarator = assertion.parent;
  if (
    declarator.type !== "VariableDeclarator" ||
    declarator.id.type !== "Identifier" ||
    !/Keys$/i.test(declarator.id.name) ||
    declarator.parent?.type !== "VariableDeclaration" ||
    declarator.parent.kind !== "const"
  )
    return false;
  return object.properties.some((candidate) => {
    if (
      candidate.type !== "Property" ||
      staticMemberName(candidate.key) !== "all"
    )
      return false;
    return (
      candidate.value.type === "TSAsExpression" &&
      candidate.value.expression.type === "ArrayExpression" &&
      candidate.value.typeAnnotation.type === "TSTypeReference" &&
      candidate.value.typeAnnotation.typeName.type === "Identifier" &&
      candidate.value.typeAnnotation.typeName.name === "const"
    );
  });
}

function specifierExportedNames(program: ESTree.Program): ReadonlySet<string> {
  const names = new Set<string>();
  for (const statement of program.body) {
    if (
      statement.type === "ExportNamedDeclaration" &&
      statement.declaration == null &&
      statement.source == null &&
      statement.exportKind !== "type"
    ) {
      for (const specifier of statement.specifiers) {
        if (
          specifier.exportKind !== "type" &&
          specifier.local.type === "Identifier"
        ) {
          names.add(specifier.local.name);
        }
      }
      continue;
    }
    if (
      statement.type === "ExportDefaultDeclaration" &&
      statement.declaration.type === "Identifier"
    ) {
      names.add(statement.declaration.name);
      continue;
    }
    if (
      statement.type === "TSExportAssignment" &&
      statement.expression.type === "Identifier"
    ) {
      names.add(statement.expression.name);
    }
  }
  return names;
}

function exportedTypeNames(program: ESTree.Program): ReadonlySet<string> {
  const names = new Set<string>();
  for (const statement of program.body) {
    if (
      statement.type !== "ExportNamedDeclaration" ||
      statement.source !== null
    )
      continue;
    if (
      statement.declaration?.type === "TSInterfaceDeclaration" ||
      statement.declaration?.type === "TSTypeAliasDeclaration"
    )
      names.add(statement.declaration.id.name);
    for (const specifier of statement.specifiers) {
      if (specifier.local.type === "Identifier")
        names.add(specifier.local.name);
    }
  }
  for (const statement of program.body) {
    if (
      statement.type === "ExportDefaultDeclaration" &&
      statement.declaration.type === "TSInterfaceDeclaration"
    )
      names.add(statement.declaration.id.name);
  }
  return names;
}

function typeAliases(sourceCode: SourceCode): TypeAliases {
  const aliases = new Map<string, ESTree.TSTypeAliasDeclaration>();
  for (const statement of sourceCode.ast.body) {
    const declaration =
      statement.type === "ExportNamedDeclaration"
        ? statement.declaration
        : statement;
    if (declaration?.type === "TSTypeAliasDeclaration") {
      aliases.set(declaration.id.name, declaration);
    }
  }
  return {
    get(identifier) {
      const declaration = aliases.get(identifier.name);
      if (declaration == null) return undefined;
      const binding = findVariable(
        sourceCode.getScope(identifier),
        identifier.name,
      );
      return binding?.defs.length === 1 && binding.defs[0]?.node === declaration
        ? declaration.typeAnnotation
        : undefined;
    },
  };
}

function callableReturnType(
  node: ESTree.TSType,
  aliases: TypeAliases,
  resolving: ReadonlySet<string> = new Set(),
): ESTree.TSType | null {
  if (node.type === "TSFunctionType")
    return node.returnType?.typeAnnotation ?? null;
  if (
    node.type === "TSTypeReference" &&
    node.typeName.type === "Identifier" &&
    !resolving.has(node.typeName.name)
  ) {
    const target = aliases.get(node.typeName);
    if (target !== undefined) {
      return callableReturnType(
        target,
        aliases,
        new Set([...resolving, node.typeName.name]),
      );
    }
  }
  return null;
}

function publiclyReachableTypeNames(
  program: ESTree.Program,
  exported: ReadonlySet<string>,
): ReadonlySet<string> {
  const names = new Set(exported);
  const interfaces = new Map<string, readonly ESTree.TSInterfaceHeritage[]>();
  for (const statement of program.body) {
    const declaration =
      statement.type === "ExportNamedDeclaration"
        ? statement.declaration
        : statement;
    if (declaration?.type === "TSInterfaceDeclaration") {
      interfaces.set(declaration.id.name, declaration.extends);
    }
  }
  for (let pass = 0; pass < interfaces.size; pass += 1) {
    let changed = false;
    for (const name of [...names]) {
      for (const heritage of interfaces.get(name) ?? []) {
        if (
          heritage.expression.type === "Identifier" &&
          !names.has(heritage.expression.name)
        ) {
          names.add(heritage.expression.name);
          changed = true;
        }
      }
    }
    if (!changed) break;
  }
  return names;
}

function owningInterface(
  node: ESTree.Node,
): ESTree.TSInterfaceDeclaration | null {
  for (let current = node.parent; current != null; current = current.parent) {
    if (current.type === "TSInterfaceDeclaration") return current;
    if (current.type === "Program") return null;
  }
  return null;
}

function owningTypeAlias(
  node: ESTree.Node,
): ESTree.TSTypeAliasDeclaration | null {
  for (let current = node.parent; current != null; current = current.parent) {
    if (current.type === "TSTypeAliasDeclaration") return current;
    if (current.type === "Program") return null;
  }
  return null;
}

function owningClass(node: ESTree.Node): ESTree.Class | null {
  for (let current = node.parent; current != null; current = current.parent) {
    if (
      current.type === "ClassDeclaration" ||
      current.type === "ClassExpression"
    ) {
      return current;
    }
    if (current.type === "Program") return null;
  }
  return null;
}

function isExportedClass(
  node: ESTree.Class,
  specifierExports: ReadonlySet<string>,
): boolean {
  if (
    node.parent?.type === "ExportNamedDeclaration" ||
    node.parent?.type === "ExportDefaultDeclaration"
  )
    return true;
  if (node.type === "ClassDeclaration") {
    return (
      node.id !== null &&
      node.parent?.type === "Program" &&
      specifierExports.has(node.id.name)
    );
  }
  if (
    node.parent?.type === "VariableDeclarator" &&
    node.parent.id.type === "Identifier"
  )
    return specifierExports.has(node.parent.id.name) || isInlineExported(node);
  return false;
}

/**
 * True when an ancestor statement carries the `export` keyword inline —
 * `export function f`, `export const f =`, `export default function f`.
 */
function isInlineExported(node: ESTree.Node): boolean {
  if (moduleScopeBindingName(node) === null) return false;
  for (
    let current: ESTree.Node | null | undefined = node;
    current != null;
    current = current.parent
  ) {
    const parent = current.parent;
    if (
      parent?.type === "ExportNamedDeclaration" ||
      parent?.type === "ExportDefaultDeclaration"
    ) {
      return true;
    }
  }
  return false;
}

function moduleScopeBindingName(node: ESTree.Node): string | null {
  let current: ESTree.Node = node;
  while (current.parent != null && current.parent?.type !== "Program") {
    current = current.parent;
  }
  if (current.parent?.type !== "Program") return null;
  let topLevel: ESTree.Node | null = current;
  if (
    current.type === "ExportNamedDeclaration" ||
    current.type === "ExportDefaultDeclaration"
  )
    topLevel = current.declaration;
  if (topLevel === null) return null;
  if (topLevel.type === "FunctionDeclaration") {
    if (topLevel !== node) return null;
    return (
      topLevel.id?.name ??
      (current.type === "ExportDefaultDeclaration" ? "default" : null)
    );
  }
  if (
    (topLevel.type === "ArrowFunctionExpression" ||
      topLevel.type === "FunctionExpression") &&
    topLevel === node &&
    current.type === "ExportDefaultDeclaration"
  )
    return "default";
  if (topLevel.type === "ClassDeclaration") {
    return classBindingName(
      topLevel,
      node,
      current.type === "ExportDefaultDeclaration",
    );
  }
  if (topLevel.type === "VariableDeclaration") {
    return variableBindingName(topLevel, node);
  }
  return null;
}

function isExportedInterface(
  node: ESTree.TSInterfaceDeclaration,
  exports: ReadonlySet<string>,
): boolean {
  return (
    node.parent?.type === "ExportNamedDeclaration" ||
    node.parent?.type === "ExportDefaultDeclaration" ||
    (node.parent?.type === "Program" && exports.has(node.id.name))
  );
}

export default createRule<Options, MessageIds>({
  name: "no-positional-tuple-return",
  documentation: NO_POSITIONAL_TUPLE_RETURN_DOCUMENTATION,
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
    if (isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)) return {};
    const specifierExports = specifierExportedNames(context.sourceCode.ast);
    const typeExports = publiclyReachableTypeNames(
      context.sourceCode.ast,
      exportedTypeNames(context.sourceCode.ast),
    );
    const aliases = typeAliases(context.sourceCode);
    const reportedFunctions = new WeakSet<FunctionNode>();
    const functionStack: FunctionNode[] = [];
    const report = (annotation: ESTree.TSType, name: string): void => {
      const tuple = tupleReturnType(annotation, aliases);
      if (tuple === null || tuple.elementTypes.length < MIN_ELEMENTS) return;
      context.report({
        node: annotation,
        messageId: "noPositionalTupleReturn",
        data: { name, count: String(tuple.elementTypes.length) },
      });
    };
    const reportExpression = (
      node: FunctionNode,
      expression: ESTree.Expression,
    ): void => {
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
    const enterFunction = (node: FunctionNode): void => {
      functionStack.push(node);
      check(node);
    };

    const check = (node: FunctionNode): void => {
      if (isQueryKeyFactory(node)) return;
      const annotation = node.returnType?.typeAnnotation;
      if (annotation == null) {
        if (
          node.type === "ArrowFunctionExpression" &&
          node.body.type !== "BlockStatement"
        ) {
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
        if (
          owner === undefined ||
          owner.returnType != null ||
          node.argument === null
        )
          return;
        reportExpression(owner, node.argument);
      },
      TSDeclareFunction(node): void {
        if (
          node.id === null ||
          node.returnType == null ||
          (node.parent?.type !== "ExportNamedDeclaration" &&
            node.parent?.type !== "ExportDefaultDeclaration" &&
            !specifierExports.has(node.id.name))
        )
          return;
        report(node.returnType.typeAnnotation, node.id.name);
      },
      TSCallSignatureDeclaration(node): void {
        const owner = owningInterface(node);
        if (
          owner === null ||
          !isExportedInterface(owner, typeExports) ||
          node.returnType == null
        )
          return;
        report(node.returnType.typeAnnotation, `${owner.id.name}.call`);
      },
      TSMethodSignature(node): void {
        const owner = owningInterface(node);
        const alias = owningTypeAlias(node);
        const memberName = staticMemberName(node.key);
        if (
          ((owner === null || !isExportedInterface(owner, typeExports)) &&
            (alias === null || !typeExports.has(alias.id.name))) ||
          node.returnType == null ||
          memberName === null
        )
          return;
        report(
          node.returnType.typeAnnotation,
          `${owner?.id.name ?? alias?.id.name ?? "type"}.${memberName}`,
        );
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
          annotation == null
        )
          return;
        const returnType = callableReturnType(annotation, aliases);
        if (returnType !== null) {
          report(
            returnType,
            `${owner?.id.name ?? alias?.id.name ?? "type"}.${memberName}`,
          );
        }
      },
      PropertyDefinition(node): void {
        if (
          node.accessibility === "private" ||
          node.accessibility === "protected"
        )
          return;
        const owner = owningClass(node);
        const annotation = node.typeAnnotation?.typeAnnotation;
        if (
          owner === null ||
          !isExportedClass(owner, specifierExports) ||
          annotation == null
        )
          return;
        const returnType = callableReturnType(annotation, aliases);
        if (returnType !== null) {
          const name =
            node.key.type === "Identifier" ? node.key.name : "property";
          report(returnType, name);
        }
      },
    };
  },
});

function variableBindingName(
  topLevel: ESTree.VariableDeclaration,
  node: ESTree.Node,
): string | null {
  for (const declarator of topLevel.declarations) {
    let initializer = declarator.init;
    while (
      initializer?.type === "TSAsExpression" ||
      initializer?.type === "TSSatisfiesExpression" ||
      initializer?.type === "TSNonNullExpression"
    )
      initializer = initializer.expression;
    if (declarator.id.type === "Identifier" && initializer === node)
      return declarator.id.name;
    if (
      declarator.id.type === "Identifier" &&
      (initializer?.type === "ClassExpression" ||
        initializer?.type === "ObjectExpression")
    ) {
      if (ownsMemberValue(initializer, node)) return declarator.id.name;
    }
  }
  return null;
}

function classBindingName(
  topLevel: ESTree.Class,
  node: ESTree.Node,
  defaultExport: boolean,
): string | null {
  let owner: ESTree.Node | null = node.parent;
  while (owner != null && owner.parent !== topLevel.body) owner = owner.parent;
  return (owner?.type === "MethodDefinition" ||
    owner?.type === "TSAbstractMethodDefinition" ||
    owner?.type === "PropertyDefinition") &&
    owner.value === node
    ? (topLevel.id?.name ?? (defaultExport ? "default" : null))
    : null;
}

function ownsMemberValue(
  initializer: ESTree.Class | ESTree.ObjectExpression,
  node: ESTree.Node,
): boolean {
  let owner: ESTree.Node | null = node.parent;
  const container =
    initializer.type === "ClassExpression" ? initializer.body : initializer;
  while (owner != null && owner.parent !== container) owner = owner.parent;
  return (
    (owner?.type === "MethodDefinition" ||
      owner?.type === "PropertyDefinition" ||
      owner?.type === "Property") &&
    owner.value === node
  );
}
