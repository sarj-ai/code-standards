/**
 * @fileoverview require-svg-accessible-name — inline SVGs need a name or explicit decorative semantics.
 *
 * Port of the 18.x `require-svg-accessible-name` rule. The rule is
 * untyped, so the port covers all of it.
 */

import { defineRule } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import {
  attributeNameStatus,
  attributeText,
  childrenNameStatus,
  hasHiddenAncestor,
  isHidden,
  isPassedAsProp,
} from "../utils/jsx-accessibility.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "../utils/paths.js";

const NAME = "require-svg-accessible-name";
const DECORATIVE_ROLES: ReadonlySet<string> = new Set(["none", "presentation"]);
const NAME_ATTRIBUTES: readonly string[] = ["aria-label", "aria-labelledby"];
const NO_ICON_MODULES: readonly string[] = [];

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Require a name or explicit decorative semantics on inline SVG elements.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      missingName:
        "Give this SVG an accessible name or explicitly mark it decorative with aria-hidden or a presentational role.",
    },
  },
  createOnce(context) {
    return {
      before() {
        const file = { filename: context.filename, cwd: context.cwd };
        if (
          isGeneratedFile(file, context.sourceCode.text) ||
          isTestFile(file) ||
          isStoryFile(file)
        ) return false;
        return undefined;
      },
      JSXElement(node) {
        const opening = node.openingElement;
        if (opening.name.type !== "JSXIdentifier" || opening.name.name !== "svg") return;
        const sourceCode = context.sourceCode;
        if (isPassedAsProp(node, sourceCode) || hasHiddenAncestor(node, sourceCode)) return;
        if (
          isHidden(opening, sourceCode) ||
          DECORATIVE_ROLES.has(attributeText(opening, "role") ?? "")
        ) return;
        if (attributeNameStatus(opening, NAME_ATTRIBUTES) !== "empty") return;
        const namedTitle = node.children.some(
          (child) =>
            child.type === "JSXElement" &&
            child.openingElement.name.type === "JSXIdentifier" &&
            child.openingElement.name.name === "title" &&
            childrenNameStatus(child.children, sourceCode, NO_ICON_MODULES) !== "empty",
        );
        if (namedTitle) return;
        context.report({ node: opening, messageId: "missingName" });
      },
    };
  },
});
