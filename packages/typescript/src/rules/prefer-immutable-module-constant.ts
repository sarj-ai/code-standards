/**
 * @fileoverview prefer-immutable-module-constant — module constants should expose readonly collection state.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-immutable-module-constant.test.ts
 */

import type { ESTree, Variable } from "@oxlint/plugins";
import { sourceOrigin } from "./_source-origin.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { findVariable } from "./_scope.js";
import {
  createTypeAliasEnvironment,
  hasVisibleTypeBinding,
  visibleTypeAlias,
} from "./_type-alias-resolution.js";

type MessageIds = "preferAsConst" | "preferReadonlyCollection";
type Options = readonly [];

export const PREFER_IMMUTABLE_MODULE_CONSTANT_DOCUMENTATION = {
  summary:
    "Require module-level constant collections to expose readonly state.",
  rationale:
    "A const binding prevents reassignment but does not stop callers from mutating its array, object, Set, or Map contents.",
  remediation:
    "Expose literals with `as const` or a readonly type, and expose Set or Map values through ReadonlySet or ReadonlyMap.",
  category: "correctness",
  limitations: [
    "Generated, test and JavaScript files are skipped. Private constants with observed direct or alias mutation are excluded; exported mutable collections remain advisory candidates. Reassigned aliases are conservatively followed, not flow-proven.",
    "Local type aliases are resolved before recognizing standard readonly types; imported or otherwise unknown type declarations are not inferred from their names. Readonly types have no runtime enforcement.",
  ],
  examples: [
    {
      id: "readonly-array-literal",
      title: "A module constant exposes a readonly literal",
      outcome: "no-match",
      files: [
        {
          path: "src/constants.ts",
          source: "const VALUES = [1, 2, 3] as const;",
        },
      ],
      focusPath: "src/constants.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "mutable-array-literal",
      title: "A module constant exposes a mutable array",
      outcome: "match",
      files: [
        { path: "src/constants.ts", source: "const VALUES = [1, 2, 3];" },
      ],
      focusPath: "src/constants.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "shadowed-readonly-alias",
      scenarioId: "type-binding",
      title: "A type named Readonly still exposes mutable properties",
      outcome: "match",
      files: [
        {
          path: "src/constants.ts",
          source:
            "type Readonly = { voice: boolean };\nexport const TOOL_SUPPORT: Readonly = { voice: true };",
        },
      ],
      focusPath: "src/constants.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "resolved-readonly-alias",
      scenarioId: "type-binding",
      title: "A local alias resolves to readonly properties",
      outcome: "no-match",
      files: [
        {
          path: "src/constants.ts",
          source:
            "type ToolSupport = Readonly<{ voice: boolean }>;\nexport const TOOL_SUPPORT: ToolSupport = { voice: true };",
        },
      ],
      focusPath: "src/constants.ts",
      expectedCount: 0,
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

function isAsConst(
  node: ESTree.Node,
  sourceText: (node: ESTree.Node) => string,
): boolean {
  if (
    node.type === "TSSatisfiesExpression" ||
    node.type === "TSNonNullExpression"
  ) {
    return isAsConst(node.expression, sourceText);
  }
  if (node.type !== "TSAsExpression") return false;
  return sourceText(node.typeAnnotation).trim() === "const";
}

/** Strip type-only wrappers without treating a mutable assertion as readonly. */
function unwrapExpression(node: ESTree.Node): ESTree.Node {
  if (
    node.type === "TSAsExpression" ||
    node.type === "TSSatisfiesExpression" ||
    node.type === "TSNonNullExpression"
  ) {
    return unwrapExpression(node.expression);
  }
  return node;
}

type GlobalResolver = (
  identifier: Extract<ESTree.Node, { type: "Identifier" }>,
) => boolean;
type LocalType = ESTree.TSTypeAliasDeclaration | ESTree.TSTypeParameter;
type LocalTypeResolver = (
  identifier: Extract<ESTree.Node, { type: "Identifier" }>,
) => LocalType | undefined;
type TypeArguments = ReadonlyMap<ESTree.TSTypeParameter, TypeArgument>;
type ReadonlyState = "readonly" | "mutable" | "unknown";
type TypeArgument = {
  readonly node: ESTree.Node;
  readonly arguments: TypeArguments;
  readonly seen: ReadonlySet<ESTree.Node>;
};

function isObjectFreeze(
  node: ESTree.Node,
  isUnshadowedGlobal: GlobalResolver,
): boolean {
  const inner = unwrapExpression(node);
  if (
    inner.type === "CallExpression" &&
    inner.callee.type === "MemberExpression" &&
    !inner.callee.computed &&
    inner.callee.object.type === "Identifier" &&
    inner.callee.object.name === "Object" &&
    isUnshadowedGlobal(inner.callee.object) &&
    inner.callee.property.type === "Identifier" &&
    inner.callee.property.name === "freeze" &&
    inner.arguments.length === 1
  ) {
    const argument = inner.arguments[0];
    return (
      argument !== undefined &&
      argument.type !== "SpreadElement" &&
      collectionKind(argument, isUnshadowedGlobal) === "literal"
    );
  }
  return false;
}

function collectionKind(
  node: ESTree.Node,
  isUnshadowedGlobal: GlobalResolver,
): "literal" | "Set" | "Map" | null {
  const inner = unwrapExpression(node);
  if (
    inner.type === "CallExpression" &&
    inner.callee.type === "MemberExpression" &&
    !inner.callee.computed &&
    inner.callee.object.type === "Identifier" &&
    inner.callee.object.name === "Object" &&
    isUnshadowedGlobal(inner.callee.object) &&
    inner.callee.property.type === "Identifier" &&
    inner.callee.property.name === "freeze" &&
    inner.arguments.length === 1 &&
    inner.arguments[0] !== undefined &&
    inner.arguments[0].type !== "SpreadElement"
  ) {
    return collectionKind(inner.arguments[0], isUnshadowedGlobal);
  }
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
  const annotation =
    node.id.type === "Identifier" ? node.id.typeAnnotation : undefined;
  if (
    annotation != null &&
    readonlyTypeState(
      annotation.typeAnnotation,
      kind,
      resolveLocalType,
      isUnshadowedType,
    ) === "readonly"
  ) {
    return true;
  }
  return (
    node.init?.type === "TSAsExpression" &&
    readonlyTypeState(
      node.init.typeAnnotation,
      kind,
      resolveLocalType,
      isUnshadowedType,
    ) === "readonly"
  );
}

function readonlyTypeState(
  node: ESTree.Node,
  kind: "literal" | "Set" | "Map",
  resolveLocalType: LocalTypeResolver,
  isUnshadowedType: GlobalResolver,
  arguments_: TypeArguments = new Map(),
  seen: ReadonlySet<ESTree.Node> = new Set(),
): ReadonlyState {
  if (seen.has(node)) return "unknown";
  if (node.type !== "TSTypeReference" || node.typeName.type !== "Identifier") {
    return directReadonlyState(node, kind, isUnshadowedType);
  }
  const declaration = resolveLocalType(node.typeName);
  if (declaration === undefined)
    return directReadonlyState(node, kind, isUnshadowedType);
  if (declaration.type === "TSTypeParameter") {
    const argument = arguments_.get(declaration);
    return argument === undefined
      ? "unknown"
      : readonlyTypeState(
          argument.node,
          kind,
          resolveLocalType,
          isUnshadowedType,
          argument.arguments,
          argument.seen,
        );
  }
  const expanded = new Set([...seen, node]);
  return readonlyTypeState(
    declaration.typeAnnotation,
    kind,
    resolveLocalType,
    isUnshadowedType,
    bindTypeArguments(declaration, node, arguments_, expanded),
    expanded,
  );
}

function bindTypeArguments(
  declaration: ESTree.TSTypeAliasDeclaration,
  reference: ESTree.TSTypeReference,
  arguments_: TypeArguments,
  seen: ReadonlySet<ESTree.Node>,
): TypeArguments {
  const bindings = new Map(arguments_);
  for (const [index, parameter] of (
    declaration.typeParameters?.params ?? []
  ).entries()) {
    const argument = reference.typeArguments?.params[index];
    const node = argument ?? parameter.default;
    if (node != null) {
      bindings.set(parameter, {
        node,
        arguments: argument === undefined ? new Map(bindings) : arguments_,
        seen,
      });
    }
  }
  return bindings;
}

function directReadonlyState(
  node: ESTree.Node,
  kind: "literal" | "Set" | "Map",
  isUnshadowedType: GlobalResolver,
): ReadonlyState {
  if (node.type === "TSTypeOperator" && node.operator === "readonly") {
    return "readonly";
  }
  if (node.type === "TSTypeLiteral") {
    if (node.members.length === 0) return "unknown";
    const readonly =
      kind === "literal" &&
      node.members.length > 0 &&
      node.members.every(
        (member) =>
          (member.type === "TSPropertySignature" ||
            member.type === "TSIndexSignature") &&
          member.readonly,
      );
    return readonly ? "readonly" : "mutable";
  }
  if (node.type === "TSArrayType" || node.type === "TSTupleType")
    return "mutable";
  if (
    node.type !== "TSTypeReference" ||
    node.typeName.type !== "Identifier" ||
    !isUnshadowedType(node.typeName)
  ) {
    return "unknown";
  }
  if (node.typeName.name === "Readonly") {
    return kind === "literal" ? "readonly" : "mutable";
  }
  if (["Array", "Map", "Set"].includes(node.typeName.name)) return "mutable";
  if (
    !["ReadonlyArray", "ReadonlyMap", "ReadonlySet"].includes(
      node.typeName.name,
    )
  )
    return "unknown";
  const readonly =
    kind === "literal"
      ? node.typeName.name === "ReadonlyArray"
      : node.typeName.name === `Readonly${kind}`;
  return readonly ? "readonly" : "mutable";
}

function hasUnknownExplicitType(
  node: ESTree.VariableDeclarator,
  kind: "literal" | "Set" | "Map",
  resolveLocalType: LocalTypeResolver,
  isUnshadowedType: GlobalResolver,
): boolean {
  const annotation =
    (node.id.type === "Identifier"
      ? node.id.typeAnnotation?.typeAnnotation
      : undefined) ??
    (node.init?.type === "TSAsExpression"
      ? node.init.typeAnnotation
      : undefined);
  if (annotation == null) return false;
  if (annotation.type === "TSArrayType" || annotation.type === "TSTypeOperator")
    return false;
  if (
    annotation.type !== "TSTypeReference" ||
    annotation.typeName.type !== "Identifier"
  )
    return true;
  if (resolveLocalType(annotation.typeName) !== undefined) {
    return (
      readonlyTypeState(
        annotation,
        kind,
        resolveLocalType,
        isUnshadowedType,
      ) === "unknown"
    );
  }
  return (
    resolveLocalType(annotation.typeName) === undefined &&
    (!isUnshadowedType(annotation.typeName) ||
      ![
        "Array",
        "Map",
        "Readonly",
        "ReadonlyArray",
        "ReadonlyMap",
        "ReadonlySet",
        "Set",
      ].includes(annotation.typeName.name))
  );
}

function referenceMutates(
  identifier: Extract<ESTree.Node, { type: "Identifier" }>,
  isUnshadowedGlobal: GlobalResolver,
): boolean {
  let member = identifier.parent;
  if (member?.type !== "MemberExpression" || member.object !== identifier) {
    return (
      member?.type === "CallExpression" &&
      member.arguments[0] === identifier &&
      member.callee.type === "MemberExpression" &&
      !member.callee.computed &&
      member.callee.object.type === "Identifier" &&
      member.callee.object.name === "Object" &&
      isUnshadowedGlobal(member.callee.object) &&
      member.callee.property.type === "Identifier" &&
      member.callee.property.name === "assign"
    );
  }
  while (
    member.parent.type === "MemberExpression" &&
    member.parent.object === member
  ) {
    member = member.parent;
  }
  const parent = member.parent;
  if (parent?.type === "AssignmentExpression" && parent.left === member) {
    return true;
  }
  if (parent?.type === "UpdateExpression" && parent.argument === member) {
    return true;
  }
  if (
    parent?.type === "UnaryExpression" &&
    parent.operator === "delete" &&
    parent.argument === member
  ) {
    return true;
  }
  return (
    parent?.type === "CallExpression" &&
    parent.callee === member &&
    ((member.property.type === "Identifier" && !member.computed) ||
      (member.property.type === "Literal" &&
        typeof member.property.value === "string")) &&
    MUTATING_METHODS.has(
      member.property.type === "Identifier"
        ? member.property.name
        : member.property.value,
    )
  );
}

export default createRule<Options, MessageIds>({
  name: "prefer-immutable-module-constant",
  documentation: PREFER_IMMUTABLE_MODULE_CONSTANT_DOCUMENTATION,
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
    const origin = sourceOrigin(context);
    const sourceCode = context.sourceCode;
    const isUnshadowedGlobal: GlobalResolver = (identifier) => {
      const variable = findVariable(
        sourceCode.getScope(identifier),
        identifier.name,
      );
      return variable === null || variable.defs.length === 0;
    };
    const types = createTypeAliasEnvironment(
      sourceCode.ast,
      sourceCode.visitorKeys,
    );
    const isUnshadowedType: GlobalResolver = (identifier) =>
      !hasVisibleTypeBinding(identifier.name, identifier, types);
    const resolveLocalType: LocalTypeResolver = (identifier) => {
      for (
        let ancestor: ESTree.Node | null = identifier;
        ancestor !== null;
        ancestor = ancestor.parent
      ) {
        if (!("typeParameters" in ancestor)) continue;
        const parameter = ancestor.typeParameters?.params.find(
          (parameter) => parameter.name.name === identifier.name,
        );
        if (parameter !== undefined) return parameter;
      }
      return visibleTypeAlias(identifier.name, identifier, types) ?? undefined;
    };
    if (
      JAVASCRIPT_FILE_RE.test(origin.filename) ||
      isTestFile(origin.filename) ||
      isGeneratedFile(origin.filename, origin.text)
    ) {
      return {};
    }
    const exportedNames = new Set<string>();
    const mutatesThroughAlias = (root: Variable): boolean => {
      const pending = [root];
      const seen = new Set<Variable>();
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
          const alias = sourceCode.getDeclaredVariables(declarator)[0];
          if (alias !== undefined) pending.push(alias);
        }
      }
      return false;
    };
    return {
      Program(node): void {
        function collectModuleBindings(statement: ESTree.Statement): void {
          if (statement.type === "ExportNamedDeclaration") {
            if (statement.source !== null || statement.exportKind === "type")
              return;
            for (const specifier of statement.specifiers) {
              if (
                specifier.type === "ExportSpecifier" &&
                specifier.exportKind !== "type" &&
                specifier.local.type === "Identifier"
              ) {
                exportedNames.add(specifier.local.name);
              }
            }
          } else if (
            statement.type === "ExportDefaultDeclaration" &&
            unwrapTransparentExport(statement.declaration)?.type ===
              "Identifier"
          ) {
            exportedNames.add(
              (
                unwrapTransparentExport(statement.declaration) as Extract<
                  ESTree.Node,
                  { type: "Identifier" }
                >
              ).name,
            );
          }
        }

        for (const statement of node.body) {
          collectModuleBindings(statement);
        }
      },
      VariableDeclarator(node): void {
        const declaration = node.parent;
        if (
          declaration.type !== "VariableDeclaration" ||
          declaration.kind !== "const" ||
          node.id.type !== "Identifier" ||
          node.init === null
        ) {
          return;
        }
        const container = declaration.parent;
        if (
          container.type !== "Program" &&
          !(
            container.type === "ExportNamedDeclaration" &&
            container.parent.type === "Program"
          )
        ) {
          return;
        }
        const directlyExported = container.type === "ExportNamedDeclaration";
        if (
          !CONSTANT_NAME.test(node.id.name) &&
          !directlyExported &&
          !exportedNames.has(node.id.name)
        ) {
          return;
        }
        if (
          isAsConst(node.init, (target) => sourceCode.getText(target)) ||
          isObjectFreeze(node.init, isUnshadowedGlobal)
        ) {
          return;
        }
        const kind = collectionKind(node.init, isUnshadowedGlobal);
        if (
          kind === null ||
          declaredReadonlyType(
            node,
            kind,
            resolveLocalType,
            isUnshadowedType,
          ) ||
          hasUnknownExplicitType(node, kind, resolveLocalType, isUnshadowedType)
        ) {
          return;
        }
        const variable = sourceCode.getDeclaredVariables(node)[0];
        if (
          !directlyExported &&
          !exportedNames.has(node.id.name) &&
          variable !== undefined &&
          mutatesThroughAlias(variable)
        ) {
          return;
        }
        context.report({
          node: node.id,
          messageId:
            kind === "literal" ? "preferAsConst" : "preferReadonlyCollection",
          data: { name: node.id.name, kind },
        });
      },
    };
  },
});

function unwrapTransparentExport(node: ESTree.Node): ESTree.Node | null {
  if (
    node.type === "TSSatisfiesExpression" ||
    node.type === "TSNonNullExpression"
  ) {
    return unwrapTransparentExport(node.expression);
  }
  return node;
}
