import { hash } from "node:crypto";
import type { APIRoute } from "astro";

import { sourceRevision } from "../lib/source-revision";
import { catalog, catalogJson } from "../lib/catalog";
import { cliReference } from "../lib/cli";

const payload = {
  status: "ok",
  schemaVersion: catalog.schemaVersion,
  rules: catalog.rules.length,
  catalogSha256: hash("sha256", catalogJson, "hex"),
  commit: sourceRevision,
  standardsVersion: cliReference.version,
};

export const GET = (() =>
  new Response(`${JSON.stringify(payload)}\n`, {
    headers: { "Content-Type": "application/json; charset=utf-8" },
  })) satisfies APIRoute;
