import type { APIRoute } from 'astro';

import { catalog } from '../../../lib/catalog';

export const GET = (() => new Response(`${JSON.stringify(catalog)}\n`, {
  headers: { 'Content-Type': 'application/json; charset=utf-8' },
})) satisfies APIRoute;
