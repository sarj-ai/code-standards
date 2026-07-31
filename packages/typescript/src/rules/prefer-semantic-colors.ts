/**
 * @fileoverview prefer-semantic-colors — a raw palette class or hex literal pins a colour the design system can no longer retheme.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-semantic-colors.test.ts
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/prefer-semantic-colors.md
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";
import { existsSync, readFileSync } from "fs";
import { dirname, join, parse } from "path";

import { createRule } from "./_docs.js";
import { classTokens, tailwindBase } from "./_tailwind.js";

type MessageIds = "rawPalette" | "arbitraryColor" | "inlineColor";
type Options = readonly [
  {
    requireSemanticTokens?: boolean;
  }?,
];

const COLOR_PREFIXES =
  "text|bg|border(?:-[trblxyse])?|ring(?:-offset)?|fill|stroke|from|via|to|divide|decoration|placeholder|accent|caret|shadow|outline";
const PALETTE =
  "red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone";
const COLOR_FN = "rgba?|hsla?|hwb|oklch|oklab|lab|lch|color";

const PALETTE_STEP = "50|[1-9]00|950";
const RAW_PALETTE_RE = new RegExp(`^(?:${COLOR_PREFIXES})-(?:${PALETTE})-(?:${PALETTE_STEP})(?:/\\d{1,3})?$`);
const ARBITRARY_COLOR_RE = new RegExp(
  `^(?:${COLOR_PREFIXES})-\\[(?:#[0-9a-fA-F]{3,8}|(?:${COLOR_FN})\\([^\\]]*\\))\\]$`,
  "i",
);

/** Call expressions whose string args are className fragments. */
const CLASS_FNS = new Set<string>(["cn", "clsx", "cva", "tv", "cx", "twMerge", "classnames", "classNames"]);
const CLASS_NAME_RE = /class/i;

/** CSS color-bearing properties, in their JSX (camelCase) and SVG-attribute forms. */
const STYLE_COLOR_PROPS = new Set<string>([
  "color",
  "background",
  "backgroundColor",
  "borderColor",
  "borderTopColor",
  "borderRightColor",
  "borderBottomColor",
  "borderLeftColor",
  "outlineColor",
  "caretColor",
  "textDecorationColor",
  "columnRuleColor",
  "fill",
  "stroke",
  "stopColor",
  "floodColor",
  "lightingColor",
]);
const RAW_COLOR_VALUE_RE = new RegExp(`#[0-9a-fA-F]{3,8}\\b|\\b(?:${COLOR_FN})\\s*\\(`, "i");

