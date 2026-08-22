import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import type { Rule, RuleExample } from './catalog';

interface DisplayRule {
  examples: RuleExample[];
  optionsSchemaSource: string | null;
}

interface DisplayProjection {
  schemaVersion: 1;
  catalogSha256: string;
  cliSha256: string;
  rules: Partial<Record<string, DisplayRule>>;
  static: {
    quickSetup: string;
    runOnce: string;
    bootstrap: string;
    usage: Record<string, string>;
  };
}

const repositoryRoot = resolve(process.cwd(), '../..');
const projectionPath = resolve(process.cwd(), 'src/generated/formatted-code.v1.json');
const catalogPath = resolve(
  repositoryRoot,
  'packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json',
);
const cliPath = resolve(
  repositoryRoot,
  'packages/standards/src/sarj_standards/configs/cli-reference.v1.json',
);

// eslint-disable-next-line @sarj/stepdown -- hashing is a local implementation detail of projection loading.
function sha256(source: string): string {
  return createHash('sha256').update(source).digest('hex');
}

function readProjection(): DisplayProjection {
  const projection = JSON.parse(readFileSync(projectionPath, 'utf8')) as DisplayProjection;
  if (projection.catalogSha256 !== sha256(readFileSync(catalogPath, 'utf8'))) {
    throw new Error('Formatted code projection is stale for the rule catalog.');
  }
  if (projection.cliSha256 !== sha256(readFileSync(cliPath, 'utf8'))) {
    throw new Error('Formatted code projection is stale for the CLI reference.');
  }
  return projection;
}

const projection = readProjection();

export const formattedStaticCode = projection.static;

export function displayRule(rule: Rule): DisplayRule {
  const displayed = projection.rules[rule.key];
  if (displayed === undefined) throw new Error(`Formatted code projection is missing ${rule.key}.`);
  if (displayed.examples.length !== rule.examples.length) {
    throw new Error(`Formatted code projection example count differs for ${rule.key}.`);
  }
  for (const [index, example] of displayed.examples.entries()) {
    const raw = rule.examples.at(index);
    if (
      raw === undefined
      || example.id !== raw.id
      || example.scenarioId !== raw.scenarioId
      || example.outcome !== raw.outcome
    ) {
      throw new Error(`Formatted code projection topology differs for ${rule.key}.`);
    }
  }
  return displayed;
}
