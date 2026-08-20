/**
 * @fileoverview prefer-immutable-module-constant — module constants should expose readonly collection state.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-immutable-module-constant.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESTree } from "@typescript-eslint/utils";
import type { Scope } from "@typescript-eslint/utils/ts-eslint";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "preferAsConst" | "preferReadonlyCollection";
type Options = readonly [];

export const preferImmutableModuleConstantDocumentation = {
  summary: "Require module-level constant collections to expose readonly state.",
  rationale:
    "A const binding prevents reassignment but does not stop callers from mutating its array, object, Set, or Map contents.",
  remediation:
    "Expose literals with `as const` or a readonly type, and expose Set or Map values through ReadonlySet or ReadonlyMap.",
  category: "correctness",
  limitations: [
    "The rule skips generated files, test files, JavaScript files, and collections that are deliberately mutated in their declaring module.",
  ],
  examples: [
    {
      id: "readonly-array-literal",
      title: "A module constant exposes a readonly literal",
      outcome: "no-match",
      files: [{ path: "src/constants.ts", source: "const VALUES = [1, 2, 3] as const;" }],
      focusPath: "src/constants.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "mutable-array-literal",
      title: "A module constant exposes a mutable array",
      outcome: "match",
      files: [{ path: "src/constants.ts", source: "const VALUES = [1, 2, 3];" }],
      focusPath: "src/constants.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

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

function isAsConst(node: TSESTree.Node, sourceText: (node: TSESTree.Node) => string): boolean {
  if (node.type === AST_NODE_TYPES.TSSatisfiesExpression || node.type === AST_NODE_TYPES.TSNonNullExpression) {
    return isAsConst(node.expression, sourceText);
  }
  if (node.type !== AST_NODE_TYPES.TSAsExpression) return false;
  return sourceText(node.typeAnnotation).trim() === "const";
}

/** Strip type-only wrappers without treating a mutable assertion as readonly. */
function unwrapExpression(node: TSESTree.Node): TSESTree.Node {
  if (
    node.type === AST_NODE_TYPES.TSAsExpression ||
    node.type === AST_NODE_TYPES.TSSatisfiesExpression ||
    node.type === AST_NODE_TYPES.TSNonNullExpression
  ) {
    return unwrapExpression(node.expression);
  }
  return node;
}

type GlobalResolver = (identifier: TSESTree.Identifier) => boolean;

function isObjectFreeze(node: TSESTree.Node, isUnshadowedGlobal: GlobalResolver): boolean {
  const inner = unwrapExpression(node);
  if (
    inner.type === AST_NODE_TYPES.CallExpression &&
    inner.callee.type === AST_NODE_TYPES.MemberExpression &&
    !inner.callee.computed &&
    inner.callee.object.type === AST_NODE_TYPES.Identifier &&
    inner.callee.object.name === "Object" &&
    isUnshadowedGlobal(inner.callee.object) &&
    inner.callee.property.type === AST_NODE_TYPES.Identifier &&
    inner.callee.property.name === "freeze" &&
    inner.arguments.length === 1
  ) {
    const argument = inner.arguments[0];
    return argument !== undefined && argument.type !== AST_NODE_TYPES.SpreadElement && collectionKind(argument, isUnshadowedGlobal) === "literal";
  }
  return false;
}

function collectionKind(node: TSESTree.Node, isUnshadowedGlobal: GlobalResolver): "literal" | "Set" | "Map" | null {
  const inner = unwrapExpression(node);
  if (
    inner.type === AST_NODE_TYPES.CallExpression &&
    inner.callee.type === AST_NODE_TYPES.MemberExpression &&
    !inner.callee.computed &&
    inner.callee.object.type === AST_NODE_TYPES.Identifier &&
    inner.callee.object.name === "Object" &&
    isUnshadowedGlobal(inner.callee.object) &&
    inner.callee.property.type === AST_NODE_TYPES.Identifier &&
    inner.callee.property.name === "freeze" &&
    inner.arguments.length === 1 &&
    inner.arguments[0] !== undefined &&
    inner.arguments[0].type !== AST_NODE_TYPES.SpreadElement
  ) {
    return collectionKind(inner.arguments[0], isUnshadowedGlobal);
  }
  if (inner.type === AST_NODE_TYPES.ArrayExpression || inner.type === AST_NODE_TYPES.ObjectExpression) {
    return "literal";
  }
  if (
    inner.type === AST_NODE_TYPES.NewExpression &&
    inner.callee.type === AST_NODE_TYPES.Identifier &&
    (inner.callee.name === "Set" || inner.callee.name === "Map") &&
    isUnshadowedGlobal(inner.callee)
  ) {
    return inner.callee.name;
  }
  return null;
}

