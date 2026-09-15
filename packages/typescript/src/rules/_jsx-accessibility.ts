/**
 * @fileoverview _jsx-accessibility — scope-aware JSX names and accessible content are shared across rules.
 */

import {
  AST_NODE_TYPES,
  ASTUtils,
  type JSONSchema,
  type TSESLint,
  type TSESTree,
} from "@typescript-eslint/utils";

export interface ComponentImport {
  readonly module: string;
  readonly export: string;
}

export const COMPONENT_IMPORT_SCHEMA: Readonly<JSONSchema.JSONSchema4> = {
  type: "array",
  items: {
    type: "object",
    properties: {
      module: { type: "string", minLength: 1 },
      export: { type: "string", minLength: 1 },
    },
    required: ["module", "export"],
    additionalProperties: false,
  },
};

export function importedComponent(
  name: TSESTree.JSXTagNameExpression | TSESTree.Identifier,
  source: TSESLint.SourceCode,
): ComponentImport | null {
  const local =
    name.type === AST_NODE_TYPES.JSXIdentifier ||
    name.type === AST_NODE_TYPES.Identifier
      ? name
      : name.type === AST_NODE_TYPES.JSXMemberExpression &&
          name.object.type === AST_NODE_TYPES.JSXIdentifier
        ? name.object
        : null;
  if (local === null) return null;
  const binding = ASTUtils.findVariable(source.getScope(local), local.name);
  const definition = binding?.defs[0];
  if (
    definition?.type !== "ImportBinding" ||
    definition.parent.type !== AST_NODE_TYPES.ImportDeclaration ||
    definition.parent.importKind === "type"
  )
    return null;
  const specifier = definition.node;
  if (
    specifier.type === AST_NODE_TYPES.ImportSpecifier &&
    (name.type === AST_NODE_TYPES.JSXIdentifier ||
      name.type === AST_NODE_TYPES.Identifier) &&
    specifier.importKind !== "type"
  ) {
    return {
      module: definition.parent.source.value,
      export:
        specifier.imported.type === AST_NODE_TYPES.Identifier
          ? specifier.imported.name
          : specifier.imported.value,
    };
  }
  if (
    specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier &&
    (name.type === AST_NODE_TYPES.JSXIdentifier ||
      name.type === AST_NODE_TYPES.Identifier)
  ) {
    return { module: definition.parent.source.value, export: "default" };
  }
  if (
    specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier &&
    name.type === AST_NODE_TYPES.JSXMemberExpression
  ) {
    return {
      module: definition.parent.source.value,
      export: name.property.name,
    };
  }
  return null;
}

export function staticText(node: TSESTree.Node): string | null {
  if (node.type === AST_NODE_TYPES.Literal) {
    if (typeof node.value === "string" || typeof node.value === "number")
      return String(node.value);
    if (node.value === null || typeof node.value === "boolean") return "";
  }
  if (
    node.type === AST_NODE_TYPES.TemplateLiteral &&
    node.expressions.length === 0
  )
    return node.quasis[0]?.value.cooked ?? null;
  if (node.type === AST_NODE_TYPES.JSXExpressionContainer)
    return staticText(node.expression);
  if (node.type === AST_NODE_TYPES.JSXEmptyExpression) return "";
  return null;
}

export function attributeText(
  node: TSESTree.JSXOpeningElement,
  name: string,
): string | null {
  const attribute = node.attributes.findLast(
    (entry) =>
      entry.type === AST_NODE_TYPES.JSXSpreadAttribute ||
      (entry.name.type === AST_NODE_TYPES.JSXIdentifier &&
        entry.name.name === name),
  );
  if (attribute === undefined) return "";
  if (attribute.type === AST_NODE_TYPES.JSXSpreadAttribute) return null;
  if (
    attribute.value?.type === AST_NODE_TYPES.JSXExpressionContainer &&
    attribute.value.expression.type === AST_NODE_TYPES.Literal &&
    typeof attribute.value.expression.value === "boolean"
  ) {
    return String(attribute.value.expression.value);
  }
  return attribute.value === null ? "" : staticText(attribute.value);
}

