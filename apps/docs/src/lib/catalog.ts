import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

import { sourceRevision } from "./source-revision";
import { siteHref } from "./site.ts";
import { ENGINES, validateCatalog } from "./catalog-validation";
import { ruleIntroductions } from "./rule-introductions";

export { ENGINES };
export type { Engine, DefaultLevel, Autofix, Category, Language, ExampleFile, RuleExample, Rule, Catalog } from "./catalog-validation";
import type { Engine, Rule, Catalog } from "./catalog-validation";

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
export const catalog: Catalog = validateCatalog(rawCatalog);
const sourceCounts = new Map<string, number>();
for (const rule of catalog.rules) sourceCounts.set(rule.source, (sourceCounts.get(rule.source) ?? 0) + 1);
export const introductions = await ruleIntroductions(resolve(process.cwd(), '../..'), catalog.rules.map((rule) => {
  const source = { id: rule.key, path: rule.source };
  if ((sourceCounts.get(rule.source) ?? 0) > 1) return { ...source, marker: rule.id };
  return source;
}));
export const catalogJson = `${JSON.stringify(catalog)}\n`;
export const catalogSchema = await readGeneratedJson(
  schemaPath,
  "Rule catalog schema",
);

export function engineLabel(engine: Engine): string {
  return {
    oxlint: "TypeScript",
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
