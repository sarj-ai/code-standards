import { hash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { z } from "zod";

import type { Rule } from "./catalog";
import { ExampleSchema } from "./catalog-validation";

const DisplayRuleSchema = z.object({
  examples: z.array(ExampleSchema),
  optionsSchemaSource: z.string().nullable(),
});
const DisplayProjectionSchema = z.object({
  schemaVersion: z.literal(1),
  catalogSha256: z.string(),
  cliSha256: z.string(),
  rules: z.partialRecord(z.string(), DisplayRuleSchema),
  static: z.object({
    quickSetup: z.string(),
    runOnce: z.string(),
    bootstrap: z.string(),
    usage: z.record(z.string(), z.string()),
  }),
});
type DisplayRule = z.infer<typeof DisplayRuleSchema>;
type DisplayProjection = z.infer<typeof DisplayProjectionSchema>;

const repositoryRoot = resolve(process.cwd(), "../..");
const projectionPath = resolve(
  process.cwd(),
  "src/generated/formatted-code.v1.json",
);
const catalogPath = resolve(
  repositoryRoot,
  "packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json",
);
const cliPath = resolve(
  repositoryRoot,
  "packages/standards/src/sarj_standards/configs/cli-reference.v1.json",
);

async function readProjection(): Promise<DisplayProjection> {
  const projection = DisplayProjectionSchema.parse(JSON.parse(
    await readFile(projectionPath, "utf8"),
  ) as unknown);
  if (
    projection.catalogSha256 !== sha256(await readFile(catalogPath, "utf8"))
  ) {
    throw new Error("Formatted code projection is stale for the rule catalog.");
  }
  if (projection.cliSha256 !== sha256(await readFile(cliPath, "utf8"))) {
    throw new Error(
      "Formatted code projection is stale for the CLI reference.",
    );
  }
  return projection;
}

function sha256(source: string): string {
  return hash("sha256", source, "hex");
}

const projection = await readProjection();

export const formattedStaticCode = projection.static;

export function displayRule(rule: Rule): DisplayRule {
  const displayed = projection.rules[rule.key];
  if (displayed === undefined)
    throw new Error(`Formatted code projection is missing ${rule.key}.`);
  if (displayed.examples.length !== rule.examples.length) {
    throw new Error(
      `Formatted code projection example count differs for ${rule.key}.`,
    );
  }
  for (const [index, example] of displayed.examples.entries()) {
    const raw = rule.examples.at(index);
    if (
      raw === undefined ||
      example.id !== raw.id ||
      example.scenarioId !== raw.scenarioId ||
      example.outcome !== raw.outcome
    ) {
      throw new Error(
        `Formatted code projection topology differs for ${rule.key}.`,
      );
    }
  }
  return displayed;
}
