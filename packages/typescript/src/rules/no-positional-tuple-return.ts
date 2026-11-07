/**
 * @fileoverview no-positional-tuple-return — a positional tuple return names its fields only at the call site, so call sites disagree.
 *
 * Port of the 18.x `no-positional-tuple-return` rule. The rule is
 * untyped. The original compares absent `returnType`/`typeAnnotation` fields
 * to `undefined`; Oxlint gives null there, so under Oxlint the original skips
 * every inferred tuple `return` and throws on an exported `declare function`
 * without a return type. This port accepts null and undefined, which matches
 * the original under ESLint.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-positional-tuple-return.test.ts
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isPresent } from "../utils/is-present.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable } from "../utils/static-string.js";
import { labeledTupleObjectFix } from "./_labeled-tuple-object-fix.js";

const NAME = "no-positional-tuple-return";

interface TypeAliases {
  get(identifier: ESTree.IdentifierReference): Node | undefined;
}
type FunctionNode = ESTree.Function | ESTree.ArrowFunctionExpression;

const MIN_ELEMENTS = 2;

/** Type wrappers whose single type argument is the value actually returned. */
const AWAITABLE_TYPES: ReadonlySet<string> = new Set([
  "Promise",
  "PromiseLike",
  "Awaited",
  "Readonly",
]);

function staticMemberName(key: Node): string | null {
  if (key.type === "Identifier") return key.name;
  if (key.type === "Literal" && typeof key.value === "string") {
    return key.value;
  }
  return null;
}

function isConstReference(node: Node): boolean {
  return (
    node.type === "TSTypeReference" &&
    node.typeName.type === "Identifier" &&
    node.typeName.name === "const"
  );
}

/** The first boundary tuple in a return annotation, unwrapping transparent wrappers and unions. */
function tupleReturnType(
  node: Node,
  aliases: TypeAliases,
  resolving: ReadonlySet<string> = new Set(),
): ESTree.TSTupleType | null {
  switch (node.type) {
    case "TSTupleType": return node;
    case "TSTypeReference": return referencedTuple(node, aliases, resolving);
    case "TSTypeOperator":
      return node.operator === "readonly" ? tupleReturnType(node.typeAnnotation, aliases, resolving) : null;
    case "TSUnionType":
    case "TSIntersectionType":
      for (const member of node.types) {
        const tuple = tupleReturnType(member, aliases, resolving);
        if (tuple !== null) return tuple;
      }
      return null;
    default: return null;
  }
}

/** The tuple behind an awaitable wrapper's type argument or a local type alias. */
function referencedTuple(
  node: ESTree.TSTypeReference,
  aliases: TypeAliases,
  resolving: ReadonlySet<string>,
): ESTree.TSTupleType | null {
  if (node.typeName.type !== "Identifier") return null;
  const name = node.typeName.name;
  if (AWAITABLE_TYPES.has(name)) {
    const argument = node.typeArguments?.params.at(0);
    return argument === undefined ? null : tupleReturnType(argument, aliases, resolving);
  }
  const target = resolving.has(name) ? undefined : aliases.get(node.typeName);
  return target === undefined ? null : tupleReturnType(target, aliases, new Set([...resolving, name]));
}

function tupleExpression(
  node: Node,
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
  if (node.type === "TSAsExpression" && isConstReference(node.typeAnnotation))
    return node.expression;
  return tupleReturnType(node.typeAnnotation, aliases) === null
    ? null
    : node.expression;
}

/** The outermost `as`, `satisfies` or `!` wrapper around `node`, or `node` itself. */
function outermostWrapper(node: Node): Node {
  let wrapped = node;
  for (let parent = parentOf(wrapped); parent !== null; parent = parentOf(wrapped)) {
    if ((parent.type !== "TSAsExpression" && parent.type !== "TSSatisfiesExpression" &&
      parent.type !== "TSNonNullExpression") || parent.expression !== wrapped) break;
    wrapped = parent;
  }
  return wrapped;
}

/** The declared name of a function-ish node, or null for an anonymous one. */
function functionName(node: Node): string | null {
  if (node.type === "FunctionDeclaration") {
    return node.id?.name ?? (parentOf(node)?.type === "ExportDefaultDeclaration" ? "default" : null);
  }
  const parent = parentOf(outermostWrapper(node));
  switch (parent?.type) {
    case "ExportDefaultDeclaration": return "default";
    case "VariableDeclarator": return parent.id.type === "Identifier" ? parent.id.name : null;
    case "MethodDefinition":
    case "TSAbstractMethodDefinition":
    case "PropertyDefinition":
    case "Property": return parent.key.type === "Identifier" ? parent.key.name : null;
    default: return null;
  }
}

/**
 * TanStack Query key factories intentionally return readonly arrays as opaque
 * cache identities, not positional records.  Recognize only the conventional,
 * syntax-proven factory shape: a const object named `*Keys`, frozen with
 * `as const`, and anchored by an `all` array literal. The outer assertion
 * supplies its const context; an explicit inner assertion is also supported.
 */
