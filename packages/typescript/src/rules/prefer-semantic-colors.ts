/**
 * @fileoverview Enforce design-system semantic color tokens over raw Tailwind
 * palette classes and hardcoded color values.
 *
 * Scoped to genuine className positions to avoid false positives on non-class
 * strings (Tailwind `safelist`, `toHaveClass(...)` test assertions, prose, color
 * maps): JSX `className`, the args of `cn()`/`clsx()`/`cva()`/`tv()`/`cx()`/
 * `twMerge()` (recursing into cva variant objects), and `*class*`-named
 * variables/object properties. Plus inline color literals on JSX `style`/`fill`/
 * `stroke`.
 *
 * Flags:
 *   - raw palette classes: `text-red-500`, `bg-slate-200/50`
 *   - arbitrary color values: `bg-[#fff]`, `text-[rgb(...)]`, `ring-[oklch(...)]`
 *   - inline color literals: `style={{ color: "#111827" }}`, `fill="#000"`
 *
 * Allowed: semantic tokens (`bg-primary`, `text-muted-foreground`, `bg-chart-1`),
 * `white`/`black` (the `bg-black/50` overlay idiom rarely has a token), `var(--…)`,
 * `currentColor`, and non-color arbitraries (`w-[437px]`, `grid-cols-[auto_1fr]`).
 *
 * SVG drawing data is exempt on `fill`/`stroke`/`color` attributes: any value inside
 * a `<mask>`/`<clipPath>`/`<defs>`/`<pattern>`/`<linearGradient>`/`<radialGradient>`
 * (masking breaks without literal `#fff`/`#000`), the neutral literals
 * (`#fff`/`#000`/`transparent`/`none`/`currentColor`/`inherit`), and `*.stories.*`
 * files (Storybook fixtures) never fire. Real component styling — `className` and
 * inline `style={{ … }}` objects — still fires on hardcoded colors.
 *
 * No autofix — use a semantic token, or for charts / standalone pages / 3rd-party
 * config add `// eslint-disable-next-line @sarj/prefer-semantic-colors -- <reason>`.
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";
import { existsSync, readFileSync } from "fs";
import { dirname, join, parse } from "path";

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

const RAW_PALETTE_RE = new RegExp(`^(?:${COLOR_PREFIXES})-(?:${PALETTE})-\\d{2,3}(?:/\\d{1,3})?$`);
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

const STORIES_FILE_RE = /\.stories\.[cm]?[jt]sx?$/i;
const SEMANTIC_TOKEN_RE = /--(?:background|foreground|primary|secondary|muted|accent|destructive|border|card|popover)\b|(?:bg|text|border)-(?:background|foreground|primary|secondary|muted|accent|destructive|border|card|popover)\b/;
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
const isInsideSvg = (node: TSESTree.Node): boolean => {
  let current: TSESTree.Node | null | undefined = node.parent;
  while (current !== undefined && current !== null) {
    if (
      current.type === AST_NODE_TYPES.JSXElement &&
      current.openingElement.name.type === AST_NODE_TYPES.JSXIdentifier &&
      (current.openingElement.name.name === "svg" ||
        SVG_DEFS_CONTAINERS.has(current.openingElement.name.name))
    ) {
      return true;
    }
    current = current.parent;
  }
  return false;
};

const hasSemanticTokenSystem = (filename: string): boolean => {
  let dir = dirname(filename);
  const root = parse(dir).root;
  for (let depth = 0; depth < 8; depth += 1) {
    const cached = semanticTokenCache.get(dir);
    if (cached !== undefined) return cached;

    let found = false;
    for (const rel of DETECTION_FILES) {
      const candidate = join(dir, rel);
      if (!existsSync(candidate)) continue;
      if (rel === "components.json") {
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
    semanticTokenCache.set(dir, found);
    if (found || dir === root) return found;
    dir = dirname(dir);
  }
  return false;
};

const propName = (key: TSESTree.Property["key"]): string | null => {
  if (key.type === AST_NODE_TYPES.Identifier) return key.name;
  if (key.type === AST_NODE_TYPES.Literal && typeof key.value === "string") return key.value;
  return null;
};

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
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
    if (options?.requireSemanticTokens === true && !hasSemanticTokenSystem(context.filename)) {
      return {};
    }

    const reportClasses = (value: string, node: TSESTree.Node): void => {
      for (const token of classTokens(value)) {
        const base = tailwindBase(token);
        if (RAW_PALETTE_RE.test(base)) {
          context.report({ node, messageId: "rawPalette", data: { class: token } });
        } else if (ARBITRARY_COLOR_RE.test(base)) {
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
        RAW_COLOR_VALUE_RE.test(node.value)
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
        if (
          typeof node.value.value === "string" &&
          SVG_EXEMPT_COLOR_VALUES.has(node.value.value.toLowerCase())
        ) {
          return;
        }
        if (isInsideSvg(node)) return;
        checkColorValueNode(node.value);
      },
      // Inline style objects: style={{ color: "#111827", backgroundColor: "#fff" }}
      "JSXAttribute[name.name='style'] ObjectExpression > Property"(node: TSESTree.Property): void {
        const name = propName(node.key);
        if (name !== null && STYLE_COLOR_PROPS.has(name)) checkColorValueNode(node.value);
      },
    };
  },
});
