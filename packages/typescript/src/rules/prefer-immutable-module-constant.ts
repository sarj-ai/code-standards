/**
 * @fileoverview prefer-immutable-module-constant — module constants should expose readonly collection state.
 *
 * Port of the 18.x `prefer-immutable-module-constant` rule. The rule is
 * untyped, so the port covers all of it. Under Oxlint the original reads
 * `typeAnnotation.typeAnnotation` on Oxlint's `null` (TS-ESTree: `undefined`)
 * and crashes on every unannotated candidate; the port accepts both, which is
 * the ESLint behavior.
 */

import type { Fixer } from "@oxlint/plugins";

import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { hasLocalValueBinding } from "../utils/has-local-value-binding.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable } from "../utils/static-string.js";
import { isUnusedPrivateBinding } from "../utils/unused-private-binding.js";

const NAME = "prefer-immutable-module-constant";

type Identifier = ESTree.IdentifierReference | ESTree.BindingIdentifier | ESTree.IdentifierName;

const CONSTANT_NAME = /^_?[A-Z][A-Z0-9_]*$/;
const JAVASCRIPT_FILE_RE = /\.[cm]?jsx?$/i;
const MUTATING_METHODS: ReadonlySet<string> = new Set([
  "add",
  "clear",
  "copyWithin",
  "delete",
  "fill",
  "pop",
  "push",
  "reverse",
  "set",
  "shift",
  "sort",
  "splice",
  "unshift",
]);

function isAsConst(node: Node, sourceCode: SourceCode): boolean {
  if (node.type === "TSSatisfiesExpression" || node.type === "TSNonNullExpression") {
    return isAsConst(node.expression, sourceCode);
  }
  if (node.type !== "TSAsExpression") return false;
  return sourceCode.getText(node.typeAnnotation).trim() === "const";
}

/** Strip type-only wrappers without treating a mutable assertion as readonly. */
function unwrapExpression(node: Node): Node {
  if (
    node.type === "TSAsExpression" ||
    node.type === "TSSatisfiesExpression" ||
    node.type === "TSNonNullExpression"
  ) {
    return unwrapExpression(node.expression);
  }
  return node;
}

type GlobalResolver = (identifier: Identifier) => boolean;
type LocalType = ESTree.TSTypeAliasDeclaration | ESTree.TSTypeParameter;
type LocalTypeResolver = (identifier: Identifier) => LocalType | undefined;
type TypeArguments = ReadonlyMap<ESTree.TSTypeParameter, TypeArgument>;
type ReadonlyState = "readonly" | "mutable" | "unknown";
type TypeArgument = {
  readonly node: Node;
  readonly arguments: TypeArguments;
  readonly seen: ReadonlySet<Node>;
};

/** `Object.<method>` on the unshadowed global `Object`. */
function isObjectMethod(callee: Node, method: string, isUnshadowedGlobal: GlobalResolver): boolean {
  return (
    callee.type === "MemberExpression" &&
    !callee.computed &&
    callee.object.type === "Identifier" &&
    callee.object.name === "Object" &&
    isUnshadowedGlobal(callee.object) &&
    callee.property.type === "Identifier" &&
    callee.property.name === method
  );
}

/** The argument of an unshadowed `Object.freeze(value)` call, or null. */
function frozenArgument(node: Node, isUnshadowedGlobal: GlobalResolver): Node | null {
  if (node.type !== "CallExpression" || !isObjectMethod(node.callee, "freeze", isUnshadowedGlobal) || node.arguments.length !== 1) {
    return null;
  }
  const argument = node.arguments[0];
  return argument === undefined || argument.type === "SpreadElement" ? null : argument;
}

function isObjectFreeze(node: Node, isUnshadowedGlobal: GlobalResolver): boolean {
  const argument = frozenArgument(unwrapExpression(node), isUnshadowedGlobal);
  return argument !== null && collectionKind(argument, isUnshadowedGlobal) === "literal";
}

function collectionKind(node: Node, isUnshadowedGlobal: GlobalResolver): "literal" | "Set" | "Map" | null {
  const inner = unwrapExpression(node);
  const frozen = frozenArgument(inner, isUnshadowedGlobal);
  if (frozen !== null) return collectionKind(frozen, isUnshadowedGlobal);
  if (inner.type === "ArrayExpression" || inner.type === "ObjectExpression") {
    return "literal";
  }
  if (
    inner.type === "NewExpression" &&
    inner.callee.type === "Identifier" &&
    (inner.callee.name === "Set" || inner.callee.name === "Map") &&
    isUnshadowedGlobal(inner.callee)
  ) {
    return inner.callee.name;
  }
  return null;
}

