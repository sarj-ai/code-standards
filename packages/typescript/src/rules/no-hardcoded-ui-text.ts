/**
 * @fileoverview Flag hardcoded user-facing text in JSX so it goes through the
 * i18n layer instead — the product ships bilingual (ar/en), and every literal
 * that bypasses `t()` is a string one language never sees.
 *
 * Three narrow detectors (high-FP-risk rule, so scope is deliberately tight):
 *   (a) JSXText containing two or more consecutive words of Latin or Arabic
 *       letters — prose between tags is almost always copy.
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

type MessageIds = "hardcodedJsxText" | "hardcodedAttribute" | "arabicLiteral";
type Options = readonly [
  {
    i18nCallees?: readonly string[];
  }?,
];

const IGNORED_FILE_RE =
  /(\.(test|spec)\.[jt]sx?$)|([\\/]__tests__[\\/])|(\.stories\.)/;

const JSX_FILE_RE = /\.[jt]sx$/;

/** Two or more consecutive words of Latin or Arabic letters. */
const TWO_WORDS_RE =
  /[\p{Script=Latin}\p{Script=Arabic}][\p{Script=Latin}\p{Script=Arabic}'’-]*\s+[\p{Script=Latin}\p{Script=Arabic}]/u;

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
    if (IGNORED_FILE_RE.test(context.filename)) {
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
        if (TWO_WORDS_RE.test(node.value)) {
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
