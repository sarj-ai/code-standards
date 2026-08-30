import type { Language } from "./catalog";

const COMPOUND_EXTENSIONS = [
  [".tftest.hcl", "terraform"],
  [".git/keep", "text"],
  [".d.ts", "typescript"],
  [".test.ts", "typescript"],
  [".spec.ts", "typescript"],
] as const;

const EXTENSION_LANGUAGES: Readonly<Record<string, string>> = Object.freeze({
  bash: "shellscript",
  cfg: "ini",
  cjs: "javascript",
  cts: "typescript",
  ini: "ini",
  js: "javascript",
  json: "json",
  jsonc: "jsonc",
  jsx: "jsx",
  md: "markdown",
  mdx: "mdx",
  mjs: "javascript",
  mts: "typescript",
  properties: "properties",
  py: "python",
  pyi: "python",
  sh: "shellscript",
  sql: "sql",
  tf: "terraform",
  tfvars: "terraform",
  toml: "toml",
  ts: "typescript",
  tsx: "tsx",
  yaml: "yaml",
  yml: "yaml",
  zsh: "shellscript",
});

const FALLBACK_LANGUAGES: Readonly<Partial<Record<Language, string>>> =
  Object.freeze({
    iac: "terraform",
    markdown: "markdown",
    python: "python",
    shell: "shellscript",
    sql: "sql",
    typescript: "typescript",
  });

export function languageForPath(
  path: string,
  fallbackLanguages: readonly Language[],
): string {
  const normalizedPath = path.toLowerCase();
  for (const [suffix, language] of COMPOUND_EXTENSIONS) {
    if (normalizedPath.endsWith(suffix)) return language;
  }
  const extension = normalizedPath.includes(".")
    ? (normalizedPath.split(".").at(-1) ?? "")
    : "";
  const mapped = EXTENSION_LANGUAGES[extension];
  if (mapped) return mapped;
  if (fallbackLanguages.length === 1)
    return FALLBACK_LANGUAGES[fallbackLanguages[0]] ?? "text";
  return "text";
}
