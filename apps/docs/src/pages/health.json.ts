import { createHash } from 'node:crypto';
import type { APIRoute } from 'astro';

import { catalog } from '../lib/catalog';

const catalogJson = JSON.stringify(catalog);
const payload = {
  status: 'ok',
  schemaVersion: catalog.schemaVersion,
  rules: catalog.rules.length,
  catalogSha256: createHash('sha256').update(catalogJson).digest('hex'),
  commit: process.env.WORKERS_CI_COMMIT_SHA ?? process.env.GITHUB_SHA ?? 'local',
};

export const GET = (() => new Response(`${JSON.stringify(payload)}\n`, {
  headers: { 'Content-Type': 'application/json; charset=utf-8' },
})) satisfies APIRoute;