function declaredReadonlyType(
  node: ESTree.VariableDeclarator,
  kind: "literal" | "Set" | "Map",
  resolveLocalType: LocalTypeResolver,
  isUnshadowedType: GlobalResolver,
): boolean {
  // Oxlint leaves a missing annotation `null` where TS-ESTree leaves it `undefined`.
  const annotation = node.id.type === "Identifier" ? node.id.typeAnnotation ?? undefined : undefined;
  if (annotation !== undefined && readonlyTypeState(annotation.typeAnnotation, kind, resolveLocalType, isUnshadowedType) === "readonly") {
    return true;
  }
  return node.init?.type === "TSAsExpression" &&
    readonlyTypeState(node.init.typeAnnotation, kind, resolveLocalType, isUnshadowedType) === "readonly";
}

function readonlyTypeState(
  node: Node,
  kind: "literal" | "Set" | "Map",
  resolveLocalType: LocalTypeResolver,
  isUnshadowedType: GlobalResolver,
  arguments_: TypeArguments = new Map(),
  seen: ReadonlySet<Node> = new Set(),
): ReadonlyState {
  if (seen.has(node)) return "unknown";
  if (node.type !== "TSTypeReference" || node.typeName.type !== "Identifier") {
    return directReadonlyState(node, kind, isUnshadowedType);
  }
  const declaration = resolveLocalType(node.typeName);
  if (declaration === undefined) return directReadonlyState(node, kind, isUnshadowedType);
  if (declaration.type === "TSTypeParameter") {
    const argument = arguments_.get(declaration);
    return argument === undefined ? "unknown" : readonlyTypeState(
      argument.node, kind, resolveLocalType, isUnshadowedType, argument.arguments, argument.seen,
    );
  }
  const expanded = new Set([...seen, node]);
  return readonlyTypeState(
    declaration.typeAnnotation, kind, resolveLocalType, isUnshadowedType,
    bindTypeArguments(declaration, node, arguments_, expanded), expanded,
  );
}

function bindTypeArguments(
  declaration: ESTree.TSTypeAliasDeclaration,
  reference: ESTree.TSTypeReference,
  arguments_: TypeArguments,
  seen: ReadonlySet<Node>,
): TypeArguments {
  const bindings = new Map(arguments_);
  for (const [index, parameter] of (declaration.typeParameters?.params ?? []).entries()) {
    const argument = reference.typeArguments?.params[index];
    const node = argument ?? parameter.default ?? undefined;
    if (node !== undefined) {
      bindings.set(parameter, { node, arguments: argument === undefined ? new Map(bindings) : arguments_, seen });
    }
  }
  return bindings;
}

function directReadonlyState(node: Node, kind: "literal" | "Set" | "Map", isUnshadowedType: GlobalResolver): ReadonlyState {
  if (node.type === "TSTypeOperator" && node.operator === "readonly") {
    return "readonly";
  }
  if (node.type === "TSTypeLiteral") {
    if (node.members.length === 0) return "unknown";
    const readonly = kind === "literal" && node.members.every((member) =>
      (member.type === "TSPropertySignature" || member.type === "TSIndexSignature") && member.readonly,
    );
    return readonly ? "readonly" : "mutable";
  }
  if (node.type === "TSArrayType" || node.type === "TSTupleType") return "mutable";
  if (node.type !== "TSTypeReference" || node.typeName.type !== "Identifier" || !isUnshadowedType(node.typeName)) {
    return "unknown";
  }
  return globalTypeState(node.typeName.name, kind);
}

/** The state a global `Readonly`, collection or readonly-collection type gives a `kind` value. */
function globalTypeState(name: string, kind: "literal" | "Set" | "Map"): ReadonlyState {
  if (name === "Readonly") return kind === "literal" ? "readonly" : "mutable";
  if (["Array", "Map", "Set"].includes(name)) return "mutable";
  if (!["ReadonlyArray", "ReadonlyMap", "ReadonlySet"].includes(name)) return "unknown";
  const readonly = kind === "literal" ? name === "ReadonlyArray" : name === `Readonly${kind}`;
  return readonly ? "readonly" : "mutable";
}

