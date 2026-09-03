/**
 * @fileoverview prefer-semantic-colors — a raw palette class or hex literal pins a colour the design system can no longer retheme.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-semantic-colors.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";
import { existsSync, lstatSync, readdirSync, readFileSync } from "fs";
import { dirname, join, parse } from "path";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { classTokens, tailwindBase, tailwindVariantPrefix } from "./_tailwind.js";

type MessageIds =
  | "rawPalette"
  | "arbitraryColor"
  | "inlineColor"
  | "opaqueForegroundPair";

export const PREFER_SEMANTIC_COLORS_DOCUMENTATION = {
  summary: "Enforce semantic color tokens over raw Tailwind palette classes, arbitrary color values, and inline color literals.",
  rationale: "Semantic tokens keep themes and product meaning consistent while raw colors couple components to a palette value.",
  remediation: "Replace raw palette and literal colors with the closest semantic design-system token or CSS variable.",
  category: "style",
  limitations: [
    "Email, PDF, video-rendering, print-only, icon artwork, masks, gradients, stories, and explicitly configured non-token projects have targeted exclusions.",
    "Opaque-foreground checks are opt-in and require both a same-variant semantic background class and its package-local declared foreground token.",
  ],
  examples: [
    { id: "semantic-text-color", title: "Use a semantic color token", outcome: "no-match", files: [{ path: "src/notice.tsx", source: "const notice = <div className=\"text-destructive\" />;" }], focusPath: "src/notice.tsx", expectedCount: 0, public: true },
    { id: "raw-text-color", title: "Do not use a raw palette color", outcome: "match", files: [{ path: "src/notice.tsx", source: "const notice = <div className=\"text-red-500\" />;" }], focusPath: "src/notice.tsx", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
type Options = readonly [
  {
    opaqueForegroundPairs?: boolean;
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
const CLASS_FNS: ReadonlySet<string> = new Set(["cn", "clsx", "cva", "tv", "cx", "twMerge", "classnames", "classNames"]);
const CLASS_NAME_RE = /class/i;

/** CSS color-bearing properties, in their JSX (camelCase) and SVG-attribute forms. */
const STYLE_COLOR_PROPS: ReadonlySet<string> = new Set([
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
] as const;

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
] as const;
/** Workspace markers used when no `package.json#workspaces` declaration exists. */
const WORKSPACE_ROOT_FILES = [
  "pnpm-workspace.yaml",
  "pnpm-workspace.yml",
  "turbo.json",
  "lerna.json",
] as const;

/** Where workspace packages live when the root declares no globs, or none parse. */
const DEFAULT_WORKSPACE_GLOBS = ["packages/*", "apps/*"] as const;

/** Upper bound on the sideways scan, so a huge monorepo cannot stall a lint run. */
const MAX_WORKSPACE_PACKAGES = 512;

/** "Is there a detection file at or above this directory?" — a pure ancestry fact. */
const ANCESTRY_CACHE = new Map<string, boolean>();

/** "Does any package of this workspace carry a detection file?", keyed by root. */
const WORKSPACE_SCAN_CACHE = new Map<string, boolean>();

/** Nearest workspace root at or above a directory, `null` if there is none. */
const WORKSPACE_ROOT_CACHE = new Map<string, string | null>();

/** SVG container elements whose children carry structural (not UI-token) colors. */
const SVG_DEFS_CONTAINERS: ReadonlySet<string> = new Set([
  "mask",
  "clipPath",
  "defs",
  "pattern",
  "linearGradient",
  "radialGradient",
]);

/** Neutral fill/stroke literals that are SVG drawing data, never a UI token. */
const SVG_EXEMPT_COLOR_VALUES: ReadonlySet<string> = new Set([
  "#fff",
  "#ffffff",
  "#000",
  "#000000",
  "transparent",
  "none",
  "currentcolor",
  "inherit",
]);

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

// SVG subtree colors are artwork data rather than reusable UI tokens.
function jsxElementName(node: TSESTree.JSXElement): string | null {
  const name = node.openingElement.name;
  if (name.type === AST_NODE_TYPES.JSXIdentifier) return name.name;
  if (name.type === AST_NODE_TYPES.JSXMemberExpression && name.property.type === AST_NODE_TYPES.JSXIdentifier) {
    return name.property.name;
  }
  return null;
}

