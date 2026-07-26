/**
 * @fileoverview Flag a junk-drawer module stem that has a single public export.
 * TS port of Python SARJ022. Fires ONLY when BOTH hold:
 *
 *   (a) the file's basename stem is a generic "junk-drawer" name that describes
 *       no responsibility (`utils`, `helpers`, `types`, `models`, ...), AND
 *   (b) the module has exactly one public export, and that export is a named
 *       function / class / function-const, so the rename target is unambiguous.
 *
 * When both hold, the sole export's name is the information-rich replacement for
 * the meaningless stem (`utils.ts` exporting `snakeCaseText` -> `snake-case-text.ts`).
 *
 * A junk-drawer stem carries no domain to lose, so replacing it with the export
 * name is strictly an improvement; an informative stem (`pagination.ts`) names a
 * domain broader than its one current export and is deliberately never flagged.
 *
 * CORPUS SWEEP (2220 files, zod / TanStack Query / react-router / swr /
 * zustand, 2026-07): 1 hit, and it was a false positive —
 * `react-router/packages/react-router/__tests__/server-runtime/utils.ts:20`
 * exports one `mockServerBuild` helper. The basename-only `TEST_FILE_RE` does
 * not see `__tests__/`, so test-support modules escaped the existing test
 * exemption; a suite's shared helper module is `utils.ts` by convention and
 * renaming it buys nothing. The check now also consults the shared `isTestFile`
 * path predicate, which understands directories.
 */

import { ESLintUtils, type TSESTree, AST_NODE_TYPES } from "@typescript-eslint/utils";

import { isTestFile } from "./_paths.js";

type MessageIds = "renameJunkDrawer";
type Options = readonly [];

// Generic module stems that describe no responsibility. `index` is deliberately
// excluded: barrel files legitimately re-export many symbols under that name.
const JUNK_DRAWER_STEMS = new Set([
  "util",
  "utils",
  "helper",
  "helpers",
  "common",
  "constant",
  "constants",
  "type",
  "types",
  "model",
  "models",
  "shared",
  "misc",
]);

// Exports whose name is an idiomatic ecosystem convention that lives in a
// junk-drawer bucket by design — flagging them fights the convention and the
// bucket is expected to grow. `cn` is the shadcn/ui tailwind-merge className
// helper that scaffolds into `lib/utils.ts`; renaming to `cn.ts` breaks every
// `import { cn } from "@/lib/utils"`.
const CONVENTIONAL_BUCKET_EXPORTS = new Set(["cn"]);

// Multi-word acronyms whose accepted kebab-case is a single token rather than a
// letter-by-letter split (`OAuth` -> `oauth`, not `o-auth`).
const ACRONYM_OVERRIDES: ReadonlyArray<readonly [RegExp, string]> = [
  [/OAuth/g, "Oauth"],
  [/GraphQL/g, "Graphql"],
  [/gRPC/g, "Grpc"],
];

// Split on camelCase boundaries while keeping runs of capitals (acronyms)
// together: `HTTPServer` -> `HTTP` + `Server`, `JWTHandler` -> `JWT` + `Handler`.
const CAMEL_BOUNDARY_RE = /(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])/g;

const TEST_FILE_RE = /\.(test|spec)\.[cm]?[jt]sx?$/i;
const SCRIPT_EXT_RE = /\.[cm]?[jt]sx?$/i;

interface ExportSummary {
  readonly names: number;
  readonly hasReExport: boolean;
  readonly candidate: { name: string; node: TSESTree.Node } | null;
}

const basename = (filename: string): string =>
  filename.split(/[/\\]/).pop() ?? filename;

const stemOf = (base: string): string => base.replace(SCRIPT_EXT_RE, "");

const kebabCase = (name: string): string => {
  let normalized = name;
  for (const [pattern, replacement] of ACRONYM_OVERRIDES) {
    normalized = normalized.replace(pattern, replacement);
  }
  return normalized.replace(CAMEL_BOUNDARY_RE, "-").toLowerCase();
};

const isFunctionExpression = (node: TSESTree.Expression | null): boolean =>
  node !== null &&
  (node.type === AST_NODE_TYPES.ArrowFunctionExpression ||
    node.type === AST_NODE_TYPES.FunctionExpression);

