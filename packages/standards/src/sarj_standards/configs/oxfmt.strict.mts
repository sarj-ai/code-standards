import type { OxfmtConfig } from "oxfmt";

// Managed by code-standards. All repositories start with the same formatting
// policy. Keep repository file exclusions in oxfmt.config.mts.

const sharedStyle: OxfmtConfig = {
  printWidth: 80,
  // Quoted wire keys opt out of require-camelcase-properties.
  quoteProps: "preserve",
  sortPackageJson: false,
  sortImports: {
    groups: [
      ["side_effect", "side_effect_style"],
      ["builtin", "type-builtin"],
      ["external", "type-external"],
      ["internal", "type-internal", "subpath", "type-subpath", "unknown"],
      ["parent", "type-parent", "sibling", "type-sibling", "index", "type-index"],
    ],
    newlinesBetween: true,
  },
};

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
  return { ...sharedStyle, ...style, ignorePatterns: [...managedFiles, ...scope, ...ignorePatterns] };
}

export default createConfig();
