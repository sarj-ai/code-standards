/** @fileoverview require-ime-safe-enter-handler — preserve composing text before native control actions. */
import { defineRule, type ESTree, type Node } from "../types.js";
import { forEachOwnAstChild, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { effectiveAttribute, isEditableTextControl } from "./_web-jsx.js";

const NAME = "require-ime-safe-enter-handler";
type MatchesEvent = (identifier: Extract<Node, { type: "Identifier" }>) => boolean;

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Preserve IME composition before Enter submits or blurs a native text control.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      composition:
        "Enter also confirms IME composition. Guard composition before submitting the form or blurring this control; retain the required Safari fallback for your supported browsers.",
    },
  },
  createOnce(context) {
    return {
      before(): boolean | void {
        if (
          isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)
        )
          return false;
      },
      JSXOpeningElement(node: ESTree.JSXOpeningElement): void {
        if (!isEditableTextControl(node, context.sourceCode)) return;
        if (effectiveAttribute(node, ["onCompositionStart", "onCompositionEnd"]) !== undefined)
          return;
        const attribute = effectiveAttribute(node, ["onKeyDown"]);
        if (
          attribute?.type !== "JSXAttribute" ||
          attribute.value?.type !== "JSXExpressionContainer"
        )
          return;
        const callback = unwrapExpression(attribute.value.expression);
        if (callback.type !== "ArrowFunctionExpression" && callback.type !== "FunctionExpression")
          return;
        const [event] = callback.params;
        if (event?.type !== "Identifier" || callback.body === null) return;
        const binding = findVariable(context.sourceCode.getScope(callback.body), event.name);
        if (binding === null || binding.references.some((reference) => reference.isWrite())) return;
        const matches: MatchesEvent = (identifier) =>
          findVariable(context.sourceCode.getScope(identifier), identifier.name) === binding;
        if (contains(callback.body, (part) => isGuard(part, matches))) return;
        if (
          contains(
            callback.body,
            (part) =>
              part.type === "IfStatement" &&
              positiveEnterGate(part.test, matches) &&
              contains(part.consequent, (action) => nativeAction(action, matches)),
          )
        ) {
          context.report({ node: attribute, messageId: "composition" });
        }
      },
    };
  },
});

function contains(node: Node, predicate: (node: Node) => boolean): boolean {
  if (["FunctionExpression", "ArrowFunctionExpression", "FunctionDeclaration"].includes(node.type))
    return false;
  return predicate(node) || forEachOwnAstChild(node, (child) => contains(child, predicate));
}

function eventMember(node: Node, event: MatchesEvent, property: string): boolean {
  const value = unwrapExpression(node);
  return (
    value.type === "MemberExpression" &&
    getPropertyName(value) === property &&
    value.object.type === "Identifier" &&
    event(value.object)
  );
}

function isGuard(node: Node, event: MatchesEvent): boolean {
  if (node.type !== "MemberExpression") return false;
  const property = getPropertyName(node);
  if (!["isComposing", "keyCode", "ctrlKey", "metaKey"].includes(property ?? "")) return false;
  return (
    (node.object.type === "Identifier" && event(node.object)) ||
    eventMember(node.object, event, "nativeEvent")
  );
}

function positiveEnterGate(node: Node, event: MatchesEvent): boolean {
  const test = unwrapExpression(node);
  if (isEnter(test, event)) return true;
  if (test.type !== "LogicalExpression" || test.operator !== "&&") return false;
  const unshifted = (part: Node): boolean =>
    part.type === "UnaryExpression" &&
    part.operator === "!" &&
    eventMember(part.argument, event, "shiftKey");
  return (
    (isEnter(test.left, event) && unshifted(test.right)) ||
    (isEnter(test.right, event) && unshifted(test.left))
  );
}

function isEnter(node: Node, event: MatchesEvent): boolean {
  if (node.type !== "BinaryExpression" || !["===", "=="].includes(node.operator)) return false;
  return (
    (eventMember(node.left, event, "key") &&
      node.right.type === "Literal" &&
      node.right.value === "Enter") ||
    (eventMember(node.right, event, "key") &&
      node.left.type === "Literal" &&
      node.left.value === "Enter")
  );
}

function nativeAction(node: Node, event: MatchesEvent): boolean {
  if (node.type !== "CallExpression") return false;
  const callee = unwrapExpression(node.callee);
  if (callee.type !== "MemberExpression") return false;
  const property = getPropertyName(callee);
  if (property === "blur") return eventMember(callee.object, event, "currentTarget");
  const form = unwrapExpression(callee.object);
  return (
    property === "requestSubmit" &&
    form.type === "MemberExpression" &&
    getPropertyName(form) === "form" &&
    eventMember(form.object, event, "currentTarget")
  );
}
