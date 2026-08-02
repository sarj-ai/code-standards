/**
 * @fileoverview prefer-semantic-colors — a raw palette class or hex literal pins a colour the design system can no longer retheme.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-semantic-colors.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";
import { existsSync, readdirSync, readFileSync } from "fs";
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
 * Token ROLES, not one vendor's token NAMES.
 *
 * The previous vocabulary was shadcn's and only shadcn's, so a repo with a
 * complete, consistently used design system was read as having none and the
 * `requireSemanticTokens` gate suppressed the rule across the whole repo.
 * Medusa is the worked example: its system is `bg-ui-bg-base` /
 * `text-ui-fg-subtle` backed by `--fg-base` / `--bg-base` custom properties, so
 * its `globals.css` was FOUND and then REJECTED. `dub` names its tokens
 * `content-default` / `bg-default` and lost the same way.
 *
 * Detection errs deliberately towards "a system exists". Guessing yes leaves
 * the rule RUNNING, and an author can disable any line it reports with a
 * reason; guessing no silently disables an error-level rule for a whole
 * repository, and nobody finds out. Those costs are not symmetric, which is why
 * this is a role vocabulary rather than an exact token list.
 */
const TOKEN_ROLES =
  "background|foreground|primary|secondary|muted|accent|destructive|danger|success|warning|info|border|card|popover|surface|content|base|subtle|default|ring|input|fg|bg";
const SEMANTIC_TOKEN_RE = new RegExp(
  `--(?:color-)?(?:${TOKEN_ROLES})\\b|(?:bg|text|border|ring|fill|stroke)-(?:ui-)?(?:${TOKEN_ROLES})\\b`,
);

/**
 * Tailwind v4 is CSS-first: there is no `tailwind.config.*` to find, and the
 * theme lives in an `@theme` block in the stylesheet. Without this, every v4
 * setup reads as "no design system" and the gate suppresses the rule.
 */
const THEME_BLOCK_RE = /@theme\b/;

/**
 * Files whose PRESENCE alone proves a configured Tailwind design system.
 *
 * Reading these for a token vocabulary was the second half of the same defect.
 * A `tailwind.config.*` frequently defines its theme by importing a preset
 * (`presets: [require("@medusajs/ui-preset")]`) or by spreading a shared
 * object, so the token names are not textually present in the file that proves
 * they exist. `components.json` was already treated this way; the config files
 * are the same kind of evidence and are now treated the same.
 */
const PRESENCE_MARKERS = [
  "components.json",
  "tailwind.config.js",
  "tailwind.config.cjs",
  "tailwind.config.mjs",
  "tailwind.config.ts",
  "tailwind.config.mts",
  "tailwind.config.cts",
];

/**
 * Stylesheets that only count as evidence if they actually DECLARE tokens.
 *
 * Unlike a Tailwind config, the existence of a `globals.css` says nothing — every
 * app has one. So these are read and matched against `SEMANTIC_TOKEN_RE` or the
 * v4 `@theme` block.
 */
const CSS_DETECTION_FILES = [
  "app/globals.css",
  "app/global.css",
  "app/styles/globals.css",
  "src/app/globals.css",
  "src/app/global.css",
  "src/global.css",
  "src/index.css",
  "src/styles/globals.css",
  "src/styles/index.css",
  "styles/globals.css",
  "styles/index.css",
];
/**
 * Files that mark a directory as the root of a multi-package workspace.
 *
 * `package.json` is handled separately: only a `workspaces` field counts, since
 * every package has a `package.json` and treating it as a root would stop the
 * sideways scan at the nearest leaf package.
 */
const WORKSPACE_ROOT_FILES = [
  "pnpm-workspace.yaml",
  "pnpm-workspace.yml",
  "turbo.json",
  "lerna.json",
];

/** Where workspace packages live when the root declares no globs, or none parse. */
const DEFAULT_WORKSPACE_GLOBS = ["packages/*", "apps/*"];

/** Upper bound on the sideways scan, so a huge monorepo cannot stall a lint run. */
const MAX_WORKSPACE_PACKAGES = 512;

/** "Is there a detection file at or above this directory?" — a pure ancestry fact. */
const ancestryCache = new Map<string, boolean>();

/** "Does any package of this workspace carry a detection file?", keyed by root. */
const workspaceScanCache = new Map<string, boolean>();

/** Nearest workspace root at or above a directory, `null` if there is none. */
const workspaceRootCache = new Map<string, string | null>();

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

/** Does this one directory carry a design-token marker? */
const hasMarkerAt = (dir: string): boolean => {
  if (PRESENCE_MARKERS.some((rel) => existsSync(join(dir, rel)))) return true;
  for (const rel of CSS_DETECTION_FILES) {
    const candidate = join(dir, rel);
    if (!existsSync(candidate)) continue;
    try {
      const css = readFileSync(candidate, "utf8");
      if (SEMANTIC_TOKEN_RE.test(css) || THEME_BLOCK_RE.test(css)) return true;
    } catch {
      // Ignore unreadable stylesheets; absence of evidence means no report.
    }
  }
  return false;
};

/**
 * Is there a marker at or above `startDir`? Walks to the filesystem root.
 *
 * There is deliberately no depth budget. A budget introduces a third answer —
 * "ran out" — which has to be reported as one of the other two, and reporting it
 * as "no design system" made this gate's result depend on the ORDER files were
 * linted in.
 *
 * Every visited directory is memoised, so the walk runs once per tree. Caching
 * the resolved answer for all of them is sound: each sits at or below wherever
 * the answer was settled, so "at or above" holds for each of them too.
 */
