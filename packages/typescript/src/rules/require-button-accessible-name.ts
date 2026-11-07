/**
 * @fileoverview require-button-accessible-name — statically proven UI policy violations receive actionable diagnostics.
 *
 * Port of the 18.x `require-button-accessible-name` rule. Untyped.
 */

import { defineRule, type ESTree } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import {
  attributeNameStatus,
  childrenNameStatus,
  COMPONENT_IMPORT_SCHEMA,
  type ComponentImport,
  hasHiddenAncestor,
  importedComponent,
  isHidden,
  isPassedAsProp,
} from "../utils/jsx-accessibility.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "../utils/paths.js";

const NAME = "require-button-accessible-name";
const DELEGATING_PROPS: ReadonlySet<string> = new Set(["render", "asChild"]);

/** The button renders through another element, which owns its name. */
function delegatesRendering(opening: ESTree.JSXOpeningElement): boolean {
  return opening.attributes.some(
    (attribute) =>
      attribute.type === "JSXAttribute" &&
      attribute.name.type === "JSXIdentifier" &&
      DELEGATING_PROPS.has(attribute.name.name),
  );
}

type Options = readonly [
  {
    readonly components?: readonly ComponentImport[];
    readonly iconModules?: readonly string[];
  }?,
];

export default defineRule({
  meta: {
    defaultOptions: [{}],
    type: "problem",
    docs: {
      description: "Require an accessible name on statically unnamed native or configured JSX buttons.",
      url: docsUrl(NAME),
    },
    schema: [
      {
        type: "object",
        properties: {
          components: COMPONENT_IMPORT_SCHEMA,
          iconModules: {
            description: "Module names whose imported components count as icons.",
            type: "array",
            items: { type: "string", minLength: 1 },
            uniqueItems: true,
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      missingName:
        "This button has no statically identifiable accessible name. Add action text, aria-label, or aria-labelledby.",
    },
  },
  createOnce(context) {
    let options: Options[0];
    let iconModules: readonly string[] = [];

    /** `Button`, or a configured component import. */
    function isButtonComponent(name: ESTree.JSXElementName): boolean {
      if (name.type === "JSXIdentifier" && name.name === "Button") return true;
      // Most files configure no components: skip the scope lookup for them.
      const components = options?.components ?? [];
      if (components.length === 0) return false;
      const imported = importedComponent(name, context.sourceCode);
      return imported !== null &&
        components.some((component) => component.module === imported.module && component.export === imported.export);
    }

    return {
      before() {
        const file = { filename: context.filename, cwd: context.cwd };
        if (isGeneratedFile(file, context.sourceCode.text) || isTestFile(file) || isStoryFile(file)) return false;
        options = context.options[0] as Options[0];
        iconModules = options?.iconModules ?? ["lucide-react"];
        return true;
      },
      JSXElement(node) {
        const sourceCode = context.sourceCode;
        const opening = node.openingElement;
        const native = opening.name.type === "JSXIdentifier" && opening.name.name === "button";
        if (!native && (!isButtonComponent(opening.name) || delegatesRendering(opening))) return;
        if (isPassedAsProp(node, sourceCode) || hasHiddenAncestor(node, sourceCode)) return;
        if (isHidden(opening, sourceCode) || attributeNameStatus(opening) !== "empty") return;
        if (childrenNameStatus(node.children, sourceCode, iconModules) !== "empty") return;
        context.report({ node: opening, messageId: "missingName" });
      },
    };
  },
});
