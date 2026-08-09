import type { APIRoute } from 'astro';

import { catalog } from '../lib/catalog';

const lines = [
  '# Sarj Standards rule catalog',
  '',
  ...catalog.rules.flatMap((rule) => [
    `## ${rule.key}`,
    '',
    rule.summary,
    '',
    `Category: ${rule.category}. Default: ${rule.defaultLevel}. Autofix: ${rule.autofix}.`,
    '',
    `Rationale: ${rule.rationale}`,
    '',
    `Remediation: ${rule.remediation}`,
    '',
    `Reference: https://code-standards.sarj.ai/rules/${rule.engine}/${rule.id}/`,
    '',
  ]),
];

export const GET = (() => new Response(lines.join('\n'), {
  headers: { 'Content-Type': 'text/plain; charset=utf-8' },
})) satisfies APIRoute;
