import { createHash } from 'node:crypto';
import type { APIRoute } from 'astro';

import { sourceRevision } from '../lib/build';
import { catalog } from '../lib/catalog';
import { cliReference } from '../lib/cli';

const catalogJson = JSON.stringify(catalog);
const payload = {
  status: 'ok',
  schemaVersion: catalog.schemaVersion,
  rules: catalog.rules.length,
  catalogSha256: createHash('sha256').update(catalogJson).digest('hex'),
  commit: sourceRevision,
  standardsVersion: cliReference.version,
};

export const GET = (() => new Response(`${JSON.stringify(payload)}\n`, {
  headers: { 'Content-Type': 'application/json; charset=utf-8' },
})) satisfies APIRoute;