function isQueryKeyFactory(node: FunctionNode): boolean {
  const wrapped = outermostWrapper(node);
  const property = parentOf(wrapped);
  if (property?.type !== "Property" || property.value !== wrapped)
    return false;
  const object = parentOf(property);
  return object?.type === "ObjectExpression" && isConstKeysObject(object) && hasConstAllKey(object);
}

/** `const *Keys = { ... } as const`. */
function isConstKeysObject(object: ESTree.ObjectExpression): boolean {
  const assertion = parentOf(object);
  if (
    assertion?.type !== "TSAsExpression" ||
    assertion.expression !== object ||
    !isConstReference(assertion.typeAnnotation)
  )
    return false;
  const declarator = parentOf(assertion);
  const declaration = declarator === null ? null : parentOf(declarator);
  return declarator?.type === "VariableDeclarator" &&
    declarator.id.type === "Identifier" &&
    /Keys$/i.test(declarator.id.name) &&
    declaration?.type === "VariableDeclaration" &&
    declaration.kind === "const";
}

/** An `all` property holding an array literal, frozen by the outer or its own `as const`. */
function hasConstAllKey(object: ESTree.ObjectExpression): boolean {
  return object.properties.some((candidate) => {
    if (
      candidate.type !== "Property" ||
      staticMemberName(candidate.key) !== "all"
    )
      return false;
    if (candidate.value.type === "ArrayExpression")
      return !candidate.computed;
    return (
      candidate.value.type === "TSAsExpression" &&
      candidate.value.expression.type === "ArrayExpression" &&
      isConstReference(candidate.value.typeAnnotation)
    );
  });
}

