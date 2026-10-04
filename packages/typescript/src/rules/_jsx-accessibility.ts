/**
 * @fileoverview _jsx-accessibility — scope-aware JSX names and accessible content are shared across rules.
 */

import { nodeAncestors } from "./_scope.js";
import { decodeHTML } from "entities";
import type { ESTree, SourceCode } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


export interface ComponentImport {
  readonly module: string;
  readonly export: string;
}

export const COMPONENT_IMPORT_SCHEMA: NonNullable<import("@oxlint/plugins").RuleMeta["schema"]> = {
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
  name: ESTree.JSXElementName | ESTree.BindingIdentifier,
  source: SourceCode,
): ComponentImport | null {
  const local =
    name.type === "JSXIdentifier" ||
      name.type === "Identifier"
      ? name
      : name.type === "JSXMemberExpression" &&
        name.object.type === "JSXIdentifier"
        ? name.object
        : null;
  if (local === null) return null;
  const binding = findVariable(source.getScope(local), local.name);
  const definition = binding?.defs[0];
  if (
    definition?.type !== "ImportBinding" ||
    definition.parent?.type !== "ImportDeclaration" ||
    definition.parent.importKind === "type"
  )
    return null;
  const specifier = definition.node;
  if (
    specifier.type === "ImportSpecifier" &&
    (name.type === "JSXIdentifier" ||
      name.type === "Identifier") &&
    specifier.importKind !== "type"
  ) {
    return {
      module: definition.parent.source.value,
      export:
        specifier.imported.type === "Identifier"
          ? specifier.imported.name
          : specifier.imported.value,
    };
  }
  if (
    specifier.type === "ImportDefaultSpecifier" &&
    (name.type === "JSXIdentifier" ||
      name.type === "Identifier")
  ) {
    return { module: definition.parent.source.value, export: "default" };
  }
  if (
    specifier.type === "ImportNamespaceSpecifier" &&
    name.type === "JSXMemberExpression"
  ) {
    return {
      module: definition.parent.source.value,
      export: name.property.name,
    };
  }
  return null;
}

export function staticText(node: ESTree.Node): string | null {
  if (node.type === "Literal") {
    if (typeof node.value === "string" || typeof node.value === "number")
      return String(node.value);
    if (node.value === null || typeof node.value === "boolean") return "";
  }
  if (
    node.type === "TemplateLiteral" &&
    node.expressions.length === 0
  )
    return node.quasis[0]?.value.cooked ?? null;
  if (node.type === "JSXExpressionContainer")
    return staticText(node.expression);
  if (node.type === "JSXEmptyExpression") return "";
  return null;
}

export function attributeText(
  node: ESTree.JSXOpeningElement,
  name: string,
): string | null {
  const attribute = node.attributes.findLast(
    (entry) =>
      entry.type === "JSXSpreadAttribute" ||
      (entry.name.type === "JSXIdentifier" &&
        entry.name.name === name),
  );
  if (attribute === undefined) return "";
  if (attribute.type === "JSXSpreadAttribute") return null;
  if (
    attribute.value?.type === "JSXExpressionContainer" &&
    attribute.value.expression.type === "Literal" &&
    typeof attribute.value.expression.value === "boolean"
  ) {
    return String(attribute.value.expression.value);
  }
  return attribute.value === null ? "" : staticText(attribute.value);
}

export function isHidden(node: ESTree.JSXOpeningElement): boolean {
  if (attributeText(node, "aria-hidden") === "true") return true;
  const hidden = node.attributes.findLast(
    (attribute) =>
      attribute.type === "JSXSpreadAttribute" ||
      (attribute.name.type === "JSXIdentifier" &&
        attribute.name.name === "hidden"),
  );
  if (hidden?.type !== "JSXAttribute") return false;
  if (hidden.value === null) return true;
  if (
    hidden.value.type === "JSXExpressionContainer" &&
    hidden.value.expression.type === "Literal"
  )
    return (
      hidden.value.expression.value !== false &&
      hidden.value.expression.value !== null
    );
  return true;
}

export type NameStatus = "named" | "empty" | "unknown";

export function attributeNameStatus(
  node: ESTree.JSXOpeningElement,
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
  children: readonly ESTree.JSXChild[],
  source: SourceCode,
  iconModules: readonly string[],
): NameStatus {
  const states = children.map((child): NameStatus => {
    if (child.type === "JSXText")
      return decodeHTML(source.getText(child)).trim() === "" ? "empty" : "named";
    if (child.type === "JSXExpressionContainer") {
      const text = staticText(child);
      return textNameStatus(text);
    }
    if (child.type === "JSXFragment")
      return childrenNameStatus(child.children, source, iconModules);
    if (child.type !== "JSXElement") return "unknown";
    const opening = child.openingElement;
    if (isHidden(opening)) return "empty";
    const imported = importedComponent(opening.name, source);
    const intrinsic =
      opening.name.type === "JSXIdentifier" &&
      /^[a-z]/u.test(opening.name.name);
    if (
      !intrinsic &&
      (imported === null || !iconModules.includes(imported.module))
    )
      return "unknown";
    const named = attributeNameStatus(opening);
    if (named !== "empty") return named;
    if (
      opening.name.type === "JSXIdentifier" &&
      opening.name.name === "img"
    ) {
      const alt = attributeText(opening, "alt");
      return textNameStatus(alt);
    }
    return childrenNameStatus(child.children, source, iconModules);
  });
  if (states.includes("named")) return "named";
  return states.includes("unknown") ? "unknown" : "empty";
}

export function isPassedAsProp(
  node: ESTree.JSXElement,
  _source: SourceCode,
): boolean {
  for (const ancestor of nodeAncestors(node).toReversed()) {
    if (ancestor.type === "JSXAttribute") return true;
    if (
      ancestor.type === "JSXElement" ||
      ancestor.type === "JSXFragment"
    )
      return false;
  }
  return false;
}

export function hasHiddenAncestor(
  node: ESTree.JSXElement,
  _source: SourceCode,
): boolean {
  return nodeAncestors(node)
    .some(
      (ancestor) =>
        ancestor.type === "JSXElement" &&
        isHidden(ancestor.openingElement),
    );
}

function textNameStatus(text: string | null): NameStatus {
  if (text === null) return "unknown";
  return text.trim() === "" ? "empty" : "named";
}
