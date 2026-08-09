import type { APIRoute } from 'astro';

import { ENGINES, catalog, engineLabel } from '../lib/catalog';

const lines = [
  '# Sarj Standards',
  '',
  '> Deterministic code-quality rules and repository adoption tooling.',
  '',
  '## Reference',
  '',
  '- [CLI](https://code-standards.sarj.ai/cli/)',
  '- [All rules](https://code-standards.sarj.ai/rules/)',
  '- [Catalog JSON](https://code-standards.sarj.ai/api/v1/catalog.json)',
  '- [Catalog schema](https://code-standards.sarj.ai/api/v1/rule-catalog.schema.json)',
  '',
  '## Rule families',
  '',
  ...ENGINES.filter((engine) => catalog.rules.some((rule) => rule.engine === engine)).map(
    (engine) => `- [${engineLabel(engine)}](https://code-standards.sarj.ai/rules/${engine}/)`,
  ),
  '',
  'A complete text rendering is available at https://code-standards.sarj.ai/llms-full.txt',
  '',
];

export const GET = (() => new Response(lines.join('\n'), {
  headers: { 'Content-Type': 'text/plain; charset=utf-8' },
})) satisfies APIRoute;
