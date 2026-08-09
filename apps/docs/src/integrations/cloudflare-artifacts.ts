import { writeFile } from 'node:fs/promises';
import type { AstroIntegration } from 'astro';

import { catalog, ruleHref } from '../lib/catalog';

export default function cloudflareArtifacts(): AstroIntegration {
  return {
    name: 'sarj-cloudflare-static-artifacts',
    hooks: {
      'astro:build:done': async ({ dir }) => {
        const redirects = new Set<string>();
        for (const rule of catalog.rules) {
          for (const alias of rule.aliases) {
            const target = ruleHref(rule);
            redirects.add(`/rules/${rule.engine}/${alias} ${target} 301`);
            redirects.add(`/rules/${rule.engine}/${alias}/ ${target} 301`);
          }
        }
        const body = ['# Generated from rule catalog aliases. Do not edit.', ...[...redirects].sort(), ''].join('\n');
        await writeFile(new URL('_redirects', dir), body, 'utf8');
      },
    },
  };
}
