import type { OxfmtConfig } from "oxfmt";

// Managed by code-standards. Keep repository style, ignores and overrides in oxfmt.config.mts.
// Style options come from the repository so adopting oxfmt does not reformat code; this file
// carries only the shared policy: which file types oxfmt owns and which files it never touches.

/** Every file extension oxfmt formats. */
export const formatExtensions = Object.freeze([
  "cjs",
  "css",
  "cts",
  "gql",
  "graphql",
  "gs",
  "handlebars",
  "hbs",
  "htm",
  "html",
  "js",
  "json",
  "json5",
  "jsonc",
  "jsx",
  "less",
  "markdown",
  "md",
  "mdx",
  "mjs",
  "mts",
  "pcss",
  "scss",
  "toml",
  "ts",
  "tsx",
  "vue",
  "yaml",
  "yml",
] as const);

export type FormatExtension = (typeof formatExtensions)[number];

// Standards writes these files; reformatting them would fight the generator or the sync check.
const managedFiles = Object.freeze([
  ".basedpyright-strict.json",
  ".checkov.yml",
  ".github/workflows/commit-policy.yml",
  ".github/workflows/standards.yml",
  ".markdownlint.yaml",
  ".pyright-strict.json",
  ".repo-standards/baseline.json",
  ".ruff-strict.toml",
  ".sarj-standards.toml",
  ".swiftlint.yml",
  ".taplo.toml",
  ".yamllint.yaml",
  "config/detekt/detekt.yml",
  "diagnostic-baseline.json",
  "doctor.config.json",
  "mobile-tools.versions.json",
  "oxfmt.strict.mts",
  "oxlint-suppressions.json",
  "oxlint.strict.mts",
  "pyright.strict.json",
  "syncpack.strict.mts",
  "zizmor.yml",
]);

export interface FormatPolicy extends OxfmtConfig {
  /** Extensions the repository's previous formatter covered; oxfmt ignores the rest. */
  readonly extensions?: readonly FormatExtension[];
}

export function createConfig({
  extensions = formatExtensions,
  ignorePatterns = [],
  ...style
}: FormatPolicy = {}): OxfmtConfig {
  const skipped = formatExtensions.filter((extension) => !extensions.includes(extension));
  const unowned = skipped.length === 1 ? `**/*.${skipped[0]}` : `**/*.{${skipped.join(",")}}`;
  const scope = skipped.length === 0 ? [] : [unowned];
  return { ...style, ignorePatterns: [...managedFiles, ...scope, ...ignorePatterns] };
}

export default createConfig();