/** Intrinsic SVG shapes carry artwork colors; `className` and `style` remain checked. */
const SVG_SHAPE_PRIMITIVES: ReadonlySet<string> = new Set([
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

/** Render targets that cannot safely inherit the application's semantic CSS variables. */
const EXTERNAL_RENDERER_MODULE_RE = /^(?:@react-(?:email|pdf)\/|remotion$|@remotion\/)/;

const OPAQUE_FOREGROUND_RE = /^text-(?:white|black)(?:\/100)?$/;
const SEMANTIC_BACKGROUND_RE = /^bg-([a-z][a-z0-9-]*)$/;
const CSS_COMMENT_RE = /\/\*[\s\S]*?\*\//gu;
const DECLARED_FOREGROUND_RE = /--(?:color-)?([a-z][a-z0-9-]*)-foreground\s*:/giu;
const MAX_TOKEN_STYLESHEET_BYTES = 1_048_576;

interface CachedSemanticDeclarations {
  readonly fingerprint: string;
  readonly value: ReadonlySet<string>;
}

const SEMANTIC_DECLARATIONS_CACHE = new Map<string, CachedSemanticDeclarations>();

function isSvgLikeElementName(name: string): boolean {
  return name === "svg" || SVG_DEFS_CONTAINERS.has(name) || /svg$/i.test(name);
}

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

/** Does a design-token system exist anywhere this file's project can see? */
const hasSemanticTokenSystem = (filename: string): boolean => {
  const dir = dirname(filename);
  if (hasMarkerAtOrAbove(dir)) return true;
  const root = findWorkspaceRoot(dir);
  return root !== null && workspaceHasMarker(root);
};

/** Walk to the filesystem root and cache the resolved ancestry answer. */
const hasMarkerAtOrAbove = (startDir: string): boolean => {
  let dir = startDir;
  const root = parse(dir).root;
  const visited: string[] = [];
  let answer: boolean;

  for (;;) {
    const cached = ANCESTRY_CACHE.get(dir);
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

  for (const seen of visited) ANCESTRY_CACHE.set(seen, answer);
  return answer;
};

/** Nearest directory at or above `startDir` that declares a multi-package workspace. */
const findWorkspaceRoot = (startDir: string): string | null => {
  let dir = startDir;
  const root = parse(dir).root;
  const visited: string[] = [];
  let answer: string | null;

  for (;;) {
    const cached = WORKSPACE_ROOT_CACHE.get(dir);
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

  for (const seen of visited) WORKSPACE_ROOT_CACHE.set(seen, answer);
  return answer;
};

/** Scan sibling packages because their token config is not on the source file's ancestry. */
const workspaceHasMarker = (root: string): boolean => {
  const cached = WORKSPACE_SCAN_CACHE.get(root);
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
  WORKSPACE_SCAN_CACHE.set(root, found);
  return found;
};

/** Expand a workspace glob one level: `packages/*`, `packages/**`, or a literal path. */
const expandWorkspaceGlob = (root: string, glob: string): string[] => {
  const star = glob.indexOf("*");
  if (star === -1) return [join(root, glob)];

  const prefix = glob.slice(0, star).replace(/\/$/u, "");
  const parent = prefix === "" ? root : join(root, prefix);
  if (!existsSync(parent) || !lstatSync(parent).isDirectory()) return [];
  return readdirSync(parent, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && !entry.name.startsWith("."))
    .sort((left, right) => left.name.localeCompare(right.name))
    .map((entry) => join(parent, entry.name));
};

const propName = (key: TSESTree.Property["key"]): string | null => {
  if (key.type === AST_NODE_TYPES.Identifier) return key.name;
  if (key.type === AST_NODE_TYPES.Literal && typeof key.value === "string") return key.value;
  return null;
};

const staticallyImportsExternalRenderer = (program: TSESTree.Program): boolean =>
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
      EXTERNAL_RENDERER_MODULE_RE.test(statement.source.value)
    );
  });

/** Package-local declarations that make opaque-neutral replacements concrete. */
const semanticForegroundRoles = (filename: string): ReadonlySet<string> => {
  const packageRoot = nearestPackageRoot(dirname(filename));
  if (packageRoot === null) return new Set<string>();
  const candidates = CSS_DETECTION_FILES.map((relative) => join(packageRoot, relative));
  const fingerprint = candidates.map(fileFingerprint).join("|");
  const cached = SEMANTIC_DECLARATIONS_CACHE.get(packageRoot);
  if (cached?.fingerprint === fingerprint) return cached.value;

  const foregroundRoles = new Set<string>();
  for (const candidate of candidates) {
    const css = readTokenStylesheet(candidate);
    if (css === null) continue;
    const declarations = css.replace(CSS_COMMENT_RE, "");
    for (const match of declarations.matchAll(DECLARED_FOREGROUND_RE)) {
      if (match[1] !== undefined) foregroundRoles.add(match[1].toLowerCase());
    }
  }
  SEMANTIC_DECLARATIONS_CACHE.set(packageRoot, { fingerprint, value: foregroundRoles });
  return foregroundRoles;
};

const nearestPackageRoot = (startDir: string): string | null => {
  let dir = startDir;
  const root = parse(dir).root;
  for (;;) {
    if (existsSync(join(dir, "package.json"))) {
      return dir;
    }
    const parent = dirname(dir);
    if (dir === root || parent === dir) return null;
    dir = parent;
  }
};

const fileFingerprint = (path: string): string => {
  try {
    const stat = lstatSync(path);
    return stat.isFile() ? `${path}:${stat.size}:${stat.mtimeMs}` : `${path}:excluded`;
  } catch {
    return `${path}:missing`;
  }
};

const readTokenStylesheet = (path: string): string | null => {
  try {
    const stat = lstatSync(path);
    if (!stat.isFile() || stat.size > MAX_TOKEN_STYLESHEET_BYTES) return null;
    return readFileSync(path, "utf8");
  } catch {
    return null;
  }
};

export default createRule<Options, MessageIds>({
  name: "prefer-semantic-colors",
  documentation: PREFER_SEMANTIC_COLORS_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Enforce semantic color tokens over raw Tailwind palette classes, arbitrary color values, and inline color literals.",
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          requireSemanticTokens: { type: "boolean" },
          opaqueForegroundPairs: { type: "boolean" },
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
      opaqueForegroundPair:
        "'{{class}}' bypasses the declared '{{replacement}}' token paired with '{{background}}'.",
    },
  },
  defaultOptions: [{}],
  create(context, [options]) {
    if (STORIES_FILE_RE.test(context.filename)) return {};
    if (staticallyImportsExternalRenderer(context.sourceCode.ast)) return {};
    if (
      options?.requireSemanticTokens === true &&
      !hasSemanticTokenSystem(context.filename)
    ) return {};
    const foregroundRoles = options?.opaqueForegroundPairs === true
      ? semanticForegroundRoles(context.filename)
      : new Set<string>();
    const checkOpaqueForegroundPairs = foregroundRoles.size > 0;

    let importsExternalRenderer = false;
    const pendingReports = new Map<string, {
      node: TSESTree.Node;
      messageId: MessageIds;
      data: Record<string, string>;
    }>();
    const report = (
      node: TSESTree.Node,
      messageId: MessageIds,
      data: Record<string, string>,
    ): void => {
      const key = `${node.range[0]}:${node.range[1]}:${messageId}:${JSON.stringify(data)}`;
      pendingReports.set(key, { node, messageId, data });
    };

    const reportClasses = (value: string, node: TSESTree.Node): void => {
      const tokens = classTokens(value);
      for (const token of tokens) {
        const base = tailwindBase(token);
        if (RAW_PALETTE_RE.test(base)) {
          report(node, "rawPalette", { class: token });
        } else if (ARBITRARY_COLOR_RE.test(base) && !CSS_VAR_REFERENCE_RE.test(base)) {
          report(node, "arbitraryColor", { class: token });
        }
      }

      if (!checkOpaqueForegroundPairs || isInsideSvg(node)) return;
      for (const token of tokens) {
        const prefix = tailwindVariantPrefix(token);
        if (prefix.split(":").includes("print")) continue;
        const base = tailwindBase(token);
        if (!OPAQUE_FOREGROUND_RE.test(base)) continue;

        const semanticBackground = tokens.find((candidate) => {
          if (tailwindVariantPrefix(candidate) !== prefix) return false;
          const match = SEMANTIC_BACKGROUND_RE.exec(tailwindBase(candidate));
          return match?.[1] !== undefined && foregroundRoles.has(match[1]);
        });
        if (semanticBackground === undefined) continue;
        const role = SEMANTIC_BACKGROUND_RE.exec(tailwindBase(semanticBackground))?.[1];
        if (role === undefined) continue;
        report(node, "opaqueForegroundPair", {
          background: semanticBackground,
          class: token,
          replacement: `${prefix}text-${role}-foreground`,
        });
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
          EXTERNAL_RENDERER_MODULE_RE.test(node.arguments[0].value)
        ) {
          importsExternalRenderer = true;
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
          EXTERNAL_RENDERER_MODULE_RE.test(node.source.value)
        ) {
          importsExternalRenderer = true;
        }
      },
      "Program:exit"(): void {
        if (importsExternalRenderer) return;
        for (const descriptor of pendingReports.values()) context.report(descriptor);
      },
    };
  },
});
