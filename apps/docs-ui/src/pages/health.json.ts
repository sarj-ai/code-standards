import { createHash } from 'node:crypto';
import type { APIRoute } from 'astro';

import { sourceRevision } from '../lib/build';
import { docsUiContract } from './api/v1/docs-ui.json';

const contract = `${JSON.stringify(docsUiContract)}\n`;
const payload = { status: 'ok', schemaVersion: 1, commit: sourceRevision, contractSha256: createHash('sha256').update(contract).digest('hex') };

export const GET = (() => new Response(`${JSON.stringify(payload)}\n`, {
  headers: { 'Content-Type': 'application/json; charset=utf-8' },
})) satisfies APIRoute;
