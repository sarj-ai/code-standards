import type { APIRoute } from 'astro';

import { ENGINES, catalog, engineLabel } from '../lib/catalog';
import { siteUrl } from '../lib/site.ts';

const lines = [
  '# Sarj Standards',
  '',
  '> Deterministic code-quality rules and repository adoption tooling.',
  '',
  '## Reference',
  '',
  `- [About](${siteUrl('/')})`,
  `- [CLI](${siteUrl('/cli/')})`,
  `- [All rules](${siteUrl('/rules/')})`,
  `- [Catalog JSON](${siteUrl('/api/v1/catalog.json')})`,
  `- [Catalog schema](${siteUrl('/api/v1/rule-catalog.schema.json')})`,
  '',
  '## Rule families',
  '',
  ...ENGINES.filter((engine) => catalog.rules.some((rule) => rule.engine === engine)).map(
    (engine) => `- [${engineLabel(engine)}](${siteUrl(`/rules/${engine}/`)})`,
  ),
  '',
  `A complete text rendering is available at ${siteUrl('/llms-full.txt')}`,
  '',
];

export const GET = (() => new Response(lines.join('\n'), {
  headers: { 'Content-Type': 'text/plain; charset=utf-8' },
})) satisfies APIRoute;