function declaredReadonlyType(
  node: TSESTree.VariableDeclarator,
  kind: "literal" | "Set" | "Map",
  aliases: ReadonlyMap<string, TSESTree.Node>,
): boolean {
  const annotation = node.id.type === AST_NODE_TYPES.Identifier ? node.id.typeAnnotation : undefined;
  if (annotation !== undefined && isReadonlyTypeResolved(annotation.typeAnnotation, kind, aliases)) {
    return true;
  }
  return node.init?.type === AST_NODE_TYPES.TSAsExpression &&
    isReadonlyTypeResolved(node.init.typeAnnotation, kind, aliases);
}

function isReadonlyTypeResolved(
  node: TSESTree.Node,
  kind: "literal" | "Set" | "Map",
  aliases: ReadonlyMap<string, TSESTree.Node>,
  seen: ReadonlySet<string> = new Set(),
): boolean {
  if (isReadonlyType(node, kind)) return true;
  if (node.type !== AST_NODE_TYPES.TSTypeReference || node.typeName.type !== AST_NODE_TYPES.Identifier) return false;
  const name = node.typeName.name;
  const target = aliases.get(name);
  if (target === undefined || seen.has(name)) return false;
  return isReadonlyTypeResolved(target, kind, aliases, new Set([...seen, name]));
}

function isReadonlyType(node: TSESTree.Node, kind: "literal" | "Set" | "Map"): boolean {
  if (node.type === AST_NODE_TYPES.TSTypeOperator && node.operator === "readonly") {
    return true;
  }
  if (
    node.type !== AST_NODE_TYPES.TSTypeReference ||
    node.typeName.type !== AST_NODE_TYPES.Identifier
  ) {
    return false;
  }
  if (node.typeName.name === "Readonly") {
    return kind === "literal";
  }
  return kind === "literal"
    ? node.typeName.name === "ReadonlyArray"
    : node.typeName.name === `Readonly${kind}`;
}

function hasUnknownExplicitType(
  node: TSESTree.VariableDeclarator,
  aliases: ReadonlyMap<string, TSESTree.Node>,
): boolean {
  const annotation = node.id.type === AST_NODE_TYPES.Identifier ? node.id.typeAnnotation?.typeAnnotation : undefined;
  if (annotation === undefined) return false;
  if (annotation.type === AST_NODE_TYPES.TSArrayType || annotation.type === AST_NODE_TYPES.TSTypeOperator) return false;
  if (annotation.type !== AST_NODE_TYPES.TSTypeReference || annotation.typeName.type !== AST_NODE_TYPES.Identifier) return true;
  return !aliases.has(annotation.typeName.name) &&
    !["Array", "Map", "Readonly", "ReadonlyArray", "ReadonlyMap", "ReadonlySet", "Set"].includes(annotation.typeName.name);
}

function referenceMutates(identifier: TSESTree.Identifier, isUnshadowedGlobal: GlobalResolver): boolean {
  let member = identifier.parent;
  if (
    member?.type !== AST_NODE_TYPES.MemberExpression ||
    member.object !== identifier
  ) {
    return (
      member?.type === AST_NODE_TYPES.CallExpression &&
      member.arguments[0] === identifier &&
      member.callee.type === AST_NODE_TYPES.MemberExpression &&
      !member.callee.computed &&
      member.callee.object.type === AST_NODE_TYPES.Identifier &&
      member.callee.object.name === "Object" &&
      isUnshadowedGlobal(member.callee.object) &&
      member.callee.property.type === AST_NODE_TYPES.Identifier &&
      member.callee.property.name === "assign"
    );
  }
  while (
    member.parent.type === AST_NODE_TYPES.MemberExpression &&
    member.parent.object === member
  ) {
    member = member.parent;
  }
  const parent = member.parent;
  if (parent?.type === AST_NODE_TYPES.AssignmentExpression && parent.left === member) {
    return true;
  }
  if (parent?.type === AST_NODE_TYPES.UpdateExpression && parent.argument === member) {
    return true;
  }
  if (parent?.type === AST_NODE_TYPES.UnaryExpression && parent.operator === "delete" && parent.argument === member) {
    return true;
  }
  return (
    parent?.type === AST_NODE_TYPES.CallExpression &&
    parent.callee === member &&
    ((member.property.type === AST_NODE_TYPES.Identifier && !member.computed) ||
      (member.property.type === AST_NODE_TYPES.Literal && typeof member.property.value === "string")) &&
    MUTATING_METHODS.has(member.property.type === AST_NODE_TYPES.Identifier ? member.property.name : member.property.value)
  );
}

