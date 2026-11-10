/** @fileoverview no-invalid-web-resource-hints — conflicting native loading hints waste critical fetches. */
import { defineRule, type ESTree } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";
import { attributeString, effectiveAttribute } from "./_web-jsx.js";

const NAME = "no-invalid-web-resource-hints";
const RESOURCE_TAGS: ReadonlySet<string> = new Set(["img", "iframe", "link", "script"]);
const LAZY_TAGS: ReadonlySet<string> = new Set(["img", "iframe", "video", "audio"]);

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Keep native resource hints consistent with browser loading and preload request modes.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      criticalLazy:
        "This image is marked high priority and lazy-loaded. Review whether it is critical and load it eagerly, or keep lazy loading and remove the priority boost.",
      obsoleteImportance:
        "The importance attribute is obsolete. Review whether fetchPriority is needed for this resource.",
      invalidLoading:
        'loading="auto" is unsupported. Omit loading for the default eager behavior, or select lazy loading deliberately.',
      preloadAs:
        "A preload needs its resource destination in as so the browser can reuse it for the matching request.",
      fontCors:
        'Font preloads need anonymous CORS, including same-origin fonts. Set crossOrigin="anonymous" so the preload matches the font request.',
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
        if (node.name.type !== "JSXIdentifier") return;
        const tag = node.name.name;
        const text = (names: readonly string[]): string | null =>
          attributeString(node, context.sourceCode, names);
        const importance = text(["importance"]);
        if (RESOURCE_TAGS.has(tag) && importance !== null && importance !== "")
          context.report({ node, messageId: "obsoleteImportance" });
        const loading = text(["loading"])?.toLowerCase();
        if (LAZY_TAGS.has(tag) && loading === "auto")
          context.report({ node, messageId: "invalidLoading" });
        if (
          tag === "img" &&
          loading === "lazy" &&
          text(["fetchPriority", "fetchpriority"])?.toLowerCase() === "high"
        ) {
          context.report({ node, messageId: "criticalLazy" });
        }
        if (tag !== "link" || !text(["rel"])?.toLowerCase().split(/\s+/u).includes("preload"))
          return;
        const destination = text(["as"])?.toLowerCase();
        if (destination === "") context.report({ node, messageId: "preloadAs" });
        if (destination !== "font") return;
        const cors = effectiveAttribute(node, ["crossOrigin", "crossorigin"]);
        if (
          cors === undefined ||
          text(["crossOrigin", "crossorigin"])?.toLowerCase() === "use-credentials"
        ) {
          context.report({ node, messageId: "fontCors" });
        }
      },
    };
  },
});
