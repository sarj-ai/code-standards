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

/** Broad token roles avoid silently disabling the rule for non-shadcn systems. */
const TOKEN_ROLES =
  "background|foreground|primary|secondary|muted|accent|destructive|danger|success|warning|info|border|card|popover|surface|content|base|subtle|default|ring|input|fg|bg";
const SEMANTIC_TOKEN_RE = new RegExp(
  `--(?:color-)?(?:${TOKEN_ROLES})\\b|(?:bg|text|border|ring|fill|stroke)-(?:ui-)?(?:${TOKEN_ROLES})\\b`,
);

/** Tailwind v4 declares its theme in CSS instead of a config file. */
const THEME_BLOCK_RE = /@theme\b/;

/** These files prove a token system exists even when its vocabulary comes from a preset. */
const PRESENCE_MARKERS = [
  "components.json",
  "tailwind.config.js",
  "tailwind.config.cjs",
  "tailwind.config.mjs",
  "tailwind.config.ts",
  "tailwind.config.mts",
  "tailwind.config.cts",
];

/** Stylesheets count only when their contents declare semantic tokens or an `@theme`. */
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
/** Workspace markers used when no `package.json#workspaces` declaration exists. */
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

// SVG subtree colors are artwork data rather than reusable UI tokens.
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

/** Intrinsic SVG shapes carry artwork colors; `className` and `style` remain checked. */
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

/** Email and PDF renderers cannot resolve CSS-variable-backed semantic tokens. */
const EMAIL_OR_PDF_MODULE_RE = /^@react-(?:email|pdf)\//;

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

/** Walk to the filesystem root and cache the resolved ancestry answer. */
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

/** Read workspace globs without adding a YAML dependency to the rule. */
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

/** Scan sibling packages because their token config is not on the source file's ancestry. */
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

const staticallyImportsEmailOrPdfRenderer = (program: TSESTree.Program): boolean =>
  program.body.some((statement) => {
    if (
      statement.type !== AST_NODE_TYPES.ImportDeclaration &&
      statement.type !== AST_NODE_TYPES.ExportNamedDeclaration &&
      statement.type !== AST_NODE_TYPES.ExportAllDeclaration
    ) {
      return false;
    }
    return (
      statement.source !== null &&
      typeof statement.source.value === "string" &&
      EMAIL_OR_PDF_MODULE_RE.test(statement.source.value)
    );
  });

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
    if (staticallyImportsEmailOrPdfRenderer(context.sourceCode.ast)) return {};
    if (options?.requireSemanticTokens === true && !hasSemanticTokenSystem(context.filename)) {
      return {};
    }

    let importsEmailOrPdfRenderer = false;
    const pendingReports: Array<{
      node: TSESTree.Node;
      messageId: MessageIds;
      data: Record<string, string>;
    }> = [];
    const report = (
      node: TSESTree.Node,
      messageId: MessageIds,
      data: Record<string, string>,
    ): void => {
      pendingReports.push({ node, messageId, data });
    };

    const reportClasses = (value: string, node: TSESTree.Node): void => {
      for (const token of classTokens(value)) {
        const base = tailwindBase(token);
        if (RAW_PALETTE_RE.test(base)) {
          report(node, "rawPalette", { class: token });
        } else if (ARBITRARY_COLOR_RE.test(base) && !CSS_VAR_REFERENCE_RE.test(base)) {
          report(node, "arbitraryColor", { class: token });
        }
      }
    };

    // Recurse through class fragments but leave calls to the CallExpression visitor.
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
        report(node, "inlineColor", { value: node.value });
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
        if (
          node.callee.type === AST_NODE_TYPES.Identifier &&
          node.callee.name === "require" &&
          node.arguments[0]?.type === AST_NODE_TYPES.Literal &&
          typeof node.arguments[0].value === "string" &&
          EMAIL_OR_PDF_MODULE_RE.test(node.arguments[0].value)
        ) {
          importsEmailOrPdfRenderer = true;
        }
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
      // SVG artwork colors are exempt; component presentation colors still report.
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
      ImportExpression(node: TSESTree.ImportExpression): void {
        if (
          node.source.type === AST_NODE_TYPES.Literal &&
          typeof node.source.value === "string" &&
          EMAIL_OR_PDF_MODULE_RE.test(node.source.value)
        ) {
          importsEmailOrPdfRenderer = true;
        }
      },
      "Program:exit"(): void {
        if (importsEmailOrPdfRenderer) return;
        for (const descriptor of pendingReports) context.report(descriptor);
      },
    };
  },
});
