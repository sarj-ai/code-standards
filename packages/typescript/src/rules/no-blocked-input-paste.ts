/** @fileoverview no-blocked-input-paste — distinguish pure paste blocking from clipboard processing. */
import { defineRule, type ESTree, type Node } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { getPropertyName } from "../utils/static-string.js";
import { effectiveAttribute, isEditableTextControl } from "./_web-jsx.js";

const NAME = "no-blocked-input-paste";

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Allow clipboard input when a text control has no replacement paste handling.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      blockedPaste:
        "This handler only cancels pasting into an editable text control. Allow clipboard and password-manager input, or provide explicit replacement paste handling.",
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
        const blocker = blockingAttribute(node);
        if (blocker !== null) context.report({ node: blocker, messageId: "blockedPaste" });
      },
    };
  },
});

function blockingAttribute(node: ESTree.JSXOpeningElement): ESTree.JSXAttribute | null {
  let blocker: ESTree.JSXAttribute | null = null;
  for (const name of ["onPaste", "onPasteCapture"]) {
    const attribute = effectiveAttribute(node, [name]);
    if (attribute === undefined) continue;
    if (
      attribute.type !== "JSXAttribute" ||
      attribute.value?.type !== "JSXExpressionContainer" ||
      !onlyCancelsPaste(attribute.value.expression)
    )
      return null;
    blocker ??= attribute;
  }
  return blocker;
}

function onlyCancelsPaste(expression: Node): boolean {
  const callback = unwrapExpression(expression);
  if (callback.type !== "ArrowFunctionExpression" && callback.type !== "FunctionExpression")
    return false;
  if (callback.body === null) return false;
  const [event] = callback.params;
  if (event?.type !== "Identifier") return false;
  let body: Node = callback.body;
  if (body.type === "BlockStatement") {
    if (body.body.length !== 1) return false;
    const statement = body.body[0];
    if (statement?.type === "ExpressionStatement") body = statement.expression;
    else if (statement?.type === "ReturnStatement" && statement.argument !== null)
      body = statement.argument;
    else return false;
  }
  body = unwrapExpression(body);
  if (body.type !== "CallExpression" || body.optional || body.arguments.length !== 0) return false;
  const callee = unwrapExpression(body.callee);
  return (
    callee.type === "MemberExpression" &&
    !callee.optional &&
    getPropertyName(callee) === "preventDefault" &&
    callee.object.type === "Identifier" &&
    callee.object.name === event.name
  );
}
