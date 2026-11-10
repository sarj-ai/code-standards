/** @fileoverview no-password-get-form — native GET submissions expose named passwords in URLs. */
import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { forEachOwnAstChild } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { attributeString, effectiveAttribute, mayHaveBooleanAttribute } from "./_web-jsx.js";

const NAME = "no-password-get-form";

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Keep named password controls out of native GET form submissions.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      passwordGet:
        "This native GET form can put a named password in the URL. Review the endpoint contract and submit credentials with POST.",
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
      JSXElement(node: ESTree.JSXElement): void {
        const opening = node.openingElement;
        if (opening.name.type !== "JSXIdentifier" || opening.name.name !== "form") return;
        const method = attributeString(opening, context.sourceCode, ["method"])?.toLowerCase();
        if (method === undefined || method === "post" || method === "dialog") return;
        if (
          attributeString(opening, context.sourceCode, ["action"]) === null ||
          effectiveAttribute(opening, ["onSubmit", "onSubmitCapture"]) !== undefined
        )
          return;
        if (!hasSubmissionOverride(node) && containsPassword(node.children, context.sourceCode))
          context.report({ node: opening, messageId: "passwordGet" });
      },
    };
  },
});

function containsPassword(children: readonly ESTree.JSXChild[], source: SourceCode): boolean {
  for (const child of children) {
    if (child.type === "JSXFragment") {
      if (containsPassword(child.children, source)) return true;
      continue;
    }
    if (child.type !== "JSXElement" || child.openingElement.name.type !== "JSXIdentifier") continue;
    const opening = child.openingElement;
    const tag = opening.name.type === "JSXIdentifier" ? opening.name.name : "";
    if (
      !/^[a-z]/u.test(tag) ||
      tag === "form" ||
      (tag === "fieldset" && mayHaveBooleanAttribute(opening, ["disabled"]))
    )
      continue;
    if (tag === "input" && isSubmittedPassword(opening, source)) return true;
    if (containsPassword(child.children, source)) return true;
  }
  return false;
}

function isSubmittedPassword(opening: ESTree.JSXOpeningElement, source: SourceCode): boolean {
  const name = attributeString(opening, source, ["name"]);
  return (
    attributeString(opening, source, ["type"])?.toLowerCase() === "password" &&
    name !== null &&
    name !== "" &&
    !mayHaveBooleanAttribute(opening, ["disabled"]) &&
    effectiveAttribute(opening, ["form"]) === undefined
  );
}

function hasSubmissionOverride(node: Node): boolean {
  if (
    node.type === "JSXOpeningElement" &&
    node.name.type === "JSXIdentifier" &&
    ["button", "input"].includes(node.name.name) &&
    effectiveAttribute(node, ["formMethod", "formmethod", "formAction", "formaction"]) !== undefined
  )
    return true;
  return forEachOwnAstChild(node, hasSubmissionOverride);
}