function hasUnknownExplicitType(
  node: ESTree.VariableDeclarator,
  kind: "literal" | "Set" | "Map",
  resolveLocalType: LocalTypeResolver,
  isUnshadowedType: GlobalResolver,
): boolean {
  const annotation = (node.id.type === "Identifier" ? node.id.typeAnnotation?.typeAnnotation : undefined) ??
    (node.init?.type === "TSAsExpression" ? node.init.typeAnnotation : undefined);
  if (annotation === undefined) return false;
  if (annotation.type === "TSArrayType" || annotation.type === "TSTypeOperator") return false;
  if (annotation.type !== "TSTypeReference" || annotation.typeName.type !== "Identifier") return true;
  if (resolveLocalType(annotation.typeName) !== undefined) {
    return readonlyTypeState(annotation, kind, resolveLocalType, isUnshadowedType) === "unknown";
  }
  return !isUnshadowedType(annotation.typeName) ||
    !["Array", "Map", "Readonly", "ReadonlyArray", "ReadonlyMap", "ReadonlySet", "Set"].includes(annotation.typeName.name);
}

function referenceMutates(identifier: Identifier, isUnshadowedGlobal: GlobalResolver): boolean {
  const parent = identifier.parent;
  if (parent?.type === "MemberExpression" && parent.object === identifier) return memberChainMutates(parent);
  // `Object.assign(CONSTANT, …)`
  return parent?.type === "CallExpression" && parent.arguments[0] === identifier &&
    isObjectMethod(parent.callee, "assign", isUnshadowedGlobal);
}

/** Whether `object.a.b` is written, deleted, or receives a mutating method call. */
function memberChainMutates(start: ESTree.MemberExpression): boolean {
  let member = start;
  while (member.parent.type === "MemberExpression" && member.parent.object === member) member = member.parent;
  const parent = member.parent;
  if (parent.type === "AssignmentExpression") return parent.left === member;
  if (parent.type === "UpdateExpression") return parent.argument === member;
  if (parent.type === "UnaryExpression") return parent.operator === "delete" && parent.argument === member;
  return parent.type === "CallExpression" && parent.callee === member && MUTATING_METHODS.has(staticMemberName(member) ?? "");
}

/** `a.b` or `a["b"]`. */
function staticMemberName(member: ESTree.MemberExpression): string | null {
  if (member.property.type === "Identifier" && !member.computed) return member.property.name;
  return member.property.type === "Literal" && typeof member.property.value === "string" ? member.property.value : null;
}

/** `const NAME = [ … ]` or `const NAME = { … }` with no type annotation, where `as const` can be appended. */
function isUnannotatedLiteral(id: ESTree.BindingIdentifier, init: ESTree.Expression): boolean {
  return (id.typeAnnotation === undefined || id.typeAnnotation === null) && (init.type === "ObjectExpression" || init.type === "ArrayExpression");
}