const CSS_VAR_REFERENCE_RE = /var\(\s*--/;

const STORIES_FILE_RE = /\.stories\.[cm]?[jt]sx?$/i;

/**
 * A design-token vocabulary, in a stylesheet.
 *
 * shadcn's names plus Tailwind v4's `@theme` block, which is how a v4 project
 * declares tokens now that there is no `tailwind.config.*` to declare them in.
 * Only stylesheets are content-tested at all (see `CONFIG_IS_SUFFICIENT`), so
 * the vocabulary list no longer decides whether a whole repo is linted.
 */
const SEMANTIC_TOKEN_RE = /@theme\b|--(?:background|foreground|primary|secondary|muted|accent|destructive|border|card|popover)\b|(?:bg|text|border)-(?:background|foreground|primary|secondary|muted|accent|destructive|border|card|popover)\b/;

/**
 * Files whose mere EXISTENCE proves a design system, with no content test.
 *
 * A `tailwind.config.*` is a token vocabulary by construction — the whole point
 * of the file is to name colors — and the vocabulary it declares is the
 * project's own, not shadcn's. Content-testing it cost whole repositories:
 * `medusa/packages/admin/dashboard/tailwind.config.cjs` exists, sits 5
 * directories above the components that fail the rule, is already in this list,
 * and was REJECTED because Medusa names its tokens `bg-ui-button-neutral` /
 * `text-ui-fg-subtle` rather than shadcn's `bg-primary`, which silenced that
 * whole repository under the shipped `requireSemanticTokens: true`. The content
 * test was answering "does this project use shadcn?" while the option is
 * documented to ask "does this project have design tokens?".
 */
const CONFIG_IS_SUFFICIENT = new Set([
  "components.json",
  "tailwind.config.cjs",
  "tailwind.config.js",
  "tailwind.config.mjs",
  "tailwind.config.ts",
]);

const DETECTION_FILES = [
  "components.json",
  "tailwind.config.js",
  "tailwind.config.cjs",
  "tailwind.config.mjs",
  "tailwind.config.ts",
  "app/globals.css",
  "src/app/globals.css",
  "src/index.css",
  "src/styles/globals.css",
  "styles/globals.css",
];
/** How far up the tree to look for a design-token marker before giving up. */
const MAX_UPWARD_DEPTH = 8;

const semanticTokenCache = new Map<string, boolean>();

/** SVG container elements whose children carry structural (not UI-token) colors. */
const SVG_DEFS_CONTAINERS = new Set<string>([
  "mask",
  "clipPath",
  "defs",
  "pattern",
  "linearGradient",
  "radialGradient",
]);

/** Neutral fill/stroke literals that are SVG drawing data, never a UI token. */
const SVG_EXEMPT_COLOR_VALUES = new Set<string>([
  "#fff",
  "#ffffff",
  "#000",
  "#000000",
  "transparent",
  "none",
  "currentcolor",
  "inherit",
]);

// A `fill`/`stroke` literal anywhere inside an `<svg>` subtree is drawing data
// (icon/illustration artwork), not a reusable UI token — the color is inherent to
// the graphic. Exempt any descendant of `<svg>` (which subsumes the defs
// containers `<mask>`/`<clipPath>`/`<defs>`/`<pattern>`/gradients).
function jsxElementName(node: TSESTree.JSXElement): string | null {
  const name = node.openingElement.name;
  if (name.type === AST_NODE_TYPES.JSXIdentifier) return name.name;
  if (name.type === AST_NODE_TYPES.JSXMemberExpression && name.property.type === AST_NODE_TYPES.JSXIdentifier) {
    return name.property.name;
  }
  return null;
}

function isSvgLikeElementName(name: string): boolean {
  return name === "svg" || SVG_DEFS_CONTAINERS.has(name) || /svg$/i.test(name);
}

/**
 * Intrinsic lowercase SVG shape primitives.
 *
 * A `fill`/`stroke` on a lowercase `<path>` is never a reusable-UI-token
 * position — real component styling goes through `className` or `style`, which
 * this guard does not touch — so the recall cost is zero.
 */
const SVG_SHAPE_PRIMITIVES = new Set<string>([
  "circle",
  "ellipse",
  "g",
  "line",
  "path",
  "polygon",
  "polyline",
  "rect",
  "stop",
  "text",
  "tspan",
  "use",
]);

/**
 * Files rendered by react-email or react-pdf.
 *
 * CSS-variable-backed semantic tokens cannot work in either target. `<Tailwind>`
 * from `@react-email/components` compiles classes to inline styles at render
 * time, and `hsl(var(--primary))` is undefined in a mail client; react-pdf has
 * no CSS custom properties at all. Raw palette classes and literal hex are the
 * correct practice there, so the rule's advice is unfollowable.
 */
const EMAIL_OR_PDF_IMPORT_RE = /@react-(?:email|pdf)\//;

const isInsideSvg = (node: TSESTree.Node): boolean => {
  let current: TSESTree.Node | null | undefined = node.parent;
  while (current !== undefined && current !== null) {
    if (current.type === AST_NODE_TYPES.JSXElement) {
      const name = jsxElementName(current);
      if (name !== null && isSvgLikeElementName(name)) return true;
    }
    current = current.parent;
  }
  return false;
};

const isInsideIconFactoryPath = (node: TSESTree.Node): boolean => {
  let current: TSESTree.Node | null | undefined = node.parent;
  while (current !== undefined && current !== null) {
    if (
      current.type === AST_NODE_TYPES.Property &&
      propName(current.key) === "path" &&
      current.parent.type === AST_NODE_TYPES.ObjectExpression &&
      current.parent.parent.type === AST_NODE_TYPES.CallExpression &&
      current.parent.parent.callee.type === AST_NODE_TYPES.Identifier &&
      current.parent.parent.callee.name === "createIcon"
    ) {
      return true;
    }
    current = current.parent;
  }
  return false;
};

/**
 * Does a design-token system exist at or above `filename`'s directory?
 *
 * The cache stores the RESOLVED answer for every directory visited on the way
 * up, not each directory's own local result. That distinction is the entire bug
 * this replaced: the previous version wrote `cache[dir] = found` per
 * intermediate directory, where `found` meant "no marker AT this dir" — but the
 * question being cached is "is there a marker at or ABOVE this dir". So the
 * first file linted wrote `cache["…/src"] = false`, and every later file under
 * `src/**` short-circuited on it and never walked up to the `components.json`
 * at the repo root.
 *
 * Caching the resolved answer for all visited directories is sound: every
 * visited directory sits at or below the one where the marker was found, so the
 * marker is at-or-above each of them too.
 */
const hasSemanticTokenSystem = (filename: string): boolean => {
  let dir = dirname(filename);
  const root = parse(dir).root;
  const visited: string[] = [];
  let answer: boolean | undefined;

  for (let depth = 0; depth < MAX_UPWARD_DEPTH; depth += 1) {
    const cached = semanticTokenCache.get(dir);
    if (cached !== undefined) {
      answer = cached;
      break;
    }
    visited.push(dir);

    let found = false;
    for (const rel of DETECTION_FILES) {
      const candidate = join(dir, rel);
      if (!existsSync(candidate)) continue;
      if (CONFIG_IS_SUFFICIENT.has(rel)) {
        found = true;
        break;
      }
      try {
        if (SEMANTIC_TOKEN_RE.test(readFileSync(candidate, "utf8"))) {
          found = true;
          break;
        }
      } catch {
        // Ignore unreadable config files; absence of evidence means no report.
      }
    }
    if (found) {
      answer = true;
      break;
    }
    if (dir === root) {
      answer = false;
      break;
    }
    dir = dirname(dir);
  }

  // `answer` is undefined only when the depth budget ran out before reaching a
  // marker or the filesystem root. That is inconclusive, not "no" — a directory
  // higher up could still hold one, reachable within budget from a shallower
  // file. Memoizing it would make the wrong answer permanent for the process,
  // so those directories are deliberately left uncached.
  if (answer === undefined) return false;
  for (const seen of visited) semanticTokenCache.set(seen, answer);
  return answer;
};

const propName = (key: TSESTree.Property["key"]): string | null => {
  if (key.type === AST_NODE_TYPES.Identifier) return key.name;
  if (key.type === AST_NODE_TYPES.Literal && typeof key.value === "string") return key.value;
  return null;
};

export default createRule<Options, MessageIds>({
  name: "prefer-semantic-colors",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Enforce design-system semantic color tokens (bg-primary, text-destructive, …) over raw Tailwind palette classes (text-red-500), arbitrary color values (bg-[#fff]), and inline color literals.",
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          requireSemanticTokens: { type: "boolean" },
        },
      },
    ],
    messages: {
      rawPalette:
        "Raw palette class '{{class}}' — use a semantic token (e.g. text-foreground, bg-primary, text-destructive, bg-muted).",
      arbitraryColor:
        "Hardcoded color '{{class}}' — use a semantic token, or var(--…). For charts/brand add an eslint-disable with a reason.",
      inlineColor:
        "Hardcoded color '{{value}}' — use a semantic token / CSS variable. For charts/standalone pages add an eslint-disable with a reason.",
    },
  },
  defaultOptions: [{}],
  create(context, [options]) {
    if (STORIES_FILE_RE.test(context.filename)) return {};
    if (EMAIL_OR_PDF_IMPORT_RE.test(context.sourceCode.getText())) return {};
    if (options?.requireSemanticTokens === true && !hasSemanticTokenSystem(context.filename)) {
      return {};
    }

    const reportClasses = (value: string, node: TSESTree.Node): void => {
      for (const token of classTokens(value)) {
        const base = tailwindBase(token);
        if (RAW_PALETTE_RE.test(base)) {
          context.report({ node, messageId: "rawPalette", data: { class: token } });
        } else if (ARBITRARY_COLOR_RE.test(base) && !CSS_VAR_REFERENCE_RE.test(base)) {
          context.report({ node, messageId: "arbitraryColor", data: { class: token } });
        }
      }
    };

    // Walk a node that holds className fragments: strings, templates, arrays, cva
    // variant objects, and conditionals. CallExpressions are handled separately, so
    // they're not recursed here (avoids double-reporting cn()/cva() args).
    const checkClassNode = (node: TSESTree.Node | null): void => {
      if (node === null) return;
      switch (node.type) {
        case AST_NODE_TYPES.Literal:
          if (typeof node.value === "string") reportClasses(node.value, node);
          break;
        case AST_NODE_TYPES.TemplateLiteral:
          for (const quasi of node.quasis) reportClasses(quasi.value.cooked ?? "", quasi);
          break;
        case AST_NODE_TYPES.ArrayExpression:
          for (const element of node.elements) {
            if (element !== null && element.type !== AST_NODE_TYPES.SpreadElement) checkClassNode(element);
          }
          break;
        case AST_NODE_TYPES.ObjectExpression:
          for (const property of node.properties) {
            if (property.type === AST_NODE_TYPES.Property) checkClassNode(property.value);
          }
          break;
        case AST_NODE_TYPES.ConditionalExpression:
          checkClassNode(node.consequent);
          checkClassNode(node.alternate);
          break;
        case AST_NODE_TYPES.LogicalExpression:
          checkClassNode(node.right);
          break;
        default:
          break;
      }
    };

    const checkColorValueNode = (node: TSESTree.Node): void => {
      if (
        node.type === AST_NODE_TYPES.Literal &&
        typeof node.value === "string" &&
        RAW_COLOR_VALUE_RE.test(node.value) &&
        !CSS_VAR_REFERENCE_RE.test(node.value)
      ) {
        context.report({ node, messageId: "inlineColor", data: { value: node.value } });
      }
    };

    return {
      "JSXAttribute[name.name='className']"(node: TSESTree.JSXAttribute): void {
        if (node.value === null) return;
        if (node.value.type === AST_NODE_TYPES.Literal) checkClassNode(node.value);
        else if (node.value.type === AST_NODE_TYPES.JSXExpressionContainer) {
          if (node.value.expression.type !== AST_NODE_TYPES.JSXEmptyExpression) {
            checkClassNode(node.value.expression);
          }
        }
      },
      CallExpression(node: TSESTree.CallExpression): void {
        if (node.callee.type === AST_NODE_TYPES.Identifier && CLASS_FNS.has(node.callee.name)) {
          for (const arg of node.arguments) {
            if (arg.type !== AST_NODE_TYPES.SpreadElement) checkClassNode(arg);
          }
        }
      },
      VariableDeclarator(node: TSESTree.VariableDeclarator): void {
        if (node.id.type === AST_NODE_TYPES.Identifier && CLASS_NAME_RE.test(node.id.name)) {
          checkClassNode(node.init);
        }
      },
      Property(node: TSESTree.Property): void {
        const name = propName(node.key);
        if (name !== null && CLASS_NAME_RE.test(name)) checkClassNode(node.value);
      },
      // SVG presentation attributes: <path fill="#7c3aed" stroke="#7c3aed" />.
      // Neutral drawing literals and anything inside an SVG defs container are
      // structural, not UI tokens, so they never fire.
      "JSXAttribute[name.name=/^(fill|stroke|color)$/]"(node: TSESTree.JSXAttribute): void {
        if (node.value?.type !== AST_NODE_TYPES.Literal) return;
        const owner = node.parent.name;
        if (owner.type === AST_NODE_TYPES.JSXIdentifier && SVG_SHAPE_PRIMITIVES.has(owner.name)) {
          return;
        }
        if (
          typeof node.value.value === "string" &&
          SVG_EXEMPT_COLOR_VALUES.has(node.value.value.toLowerCase())
        ) {
          return;
        }
        if (isInsideSvg(node) || isInsideIconFactoryPath(node)) return;
        checkColorValueNode(node.value);
      },
      "JSXAttribute[name.name='style'] ObjectExpression > Property"(node: TSESTree.Property): void {
        const name = propName(node.key);
        if (name !== null && STYLE_COLOR_PROPS.has(name)) checkColorValueNode(node.value);
      },
    };
  },
});