export default createRule<Options, MessageIds>({
  name: "prefer-immutable-module-constant",
  documentation: preferImmutableModuleConstantDocumentation,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Require module-level constant collections to expose readonly state.",
    },
    schema: [],
    messages: {
      preferAsConst:
        "Module constant `{{name}}` exposes a mutable literal. Add `as const` or a readonly surface to prevent ordinary mutation through the binding.",
      preferReadonlyCollection:
        "Module constant `{{name}}` is a mutable {{kind}}. Expose it as `Readonly{{kind}}` or an immutable collection.",
    },
  },
  defaultOptions: [],
  create(context) {
    const sourceCode = context.sourceCode;
    const isUnshadowedGlobal: GlobalResolver = (identifier) => {
      const variable = ASTUtils.findVariable(sourceCode.getScope(identifier), identifier.name);
      return variable === null || variable.defs.length === 0;
    };
    if (
      JAVASCRIPT_FILE_RE.test(context.filename) ||
      isTestFile(context.filename) ||
      isGeneratedFile(context.filename, sourceCode.getText())
    ) {
      return {};
    }
    const exportedNames = new Set<string>();
    const typeAliases = new Map<string, TSESTree.Node>();
    const mutatesThroughConstAlias = (root: Scope.Variable): boolean => {
      const pending = [root];
      const seen = new Set<Scope.Variable>();
      while (pending.length > 0) {
        const variable = pending.pop();
        if (variable === undefined || seen.has(variable)) continue;
        seen.add(variable);
        for (const reference of variable.references) {
          const identifier = reference.identifier;
          if (identifier.type !== AST_NODE_TYPES.Identifier) continue;
          if (referenceMutates(identifier, isUnshadowedGlobal)) return true;
          const declarator = identifier.parent;
          if (
            declarator.type !== AST_NODE_TYPES.VariableDeclarator ||
            declarator.init !== identifier ||
            declarator.id.type !== AST_NODE_TYPES.Identifier ||
            declarator.parent.type !== AST_NODE_TYPES.VariableDeclaration ||
            declarator.parent.kind !== "const"
          ) {
            continue;
          }
          const alias = sourceCode.getDeclaredVariables(declarator)[0];
          if (alias !== undefined) pending.push(alias);
        }
      }
      return false;
    };
    return {
      Program(node): void {
        for (const statement of node.body) {
          const declaration = statement.type === AST_NODE_TYPES.ExportNamedDeclaration ? statement.declaration : statement;
          if (declaration?.type === AST_NODE_TYPES.TSTypeAliasDeclaration) {
            typeAliases.set(declaration.id.name, declaration.typeAnnotation);
          }
          if (statement.type === AST_NODE_TYPES.ExportNamedDeclaration) {
            if (statement.source !== null || statement.exportKind === "type") continue;
            for (const specifier of statement.specifiers) {
              if (specifier.type === AST_NODE_TYPES.ExportSpecifier && specifier.exportKind !== "type" && specifier.local.type === AST_NODE_TYPES.Identifier) {
                exportedNames.add(specifier.local.name);
              }
            }
          } else if (
            statement.type === AST_NODE_TYPES.ExportDefaultDeclaration &&
            unwrapTransparentExport(statement.declaration)?.type === AST_NODE_TYPES.Identifier
          ) {
            exportedNames.add((unwrapTransparentExport(statement.declaration) as TSESTree.Identifier).name);
          }
        }
      },
      VariableDeclarator(node): void {
        const declaration = node.parent;
        if (
          declaration.type !== AST_NODE_TYPES.VariableDeclaration ||
          declaration.kind !== "const" ||
          node.id.type !== AST_NODE_TYPES.Identifier ||
          node.init === null
        ) {
          return;
        }
        const container = declaration.parent;
        if (
          container.type !== AST_NODE_TYPES.Program &&
          !(
            container.type === AST_NODE_TYPES.ExportNamedDeclaration &&
            container.parent.type === AST_NODE_TYPES.Program
          )
        ) {
          return;
        }
        const directlyExported = container.type === AST_NODE_TYPES.ExportNamedDeclaration;
        if (!CONSTANT_NAME.test(node.id.name) && !directlyExported && !exportedNames.has(node.id.name)) {
          return;
        }
        if (
          isAsConst(node.init, (target) => sourceCode.getText(target)) ||
          isObjectFreeze(node.init, isUnshadowedGlobal)
        ) {
          return;
        }
        const kind = collectionKind(node.init, isUnshadowedGlobal);
        if (kind === null || declaredReadonlyType(node, kind, typeAliases) || hasUnknownExplicitType(node, typeAliases)) {
          return;
        }
        const variable = sourceCode.getDeclaredVariables(node)[0];
        if (!directlyExported && !exportedNames.has(node.id.name) &&
          variable !== undefined && mutatesThroughConstAlias(variable)
        ) {
          return;
        }
        context.report({
          node: node.id,
          messageId: kind === "literal" ? "preferAsConst" : "preferReadonlyCollection",
          data: { name: node.id.name, kind },
        });
      },
    };
  },
});

function unwrapTransparentExport(node: TSESTree.Node): TSESTree.Node | null {
  if (node.type === AST_NODE_TYPES.TSSatisfiesExpression || node.type === AST_NODE_TYPES.TSNonNullExpression) {
    return unwrapTransparentExport(node.expression);
  }
  return node;
}
