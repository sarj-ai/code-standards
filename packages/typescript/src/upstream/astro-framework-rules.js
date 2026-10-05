// Maintained Astro 3.2.1 rule algorithms, applied to genuine native JSX and source facts.
// Original MIT attribution: packages/typescript/vendor/astro/LICENSE.
import { getStaticValue, getPropertyName } from "../../vendor/eslint-utils/index.mjs";
import { iterateCSSVars } from "../../vendor/astro/css-variables.mjs";
import { astroElement, sourceOrigin, authoredRange } from "../rules/_source-origin.js";

function nameOf(node) {
  if (node.type === "JSXIdentifier") return node.name;
  return node.type === "JSXNamespacedName" ? `${nameOf(node.namespace)}:${nameOf(node.name)}` : null;
}

function metadata(messages) {
  return { type: "problem", schema: [], messages };
}

export const astroFrameworkRules = {
  "missing-client-only-directive-value": {
    meta: metadata({ missing: "`client:only` directive is missing a value" }),
    create(context) {
      if (!sourceOrigin(context).filename.endsWith(".astro")) return {};
      return {
        JSXAttribute(attribute) {
          if (nameOf(attribute.name) !== "client:only") return;
          const value = attribute.value?.type === "JSXExpressionContainer"
            ? attribute.value.expression : attribute.value;
          if (!value || !getStaticValue(value, context.sourceCode.getScope(value))) {
            context.report({ node: attribute, messageId: "missing" });
          }
        },
      };
    },
  },
  "no-conflict-set-directives": {
    meta: metadata({ conflict: "{{name}} conflicts with {{targets}}." }),
    create(context) {
      if (!sourceOrigin(context).filename.endsWith(".astro")) return {};
      return {
        JSXElement(node) {
          const opening = node.openingElement;
          const facts = astroElement(context, opening.range);
          if (!facts) return;
          const conflicts = opening.attributes
            .filter((attribute) => attribute.type === "JSXAttribute" &&
              ["set:text", "set:html"].includes(nameOf(attribute.name)))
            .map((attribute) => ({ node: attribute, name: `'${nameOf(attribute.name)}'` }));
          if (!conflicts.length) return;
          const child = facts.children.find((candidate) => candidate.type !== "comment" &&
            (candidate.type !== "text" || candidate.value.trim()));
          if (child) {
            const nativeChild = node.children.find((candidate) => {
              const original = authoredRange(context, candidate.range);
              return original && original.start <= child.start && original.end >= child.end;
            });
            conflicts.push({ node: nativeChild ?? (child.omittedExpression ? opening : node), name: "child contents" });
          }
          if (conflicts.length < 2) return;
          for (const conflict of conflicts) {
            const others = conflicts.filter((candidate) => candidate !== conflict).map((candidate) => candidate.name);
            const targets = [others.slice(0, -1).join(", "), others.at(-1)].filter(Boolean).join(", and ");
            context.report({ node: conflict.node, messageId: "conflict", data: { name: conflict.name, targets } });
          }
        },
      };
    },
  },
  "no-unused-define-vars-in-style": {
    meta: metadata({ unused: "'{{name}}' is defined but never used." }),
    create(context) {
      if (!sourceOrigin(context).filename.endsWith(".astro")) return {};
      return {
        JSXAttribute(attribute) {
          if (nameOf(attribute.name) !== "define:vars" || nameOf(attribute.parent.name) !== "style") return;
          const facts = astroElement(context, attribute.parent.range);
          if (!facts || facts.children.length !== 1 || facts.children[0].type !== "text") return;
          const object = attribute.value?.type === "JSXExpressionContainer" ? attribute.value.expression : null;
          if (object?.type !== "ObjectExpression") return;
          const language = facts.attributes.find((candidate) => candidate.name === "lang" && candidate.kind === "quoted")?.value;
          const used = new Set(Array.from(iterateCSSVars(facts.children[0].value, {
            inlineComment: Boolean(language) && language !== "css",
          }), (value) => value.slice(2)));
          for (const property of object.properties) {
            if (property.type !== "Property") continue;
            const name = getPropertyName(property, context.sourceCode.getScope(property));
            if (name && !used.has(name)) context.report({ node: attribute, messageId: "unused", data: { name } });
          }
        },
      };
    },
  },
};