function specifierExportedNames(program: ESTree.Program): ReadonlySet<string> {
  const names = new Set<string>();
  for (const statement of program.body) {
    if (
      statement.type === "ExportNamedDeclaration" &&
      statement.declaration === null &&
      statement.source === null &&
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
      statement.type === "ExportDefaultDeclaration" &&
      (statement.declaration.type === "TSInterfaceDeclaration" ||
        (statement.declaration as Node).type === "TSTypeAliasDeclaration")
    )
      names.add((statement.declaration as ESTree.TSInterfaceDeclaration).id.name);
    if (statement.type !== "ExportNamedDeclaration" || statement.source !== null)
      continue;
    if (
      statement.declaration?.type === "TSInterfaceDeclaration" ||
      statement.declaration?.type === "TSTypeAliasDeclaration"
    )
      names.add(statement.declaration.id.name);
    for (const specifier of statement.specifiers)
      names.add((specifier.local as { name: string }).name);
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
      if (declaration === undefined) return undefined;
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
  node: Node,
  aliases: TypeAliases,
  resolving: ReadonlySet<string> = new Set(),
): Node | null {
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

function owningInterface(node: Node): ESTree.TSInterfaceDeclaration | null {
  for (let current = parentOf(node); current !== null; current = parentOf(current)) {
    if (current.type === "TSInterfaceDeclaration") return current;
    if (current.type === "Program") return null;
  }
  return null;
}

function owningClass(node: Node): ESTree.Class | null {
  for (let current = parentOf(node); current !== null; current = parentOf(current)) {
    if (current.type === "ClassDeclaration" || current.type === "ClassExpression") {
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
  const parent = parentOf(node);
  if (
    parent?.type === "ExportNamedDeclaration" ||
    parent?.type === "ExportDefaultDeclaration"
  )
    return true;
  if (node.type === "ClassDeclaration") {
    return (
      node.id !== null &&
      parent?.type === "Program" &&
      specifierExports.has(node.id.name)
    );
  }
  return parent?.type === "VariableDeclarator" && parent.id.type === "Identifier" &&
    (specifierExports.has(parent.id.name) || isInlineExported(parent));
}

/** `export const C = class {}` at module scope; a namespace's `export` does not count. */
function isInlineExported(declarator: ESTree.VariableDeclarator): boolean {
  const declaration = parentOf(declarator);
  const exported = declaration === null ? null : parentOf(declaration);
  return exported?.type === "ExportNamedDeclaration" && parentOf(exported)?.type === "Program";
}

function isExportedInterface(
  node: ESTree.TSInterfaceDeclaration,
  exports: ReadonlySet<string>,
): boolean {
  const parent = parentOf(node);
  return (
    parent?.type === "ExportNamedDeclaration" ||
    parent?.type === "ExportDefaultDeclaration" ||
    (parent?.type === "Program" && exports.has(node.id.name))
  );
}

/** The name of the exported interface or type alias that owns a type member, or null. */
function exportedTypeOwner(node: Node, typeExports: ReadonlySet<string>): string | null {
  const owner = owningInterface(node);
  const alias = owningTypeAlias(node);
  const exported = (owner !== null && isExportedInterface(owner, typeExports)) ||
    (alias !== null && typeExports.has(alias.id.name));
  return exported ? (owner ?? alias)?.id.name ?? null : null;
}

function owningTypeAlias(node: Node): ESTree.TSTypeAliasDeclaration | null {
  for (let current = parentOf(node); current !== null; current = parentOf(current)) {
    if (current.type === "TSTypeAliasDeclaration") return current;
    if (current.type === "Program") return null;
  }
  return null;
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description:
        "Disallow returning a multi-field tuple from a named function; return a named object so call sites cannot mismatch slots.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      noPositionalTupleReturn:
        "`{{name}}` returns a {{count}}-field tuple, so callers depend on positional slots that can be reordered silently. Return a named object instead.",
    },
  },
  createOnce(context) {
    let specifierExports: ReadonlySet<string> = new Set();
    let typeExports: ReadonlySet<string> = new Set();
    let aliases: TypeAliases = { get: () => undefined };
    let reportedFunctions = new WeakSet<FunctionNode>();
    const functionStack: FunctionNode[] = [];

    const report = (annotation: Node, name: string): void => {
      const tuple = tupleReturnType(annotation, aliases);
      if (tuple === null || tuple.elementTypes.length < MIN_ELEMENTS) return;
      const fix = labeledTupleObjectFix(context.sourceCode, annotation);
      context.report({
        node: annotation,
        messageId: "noPositionalTupleReturn",
        data: { name, count: String(tuple.elementTypes.length) },
        ...(fix !== null && { fix }),
      });
    };
    const reportExpression = (node: FunctionNode, expression: Node): void => {
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
      if (!isPresent(annotation)) {
        if (node.type === "ArrowFunctionExpression" && node.expression) {
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
      before() {
        const sourceCode = context.sourceCode;
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, sourceCode.text)) return false;
        specifierExports = specifierExportedNames(sourceCode.ast);
        typeExports = publiclyReachableTypeNames(sourceCode.ast, exportedTypeNames(sourceCode.ast));
        aliases = typeAliases(sourceCode);
        reportedFunctions = new WeakSet<FunctionNode>();
        functionStack.length = 0;
        return undefined;
      },
      FunctionDeclaration: enterFunction,
      "FunctionDeclaration:exit": exitFunction,
      FunctionExpression: enterFunction,
      "FunctionExpression:exit": exitFunction,
      ArrowFunctionExpression: enterFunction,
      "ArrowFunctionExpression:exit": exitFunction,
      TSEmptyBodyFunctionExpression: enterFunction,
      "TSEmptyBodyFunctionExpression:exit": exitFunction,
      ReturnStatement(node: ESTree.ReturnStatement): void {
        const owner = functionStack.at(-1);
        if (
          owner === undefined ||
          isPresent(owner.returnType) ||
          node.argument === null
        )
          return;
        reportExpression(owner, node.argument);
      },
      TSDeclareFunction(node: ESTree.Function): void {
        const parent = parentOf(node);
        if (
          node.id === null ||
          !isPresent(node.returnType) ||
          (parent?.type !== "ExportNamedDeclaration" &&
            parent?.type !== "ExportDefaultDeclaration" &&
            !specifierExports.has(node.id.name))
        )
          return;
        report(node.returnType.typeAnnotation, node.id.name);
      },
      TSCallSignatureDeclaration(node: ESTree.TSCallSignatureDeclaration): void {
        const owner = owningInterface(node);
        if (
          owner === null ||
          !isExportedInterface(owner, typeExports) ||
          !isPresent(node.returnType)
        )
          return;
        report(node.returnType.typeAnnotation, `${owner.id.name}.call`);
      },
      TSMethodSignature(node: ESTree.TSMethodSignature): void {
        const owner = exportedTypeOwner(node, typeExports);
        const memberName = staticMemberName(node.key);
        if (owner === null || !isPresent(node.returnType) || memberName === null) return;
        report(node.returnType.typeAnnotation, `${owner}.${memberName}`);
      },
      TSTypeAliasDeclaration(node: ESTree.TSTypeAliasDeclaration): void {
        if (!typeExports.has(node.id.name)) return;
        const returnType = callableReturnType(node.typeAnnotation, aliases);
        if (returnType !== null) report(returnType, node.id.name);
      },
      TSPropertySignature(node: ESTree.TSPropertySignature): void {
        const owner = exportedTypeOwner(node, typeExports);
        const annotation = node.typeAnnotation?.typeAnnotation;
        const memberName = staticMemberName(node.key);
        if (owner === null || memberName === null || !isPresent(annotation)) return;
        const returnType = callableReturnType(annotation, aliases);
        if (returnType !== null) report(returnType, `${owner}.${memberName}`);
      },
      PropertyDefinition(node: ESTree.PropertyDefinition): void {
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
          !isPresent(annotation)
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
