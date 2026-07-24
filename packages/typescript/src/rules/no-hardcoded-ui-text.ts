/**
 * @fileoverview Flag hardcoded user-facing text in JSX so it goes through the
 * i18n layer instead — the product ships bilingual (ar/en), and every literal
 * that bypasses `t()` is a string one language never sees.
 *
 * ADOPTION PARKED (2026-07 audit): no target repo has an i18n framework yet,
 * so every finding is unactionable — there is no `t()` to move the copy
 * behind (2,566 corpus hits, 60-75% of them internal tooling that may never
 * localize). The rule ships in the registry but is wired into NO config tier;
 * turning it on is gated on an i18n framework decision.
 *
 * Three narrow detectors (high-FP-risk rule, so scope is deliberately tight):
 *   (a) JSXText containing two or more consecutive words (Latin or Arabic
 *       letters, digits allowed after the first word: "Page 1 of 3") — prose
 *       between tags is almost always copy. JSXText inside `<code>`, `<pre>`,
 *       or `<kbd>` is exempt: those elements display literal text.
 *   (b) Any string literal containing an Arabic codepoint in a .tsx/.jsx
 *       file — Arabic in source is user-facing copy by definition.
 *   (c) String literals of two or more words passed to the copy-carrying JSX
 *       attributes title/label/placeholder/alt/description/aria-label.
 *
 * Skips: test files and *.stories.* files entirely; className/class/id/key/
 * htmlFor/data-* attribute values; and literals already inside a configured
 * i18n call (`i18nCallees` option, default `["t", "i18n.t"]`).
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isTestFile } from "./_paths.js";

type MessageIds = "hardcodedJsxText" | "hardcodedAttribute" | "arabicLiteral";
type Options = readonly [
  {
    i18nCallees?: readonly string[];
  }?,
];

const STORIES_FILE_RE = /\.stories\./;

const JSX_FILE_RE = /\.[jt]sx$/;

/** Two or more consecutive words of Latin or Arabic letters; digits may
 * appear after the first word ("Total 5 Users", "Page 1 of 3"). */
