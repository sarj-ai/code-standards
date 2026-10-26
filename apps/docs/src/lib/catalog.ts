import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { sourceRevision } from "./source-revision";
import { siteHref } from "./site.ts";
import { ENGINES, validateCatalog } from "./catalog-validation";

export { ENGINES };
export type Engine = (typeof ENGINES)[number];
export type DefaultLevel = "error" | "off" | "warning";
export type Autofix = "none" | "safe" | "suggestion";
export type Category =
  | "architecture"
  | "correctness"
  | "maintainability"
  | "performance"
  | "security"
  | "style"
  | "testing";
export type Language =
  "config" | "iac" | "markdown" | "python" | "shell" | "sql" | "typescript";

export interface ExampleFile {
  path: string;
  source: string;
}

export interface RuleExample {
  id: string;
  scenarioId: string;
  title: string;
  outcome: "accept" | "reject";
  focusPath: string;
  expectedCount: number;
  files: ExampleFile[];
  fixedFiles: ExampleFile[];
}

export interface Rule {
  key: string;
  engine: Engine;
  id: string;
  code: string | null;
  summary: string;
  rationale: string;
  remediation: string;
  category: Category;
  languages: Language[];
  defaultLevel: DefaultLevel;
  autofix: Autofix;
  status: "active";
  aliases: string[];
  limitations: string[];
  filePatterns: string[];
  messageIds: string[];
  optionsSchema: Record<string, unknown> | null;
  references: string[];
  since: string | null;
  source: string;
  test: string;
  examples: RuleExample[];
}

export interface Catalog {
  schemaVersion: 1;
  rules: Rule[];
}

const catalogPath = resolve(
  process.cwd(),
  "../../packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json",
);
const schemaPath = resolve(
  process.cwd(),
  "../../packages/standards/src/sarj_standards/schemas/rule-catalog.v1.schema.json",
);

async function readGeneratedJson(
  path: string,
  label: string,
): Promise<unknown> {
  let source: string;
  try {
    source = await readFile(path, "utf8");
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") {
      throw new Error(
        `${label} is missing at ${path}. Generate the repository catalog before building apps/docs.`,
        { cause: error },
      );
    }
    throw error;
  }
  try {
    return JSON.parse(source) as unknown;
  } catch (error) {
    throw new Error(`${label} is not valid JSON at ${path}.`, { cause: error });
  }
}

const rawCatalog = await readGeneratedJson(
  catalogPath,
  "Generated rule catalog",
);
validateCatalog(rawCatalog);

export const catalog: Catalog = rawCatalog;
export const catalogJson = `${JSON.stringify(catalog)}\n`;
export const catalogSchema = await readGeneratedJson(
  schemaPath,
  "Rule catalog schema",
);

export function engineLabel(engine: Engine): string {
  return {
    eslint: "TypeScript",
    iac: "IaC",
    python: "Python",
    sql: "SQL",
    text: "Text",
  }[engine];
}

export function ruleHref(rule: Pick<Rule, "engine" | "id">): string {
  return siteHref(`/rules/${rule.engine}/${rule.id}/`);
}

export function rulesForEngine(engine: Engine): Rule[] {
  return catalog.rules.filter((rule) => rule.engine === engine);
}

export function sourceUrl(path: string): string {
  return `https://github.com/sarj-ai/code-standards/blob/${sourceRevision}/${path.split("/").map(encodeURIComponent).join("/")}`;
}
