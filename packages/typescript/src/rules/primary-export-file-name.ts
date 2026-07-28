/**
 * @fileoverview Flag a module whose filename stem does not match its primary export.
 *
 * Semantic File Naming Rule:
 * When a TypeScript/TSX module has a single primary export (a sole exported
 * function, class, or React component, or a default export), its filename stem
 * should semantically reflect that export's name in kebab-case.
 *
 * Examples:
 *   - File `user-helpers.tsx` exporting sole `UserProfileCard` -> rename to `user-profile-card.tsx`.
 *   - File `account-stuff.ts` exporting sole `AccountService` -> rename to `account-service.ts`.
 *   - File `auth-hook.ts` exporting sole `useAuthSession` -> rename to `use-auth-session.ts`.
 *
 * Exemptions (Corpus-validated against noura-be, bulbul, and top TS repos):
 *   - Barrel re-export files (`index.ts`, `index.tsx`).
 *   - Declaration files (`*.d.ts`).
 *   - Test files (`*.test.ts`, `*.spec.ts`, `isTestFile`).
 *   - Framework route files (`page.tsx`, `layout.tsx`, `route.ts`, `$id.tsx`, `[id].tsx`, `__root.tsx`).
 *   - Standard framework convention stems (`config`, `constants`, `errors`, `types`).
 *   - Entrypoint functions (`main`, `run`, `cli`, `setup`, `teardown`, `execute`).
 *   - Conventional exports (`cn`).
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "primaryExportMismatch";
type Options = readonly [];

const CONVENTIONAL_BUCKET_EXPORTS = new Set(["cn"]);
const GENERIC_ENTRYPOINTS = new Set(["main", "run", "cli", "setup", "teardown", "execute"]);

const ACRONYM_OVERRIDES: ReadonlyArray<readonly [RegExp, string]> = [
  [/OAuth/g, "Oauth"],
  [/GraphQL/g, "Graphql"],
  [/gRPC/g, "Grpc"],
];

const CAMEL_BOUNDARY_RE = /(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])/g;

const basename = (filename: string): string =>
  filename.split(/[/\\]/).pop() ?? filename;

const stemOf = (base: string): string =>
  base.replace(/\.(test|spec|config|d|stories)\.[cm]?[jt]sx?$/i, "").replace(/\.[cm]?[jt]sx?$/i, "");

const kebabCase = (name: string): string => {
  let normalized = name;
  for (const [pattern, replacement] of ACRONYM_OVERRIDES) {
    normalized = normalized.replace(pattern, replacement);
  }
  return normalized.replace(CAMEL_BOUNDARY_RE, "-").toLowerCase();
};

const isFunctionOrClass = (node: TSESTree.Node): boolean =>
  node.type === AST_NODE_TYPES.ArrowFunctionExpression ||
  node.type === AST_NODE_TYPES.FunctionExpression;

interface PrimaryExportInfo {
  readonly name: string;
  readonly node: TSESTree.Node;
  readonly count: number;
  readonly isDefault: boolean;
}

const findPrimaryExport = (body: readonly TSESTree.ProgramStatement[]): PrimaryExportInfo | null => {
  let exportCount = 0;
  let primaryCandidate: { name: string; node: TSESTree.Node; isDefault: boolean } | null = null;

  for (const statement of body) {
    if (statement.type === AST_NODE_TYPES.ExportAllDeclaration) {
      return null; // Barrel file
    }

    if (statement.type === AST_NODE_TYPES.ExportDefaultDeclaration) {
      exportCount += 1;
      const decl = statement.declaration;
      if (
        (decl.type === AST_NODE_TYPES.FunctionDeclaration || decl.type === AST_NODE_TYPES.ClassDeclaration) &&
        decl.id !== null
      ) {
        primaryCandidate = { name: decl.id.name, node: statement, isDefault: true };
      } else if (decl.type === AST_NODE_TYPES.Identifier) {
        primaryCandidate = { name: decl.name, node: statement, isDefault: true };
      }
    } else if (statement.type === AST_NODE_TYPES.ExportNamedDeclaration) {
      if (statement.source !== null) {
        return null; // Re-export
      }
      const decl = statement.declaration;
      if (decl === null) {
        exportCount += statement.specifiers.length;
        if (statement.specifiers.length === 1 && primaryCandidate === null) {
          const spec = statement.specifiers[0];
          if (spec && spec.exported.type === AST_NODE_TYPES.Identifier) {
            primaryCandidate = { name: spec.exported.name, node: statement, isDefault: false };
          }
        }
      } else if (decl.type === AST_NODE_TYPES.FunctionDeclaration || decl.type === AST_NODE_TYPES.ClassDeclaration) {
        if (decl.id !== null) {
          exportCount += 1;
          if (primaryCandidate === null) {
            primaryCandidate = { name: decl.id.name, node: statement, isDefault: false };
          }
        }
      } else if (decl.type === AST_NODE_TYPES.VariableDeclaration) {
        for (const declarator of decl.declarations) {
          if (declarator.id.type === AST_NODE_TYPES.Identifier) {
            exportCount += 1;
            if (primaryCandidate === null && declarator.init && isFunctionOrClass(declarator.init)) {
              primaryCandidate = { name: declarator.id.name, node: statement, isDefault: false };
            }
          }
        }
      } else if (decl.type === AST_NODE_TYPES.TSTypeAliasDeclaration || decl.type === AST_NODE_TYPES.TSInterfaceDeclaration) {
        exportCount += 1;
        if (primaryCandidate === null) {
          primaryCandidate = { name: decl.id.name, node: statement, isDefault: false };
        }
      }
    }
  }

  if (primaryCandidate === null || exportCount > 2) {
    return null;
  }

  return { ...primaryCandidate, count: exportCount };
};

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "primary-export-file-name",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Enforce semantic naming alignment: a file with a single primary export must be named after that export.",
    },
    schema: [],
    messages: {
      primaryExportMismatch:
        "Module stem '{{stem}}' does not match its primary export '{{name}}' — rename the file to '{{expected}}{{ext}}' to describe its responsibility.",
    },
  },
  defaultOptions: [],
  create(context) {
    const base = basename(context.filename);

    if (base.endsWith(".d.ts") || base.startsWith("index.") || base.startsWith("_")) return {};
    if (isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) return {};

    const stem = stemOf(base);
    // Skip framework routes like page.tsx, layout.tsx, route.ts, $id.tsx, [id].tsx and convention stems
    if (
      stem === "page" ||
      stem === "layout" ||
      stem === "loading" ||
      stem === "error" ||
      stem === "not-found" ||
      stem === "route" ||
      stem === "__root" ||
      stem === "config" ||
      stem === "constants" ||
      stem === "types" ||
      stem.startsWith("$") ||
      stem.startsWith("[")
    ) {
      return {};
    }

    return {
      Program(node: TSESTree.Program): void {
        const primary = findPrimaryExport(node.body);
        if (primary === null) return;
        if (CONVENTIONAL_BUCKET_EXPORTS.has(primary.name) || GENERIC_ENTRYPOINTS.has(primary.name)) return;

        const expectedStem = kebabCase(primary.name);
        if (stem === expectedStem) return;

        // Ensure extension is preserved (.tsx if component/JSX or .ts)
        const ext = base.endsWith(".tsx") ? ".tsx" : ".ts";

        context.report({
          node: primary.node,
          messageId: "primaryExportMismatch",
          data: { stem, name: primary.name, expected: expectedStem, ext },
        });
      },
    };
  },
});
