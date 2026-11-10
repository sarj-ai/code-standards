/** @fileoverview web-jsx — effective intrinsic JSX attributes, including spread uncertainty. */
import type { ESTree, SourceCode } from "../types.js";
import { scopedStaticString } from "../utils/static-string.js";

const TEXT_INPUTS: ReadonlySet<string> = new Set([
  "",
  "text",
  "password",
  "email",
  "search",
  "tel",
  "url",
  "number",
]);

export function isEditableTextControl(node: ESTree.JSXOpeningElement, source: SourceCode): boolean {
  if (node.name.type !== "JSXIdentifier" || !["input", "textarea"].includes(node.name.name))
    return false;
  if (
    mayHaveBooleanAttribute(node, ["disabled"]) ||
    mayHaveBooleanAttribute(node, ["readOnly", "readonly"])
  )
    return false;
  if (node.name.name === "textarea") return true;
  const type = attributeString(node, source, ["type"])?.toLowerCase();
  return type !== undefined && TEXT_INPUTS.has(type);
}

export function effectiveAttribute(
  node: ESTree.JSXOpeningElement,
  names: readonly string[],
): ESTree.JSXAttribute | ESTree.JSXSpreadAttribute | undefined {
  return node.attributes.findLast(
    (attribute) =>
      attribute.type === "JSXSpreadAttribute" ||
      (attribute.name.type === "JSXIdentifier" && names.includes(attribute.name.name)),
  );
}

export function attributeString(
  node: ESTree.JSXOpeningElement,
  source: SourceCode,
  names: readonly string[],
): string | null {
  const attribute = effectiveAttribute(node, names);
  if (attribute === undefined) return "";
  if (attribute.type === "JSXSpreadAttribute") return null;
  if (attribute.value === null) return "";
  const value =
    attribute.value.type === "JSXExpressionContainer"
      ? attribute.value.expression
      : attribute.value;
  return scopedStaticString(value, source);
}

export function mayHaveBooleanAttribute(
  node: ESTree.JSXOpeningElement,
  names: readonly string[],
): boolean {
  const attribute = effectiveAttribute(node, names);
  if (attribute === undefined) return false;
  if (attribute.type === "JSXAttribute" && attribute.value?.type === "JSXExpressionContainer") {
    const value = attribute.value.expression;
    if (value.type === "Literal" && (value.value === false || value.value === null)) return false;
  }
  return true;
}