const TWO_WORDS_RE =
  /[\p{Script=Latin}\p{Script=Arabic}][\p{Script=Latin}\p{Script=Arabic}\p{N}'’-]*\s+[\p{Script=Latin}\p{Script=Arabic}\p{N}]/u;

/** Elements whose text content is literal by design, not copy. */
const LITERAL_TEXT_ELEMENTS: ReadonlySet<string> = new Set([
  "code",
  "pre",
  "kbd",
]);

const ARABIC_RE = /\p{Script=Arabic}/u;

/** Attributes that carry user-visible copy. */
const TEXT_ATTRIBUTES: ReadonlySet<string> = new Set([
  "title",
  "label",
  "placeholder",
  "alt",
  "description",
  "aria-label",
]);

/** Attributes whose string values are never copy (identifiers, class lists). */
function isNonCopyAttribute(name: string): boolean {
  return (
    name === "className" ||
    name === "class" ||
    name === "id" ||
    name === "key" ||
    name === "htmlFor" ||
    name.startsWith("data-")
  );
}

/** Dotted-path text of a call's callee (`t`, `i18n.t`, ...) or null. */
function calleeText(node: TSESTree.Expression): string | null {
  if (node.type === AST_NODE_TYPES.Identifier) {
    return node.name;
  }
  if (
    node.type === AST_NODE_TYPES.MemberExpression &&
    !node.computed &&
    node.property.type === AST_NODE_TYPES.Identifier
  ) {
    const objectText = calleeText(node.object as TSESTree.Expression);
    return objectText === null ? null : `${objectText}.${node.property.name}`;
  }
  return null;
}

/** The JSXAttribute this literal is the (possibly `{}`-wrapped) value of, or null. */
function enclosingAttribute(node: TSESTree.Node): TSESTree.JSXAttribute | null {
  const parent = node.parent;
  if (parent?.type === AST_NODE_TYPES.JSXAttribute) {
    return parent;
  }
  if (
    parent?.type === AST_NODE_TYPES.JSXExpressionContainer &&
    parent.parent.type === AST_NODE_TYPES.JSXAttribute
  ) {
    return parent.parent;
  }
  return null;
}

function attributeName(attr: TSESTree.JSXAttribute): string {
  return attr.name.type === AST_NODE_TYPES.JSXIdentifier
    ? attr.name.name
    : `${attr.name.namespace.name}:${attr.name.name.name}`;
}

/** True when the JSXText sits inside a `<code>` / `<pre>` / `<kbd>` element. */
function isInsideLiteralTextElement(node: TSESTree.JSXText): boolean {
  for (
    let current: TSESTree.Node | null | undefined = node.parent;
    current?.type === AST_NODE_TYPES.JSXElement ||
    current?.type === AST_NODE_TYPES.JSXFragment;
    current = current.parent
  ) {
    if (
      current.type === AST_NODE_TYPES.JSXElement &&
      current.openingElement.name.type === AST_NODE_TYPES.JSXIdentifier &&
      LITERAL_TEXT_ELEMENTS.has(current.openingElement.name.name)
    ) {
      return true;
    }
  }
  return false;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-hardcoded-ui-text",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow hardcoded user-facing text in JSX; route copy through the i18n layer (e.g. `t('key')`) so ar/en both render.",
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          i18nCallees: {
            type: "array",
            items: { type: "string" },
          },
        },
      },
    ],
    messages: {
      hardcodedJsxText:
        "Hardcoded UI text in JSX — one of ar/en will never see this string. Move it behind the i18n layer (e.g. `{t('key')}`).",
      hardcodedAttribute:
        "Hardcoded copy in the `{{attribute}}` attribute — move it behind the i18n layer (e.g. `{{attribute}}={t('key')}`).",
      arabicLiteral:
        "Hardcoded Arabic string — user-facing copy belongs in the i18n layer (e.g. `t('key')`), not in source.",
    },
  },
  defaultOptions: [{}],
  create(context, [optionsArg]) {
    if (isTestFile(context.filename) || STORIES_FILE_RE.test(context.filename)) {
      return {};
    }
    const i18nCallees = new Set(optionsArg?.i18nCallees ?? ["t", "i18n.t"]);
    const isJsxFile = JSX_FILE_RE.test(context.filename);

    function isInsideI18nCall(node: TSESTree.Node): boolean {
      // ESLint sets `parent` to null on Program, so check both nullish forms.
      for (
        let current: TSESTree.Node | null | undefined = node.parent;
        current !== undefined && current !== null;
        current = current.parent
      ) {
        if (current.type === AST_NODE_TYPES.CallExpression) {
          const text = calleeText(current.callee);
          if (text !== null && i18nCallees.has(text)) {
            return true;
          }
        }
      }
      return false;
    }

    return {
      JSXText(node: TSESTree.JSXText): void {
        if (TWO_WORDS_RE.test(node.value) && !isInsideLiteralTextElement(node)) {
          context.report({ node, messageId: "hardcodedJsxText" });
        }
      },

      Literal(node: TSESTree.Literal): void {
        if (typeof node.value !== "string") {
          return;
        }
        // Literals in type positions, imports, and directives are never copy.
        const parent = node.parent;
        if (
          parent.type === AST_NODE_TYPES.TSLiteralType ||
          parent.type === AST_NODE_TYPES.ImportDeclaration ||
          parent.type === AST_NODE_TYPES.ExportNamedDeclaration ||
          parent.type === AST_NODE_TYPES.ExportAllDeclaration ||
          (parent.type === AST_NODE_TYPES.ExpressionStatement &&
            parent.directive !== undefined)
        ) {
          return;
        }

        const attr = enclosingAttribute(node);
        const attrName = attr === null ? null : attributeName(attr);
        if (attrName !== null && isNonCopyAttribute(attrName)) {
          return;
        }
        if (isInsideI18nCall(node)) {
          return;
        }

        if (
          attrName !== null &&
          TEXT_ATTRIBUTES.has(attrName) &&
          TWO_WORDS_RE.test(node.value)
        ) {
          context.report({
            node,
            messageId: "hardcodedAttribute",
            data: { attribute: attrName },
          });
          return;
        }

        if (isJsxFile && ARABIC_RE.test(node.value)) {
          context.report({ node, messageId: "arabicLiteral" });
        }
      },
    };
  },
});