const hasMarkerAtOrAbove = (startDir: string): boolean => {
  let dir = startDir;
  const root = parse(dir).root;
  const visited: string[] = [];
  let answer: boolean;

  for (;;) {
    const cached = ancestryCache.get(dir);
    if (cached !== undefined) {
      answer = cached;
      break;
    }
    visited.push(dir);
    if (hasMarkerAt(dir)) {
      answer = true;
      break;
    }
    const parent = dirname(dir);
    if (dir === root || parent === dir) {
      answer = false;
      break;
    }
    dir = parent;
  }

  for (const seen of visited) ancestryCache.set(seen, answer);
  return answer;
};

/**
 * The workspace globs a root declares, from `package.json` or `pnpm-workspace.yaml`.
 *
 * The YAML is read with a line regex rather than a parser: a dependency-free rule
 * cannot pull one in, and the only shape that matters is the flat `packages:`
 * list every pnpm workspace writes.
 */
const readWorkspaceGlobs = (dir: string): string[] => {
  const globs: string[] = [];

  const packageJson = join(dir, "package.json");
  if (existsSync(packageJson)) {
    try {
      const parsed: unknown = JSON.parse(readFileSync(packageJson, "utf8"));
      const declared =
        typeof parsed === "object" && parsed !== null && "workspaces" in parsed
          ? (parsed as { workspaces?: unknown }).workspaces
          : undefined;
      const list = Array.isArray(declared)
        ? declared
        : typeof declared === "object" &&
            declared !== null &&
            Array.isArray((declared as { packages?: unknown }).packages)
          ? (declared as { packages: unknown[] }).packages
          : [];
      for (const entry of list) if (typeof entry === "string") globs.push(entry);
    } catch {
      // A malformed package.json is not this rule's problem to report.
    }
  }

  for (const name of ["pnpm-workspace.yaml", "pnpm-workspace.yml"]) {
    const yaml = join(dir, name);
    if (!existsSync(yaml)) continue;
    try {
      for (const line of readFileSync(yaml, "utf8").split("\n")) {
        const match = /^\s*-\s*["']?([^"'#\s]+)["']?\s*$/u.exec(line);
        if (match?.[1] !== undefined) globs.push(match[1]);
      }
    } catch {
      // Same.
    }
  }

  return globs;
};

/** Expand a workspace glob one level: `packages/*`, `packages/**`, or a literal path. */
const expandWorkspaceGlob = (root: string, glob: string): string[] => {
  const star = glob.indexOf("*");
  if (star === -1) return [join(root, glob)];

  const prefix = glob.slice(0, star).replace(/\/$/u, "");
  const parent = prefix === "" ? root : join(root, prefix);
  try {
    return readdirSync(parent, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && !entry.name.startsWith("."))
      .map((entry) => join(parent, entry.name));
  } catch {
    return [];
  }
};

/** Nearest directory at or above `startDir` that declares a multi-package workspace. */
const findWorkspaceRoot = (startDir: string): string | null => {
  let dir = startDir;
  const root = parse(dir).root;
  const visited: string[] = [];
  let answer: string | null;

  for (;;) {
    const cached = workspaceRootCache.get(dir);
    if (cached !== undefined) {
      answer = cached;
      break;
    }
    visited.push(dir);
    if (
      WORKSPACE_ROOT_FILES.some((name) => existsSync(join(dir, name))) ||
      readWorkspaceGlobs(dir).length > 0
    ) {
      answer = dir;
      break;
    }
    const parent = dirname(dir);
    if (dir === root || parent === dir) {
      answer = null;
      break;
    }
    dir = parent;
  }

  for (const seen of visited) workspaceRootCache.set(seen, answer);
  return answer;
};

/**
 * Does any package of this workspace carry a design-token marker?
 *
 * An upward walk alone silences a whole monorepo whose token config lives in a
 * sibling package: no ancestor chain from a source file passes through it. A
 * token system in a sibling package is still a token system — that is what a
 * workspace IS — so the scan goes sideways from the workspace root when, and only
 * when, the upward walk has already come back empty.
 */
const workspaceHasMarker = (root: string): boolean => {
  const cached = workspaceScanCache.get(root);
  if (cached !== undefined) return cached;

  const globs = readWorkspaceGlobs(root);
  const candidates = new Set<string>();
  for (const glob of globs.length > 0 ? globs : DEFAULT_WORKSPACE_GLOBS) {
    for (const dir of expandWorkspaceGlob(root, glob)) {
      candidates.add(dir);
      if (candidates.size >= MAX_WORKSPACE_PACKAGES) break;
    }
    if (candidates.size >= MAX_WORKSPACE_PACKAGES) break;
  }

  let found = false;
  for (const dir of candidates) {
    if (hasMarkerAt(dir)) {
      found = true;
      break;
    }
  }
  workspaceScanCache.set(root, found);
  return found;
};

/** Does a design-token system exist anywhere this file's project can see? */
const hasSemanticTokenSystem = (filename: string): boolean => {
  const dir = dirname(filename);
  if (hasMarkerAtOrAbove(dir)) return true;
  const root = findWorkspaceRoot(dir);
  return root !== null && workspaceHasMarker(root);
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