// A `const foo = () => {}` is a rename candidate; a value const (`const MAX = 5`)
// is not — renaming a file after a bare constant loses more than it gains.
const functionConstName = (
  decl: TSESTree.VariableDeclaration,
): string | null => {
  if (decl.declarations.length !== 1) return null;
  const [declarator] = decl.declarations;
  if (declarator === undefined) return null;
  if (declarator.id.type !== AST_NODE_TYPES.Identifier) return null;
  if (!isFunctionExpression(declarator.init)) return null;
  return declarator.id.name;
};

const summarizeExports = (body: readonly TSESTree.ProgramStatement[]): ExportSummary => {
  let names = 0;
  let hasReExport = false;
  let candidate: { name: string; node: TSESTree.Node } | null = null;

  const addCandidate = (name: string, node: TSESTree.Node): void => {
    names += 1;
    candidate = { name, node };
  };

  for (const statement of body) {
    switch (statement.type) {
      case AST_NODE_TYPES.ExportAllDeclaration:
        hasReExport = true;
        break;
      case AST_NODE_TYPES.ExportDefaultDeclaration: {
        names += 1;
        const decl = statement.declaration;
        if (
          decl.type === AST_NODE_TYPES.FunctionDeclaration &&
          decl.id !== null
        ) {
          candidate = { name: decl.id.name, node: statement };
        } else if (
          decl.type === AST_NODE_TYPES.ClassDeclaration &&
          decl.id !== null
        ) {
          candidate = { name: decl.id.name, node: statement };
        }
        break;
      }
      case AST_NODE_TYPES.ExportNamedDeclaration: {
        if (statement.source !== null) {
          hasReExport = true;
          break;
        }
        const decl = statement.declaration;
        if (decl === null) {
          names += statement.specifiers.length;
          break;
        }
        switch (decl.type) {
          case AST_NODE_TYPES.FunctionDeclaration:
            if (decl.id !== null) addCandidate(decl.id.name, statement);
            else names += 1;
            break;
          case AST_NODE_TYPES.ClassDeclaration:
            if (decl.id !== null) addCandidate(decl.id.name, statement);
            else names += 1;
            break;
          case AST_NODE_TYPES.VariableDeclaration: {
            const fnName = functionConstName(decl);
            if (fnName !== null && decl.declarations.length === 1) {
              addCandidate(fnName, statement);
            } else {
              names += decl.declarations.length;
            }
            break;
          }
          default:
            names += 1;
        }
        break;
      }
      default:
        break;
    }
  }

  return { names, hasReExport, candidate };
};

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "single-public-export",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "A junk-drawer module stem (`utils`, `helpers`, `types`, ...) with a single public function/class/const export should be renamed after that export.",
    },
    schema: [],
    messages: {
      renameJunkDrawer:
        "Module stem `{{stem}}` is a generic junk-drawer name; its sole public export is `{{name}}` — rename the file to `{{expected}}.ts` to describe its responsibility.",
    },
  },
  defaultOptions: [],
  create(context) {
    const base = basename(context.filename);

    if (base.endsWith(".d.ts")) return {};
    if (TEST_FILE_RE.test(base)) return {};
    // A test-support module is conventionally `__tests__/utils.ts`; the suite
    // imports it as "the helpers for these tests" and the stem is meaningful in
    // that context. `TEST_FILE_RE` only sees the basename, so it misses these.
    if (isTestFile(context.filename)) return {};

    const stem = stemOf(base);
    if (!JUNK_DRAWER_STEMS.has(stem.toLowerCase())) return {};

    return {
      Program(node: TSESTree.Program): void {
        const { names, hasReExport, candidate } = summarizeExports(node.body);
        if (hasReExport) return;
        if (names !== 1 || candidate === null) return;
        if (CONVENTIONAL_BUCKET_EXPORTS.has(candidate.name)) return;

        const expected = kebabCase(candidate.name);
        if (stem === expected) return;

        context.report({
          node: candidate.node,
          messageId: "renameJunkDrawer",
          data: { stem, name: candidate.name, expected },
        });
      },
    };
  },
});