/** A `const NAME = …` directly at module level, or directly exported, with an initializer. */
function moduleConstDeclarator(node: ESTree.VariableDeclarator): {
  readonly id: ESTree.BindingIdentifier;
  readonly init: ESTree.Expression;
  readonly directlyExported: boolean;
} | null {
  const declaration = node.parent;
  if (declaration.type !== "VariableDeclaration" || declaration.kind !== "const" || node.id.type !== "Identifier" || node.init === null) {
    return null;
  }
  const container = declaration.parent;
  const directlyExported = container.type === "ExportNamedDeclaration" && container.parent.type === "Program";
  return container.type === "Program" || directlyExported ? { id: node.id, init: node.init, directlyExported } : null;
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description:
        "Require module-level constant collections to expose readonly state.",
      url: docsUrl(NAME),
    },
    schema: [],
    defaultOptions: [],
    messages: {
      preferAsConst:
        "Module constant `{{name}}` exposes a mutable literal. Add `as const` or a readonly surface to prevent ordinary mutation through the binding.",
      preferReadonlyCollection:
        "Module constant `{{name}}` is a mutable {{kind}}. Expose it as `Readonly{{kind}}` or an immutable collection.",
    },
  },
  createOnce(context) {
    const isUnshadowedGlobal: GlobalResolver = (identifier) => !hasLocalValueBinding(context.sourceCode, identifier);
    const isUnshadowedType: GlobalResolver = (identifier) => {
      const variable = findVariable(context.sourceCode.getScope(identifier), identifier.name);
      return variable === null || !variable.defs.some((definition) => definition.isTypeDefinition);
    };
    const resolveLocalType: LocalTypeResolver = (identifier) => {
      const variable = findVariable(context.sourceCode.getScope(identifier), identifier.name);
      const definitions = variable?.defs.filter((definition) => definition.isTypeDefinition) ?? [];
      const declaration = definitions.length === 1 ? definitions[0]?.node : undefined;
      return declaration?.type === "TSTypeAliasDeclaration" || declaration?.type === "TSTypeParameter"
        ? declaration : undefined;
    };
    const exportedNames = new Set<string>();
    const mutatesThroughAlias = (root: TsVariable): boolean => {
      const pending = [root];
      const seen = new Set<TsVariable>();
      while (pending.length > 0) {
        const variable = pending.pop();
        if (variable === undefined || seen.has(variable)) continue;
        seen.add(variable);
        for (const reference of variable.references) {
          const identifier = reference.identifier;
          if (identifier.type !== "Identifier") continue;
          if (referenceMutates(identifier, isUnshadowedGlobal)) return true;
          const declarator = identifier.parent;
          if (
            declarator.type !== "VariableDeclarator" ||
            declarator.init !== identifier ||
            declarator.id.type !== "Identifier" ||
            declarator.parent.type !== "VariableDeclaration"
          ) {
            continue;
          }
          const alias = context.sourceCode.getDeclaredVariables(declarator)[0];
          if (alias !== undefined) pending.push(alias as TsVariable);
        }
      }
      return false;
    };
    /** The collection `init` builds, unless the declaration types it readonly or with a type this rule cannot read. */
    const mutableCollectionKind = (node: ESTree.VariableDeclarator, init: Node): "literal" | "Set" | "Map" | null => {
      const kind = collectionKind(init, isUnshadowedGlobal);
      if (kind === null || declaredReadonlyType(node, kind, resolveLocalType, isUnshadowedType) ||
        hasUnknownExplicitType(node, kind, resolveLocalType, isUnshadowedType)) return null;
      return kind;
    };
    return {
      before() {
        const sourceCode = context.sourceCode;
        if (
          JAVASCRIPT_FILE_RE.test(context.filename) ||
          isTestFile({ filename: context.filename, cwd: context.cwd }) ||
          isGeneratedFile({ filename: context.filename, cwd: context.cwd }, sourceCode.getText())
        ) {
          return false;
        }
        exportedNames.clear();
        return undefined;
      },
      Program(node: ESTree.Program): void {
        function collectModuleBindings(statement: ESTree.Program["body"][number]): void {
          if (statement.type === "ExportNamedDeclaration") {
            if (statement.source !== null || statement.exportKind === "type") return;
            for (const specifier of statement.specifiers) {
              if (specifier.type === "ExportSpecifier" && specifier.exportKind !== "type" && specifier.local.type === "Identifier") {
                exportedNames.add(specifier.local.name);
              }
            }
          } else if (statement.type === "ExportDefaultDeclaration") {
            const exported = unwrapTransparentExport(statement.declaration);
            if (exported.type === "Identifier") exportedNames.add(exported.name);
          }
        }

        for (const statement of node.body) { collectModuleBindings(statement); }
      },
      VariableDeclarator(node: ESTree.VariableDeclarator): void {
        const sourceCode = context.sourceCode;
        const candidate = moduleConstDeclarator(node);
        if (candidate === null) return;
        const { id, init } = candidate;
        const exported = candidate.directlyExported || exportedNames.has(id.name);
        if (!CONSTANT_NAME.test(id.name) && !exported) return;
        if (isAsConst(init, sourceCode) || isObjectFreeze(init, isUnshadowedGlobal)) return;
        const kind = mutableCollectionKind(node, init);
        if (kind === null) return;
        const variable = sourceCode.getDeclaredVariables(node)[0];
        if (!exported && variable !== undefined && mutatesThroughAlias(variable as TsVariable)) return;
        const fixable = kind === "literal" && isUnannotatedLiteral(id, init) && isUnusedPrivateBinding(sourceCode, node, id, context.filename);
        context.report({
          node: id,
          messageId: kind === "literal" ? "preferAsConst" : "preferReadonlyCollection",
          data: { name: id.name, kind },
          ...(fixable && { fix: (fixer: Fixer) => fixer.insertTextAfter(init, " as const") }),
        });
      },
    };
  },
});


function unwrapTransparentExport(node: Node): Node {
  if (node.type === "TSSatisfiesExpression" || node.type === "TSNonNullExpression") {
    return unwrapTransparentExport(node.expression);
  }
  return node;
}