export function isHidden(node: TSESTree.JSXOpeningElement): boolean {
  if (attributeText(node, "aria-hidden") === "true") return true;
  const hidden = node.attributes.findLast(
    (attribute) =>
      attribute.type === AST_NODE_TYPES.JSXSpreadAttribute ||
      (attribute.name.type === AST_NODE_TYPES.JSXIdentifier &&
        attribute.name.name === "hidden"),
  );
  if (hidden?.type !== AST_NODE_TYPES.JSXAttribute) return false;
  if (hidden.value === null) return true;
  if (
    hidden.value.type === AST_NODE_TYPES.JSXExpressionContainer &&
    hidden.value.expression.type === AST_NODE_TYPES.Literal
  )
    return (
      hidden.value.expression.value !== false &&
      hidden.value.expression.value !== null
    );
  return true;
}

export type NameStatus = "named" | "empty" | "unknown";

export function attributeNameStatus(
  node: TSESTree.JSXOpeningElement,
  attributes: readonly string[] = [
    "aria-label",
    "aria-labelledby",
    "title",
    "children",
  ],
): NameStatus {
  let status: NameStatus = "empty";
  for (const name of attributes) {
    const value = attributeText(node, name);
    if (value === null) status = "unknown";
    else if (value.trim() !== "") return "named";
  }
  return status;
}

export function childrenNameStatus(
  children: readonly TSESTree.JSXChild[],
  source: TSESLint.SourceCode,
  iconModules: readonly string[],
): NameStatus {
  const states = children.map((child): NameStatus => {
    if (child.type === AST_NODE_TYPES.JSXText)
      return child.value.trim() === "" ? "empty" : "named";
    if (child.type === AST_NODE_TYPES.JSXExpressionContainer) {
      const text = staticText(child);
      return text === null ? "unknown" : text.trim() === "" ? "empty" : "named";
    }
    if (child.type === AST_NODE_TYPES.JSXFragment)
      return childrenNameStatus(child.children, source, iconModules);
    if (child.type !== AST_NODE_TYPES.JSXElement) return "unknown";
    const opening = child.openingElement;
    if (isHidden(opening)) return "empty";
    const imported = importedComponent(opening.name, source);
    const intrinsic =
      opening.name.type === AST_NODE_TYPES.JSXIdentifier &&
      /^[a-z]/u.test(opening.name.name);
    if (
      !intrinsic &&
      (imported === null || !iconModules.includes(imported.module))
    )
      return "unknown";
    const named = attributeNameStatus(opening);
    if (named !== "empty") return named;
    if (
      opening.name.type === AST_NODE_TYPES.JSXIdentifier &&
      opening.name.name === "img"
    ) {
      const alt = attributeText(opening, "alt");
      return alt === null ? "unknown" : alt.trim() === "" ? "empty" : "named";
    }
    return childrenNameStatus(child.children, source, iconModules);
  });
  if (states.includes("named")) return "named";
  return states.includes("unknown") ? "unknown" : "empty";
}

export function isPassedAsProp(
  node: TSESTree.JSXElement,
  source: TSESLint.SourceCode,
): boolean {
  for (const ancestor of source.getAncestors(node).toReversed()) {
    if (ancestor.type === AST_NODE_TYPES.JSXAttribute) return true;
    if (
      ancestor.type === AST_NODE_TYPES.JSXElement ||
      ancestor.type === AST_NODE_TYPES.JSXFragment
    )
      return false;
  }
  return false;
}

export function hasHiddenAncestor(
  node: TSESTree.JSXElement,
  source: TSESLint.SourceCode,
): boolean {
  return source
    .getAncestors(node)
    .some(
      (ancestor) =>
        ancestor.type === AST_NODE_TYPES.JSXElement &&
        isHidden(ancestor.openingElement),
    );
}
