// vitest: shared-module-graph
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_COMMENT_CRUFT_DOCUMENTATION } from "../../src/rules/no-comment-cruft.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester();

RULE_TESTER.run("no-comment-cruft", rule, {
  valid: [

    {
      code: "const x = 1;\n// region, sector AND facility_type are HARD constraints when the investor names them\nconst y = 2;",
    },
    { code: "const x = 1;\n// region is derived from the caller's IP, which the CDN rewrites\nconst y = 2;" },
    { code: "const x = 1;\n// region defaults to us-east-1\nconst y = 2;" },
    { code: "const x = 1;\n// region comes from tenant\nconst y = 2;" },
    { code: "const x = 1;\n// regions are resolved lazily\nconst y = 2;" },
    {
      name: "preserves region titles longer than five words",
      code: "const x = 1;\n// region one two three four five six\nconst y = 2;",
    },

    { code: "const x = 1;\n// Region centroids for map_pan.\nconst y = 2;" },

    { code: "// EN-only for now; add an AR variant once AR audio exists (PROJ-249)\nconst langs = ['en'];" },
    { code: "// hacky — mirrors https://example.com/api/quirk until they fix it\nconst x = 1;" },

    {
      code: "// Stripe returns a stale timestamp, so the sink writes a field to advance it.\n// EN-only for now (PROJ-249).\nconst config = load();",
    },


    { code: "export const names = [\n  'a',\n  // config\n  'b',\n];" },

    { code: "const city = 1;\n// Riyadh\nconst y = 2;" },
    { code: "const x = 1;\n// idempotent\nconst y = 2;" },

    { code: "const x = 1;\n// lets a same-day re-run find the message it already posted\nconst y = 2;" },
    { code: "const x = 1;\n// Lets describeAppointmentWithUser skip the extra round-trip\nconst y = 2;" },

    {
      code: "// 1. Load the config\nconst c = load();\n// 2. Reconcile the rows\nconst r = reconcile(c);\n// 3. Emit\nemit(r);",
    },

    { code: "const x = 1;\n// sarj-noqa: SARJ016 — deliberate\nconst y = 2;" },


    {
      code: "const el = <div>\n  {/* Step 1: Select Patient */}\n  <Picker />\n</div>;",
      filename: "wizard.tsx",
    },

    { code: "// retry because the upstream API is flaky\nconst x = retry();" },

    { code: "const x = compute(); // cached when warm" },
    { code: "const placeholder = 'implementation omitted';" },
    { code: "// placeholder color is required by the design system\nconst color = token();" },
    { code: "// in a real implementation this changes; see PROJ-123\nconst value = fallback();" },
    { code: "// in a real application, rotate this key before deployment\nconst key = loadKey();" },
    { code: "// for demonstration purposes only; never use this key in production\nconst key = loadKey();" },
    { code: "// the pool is process-wide in a real application\nconst pool = createPool();" },
    { code: "// same as above, but input must be converted to a string\nconst value = convert();" },
    { code: "// the placeholder implementation preserves ABI compatibility\nconst value = fallback();" },
    { code: "// in a real implementation this would call the API, but offline mode avoids the network\nconst value = fallback();" },

    {
      code: "/**\n * @fileoverview does a thing\n * with detail\n * across lines\n * and more\n */\nexport const x = 1;",
    },

    { code: "// TODO@example-owner(JIRA-1234): return cachedValue();\nconst x = 1;" },
    { code: "// prettier-ignore\nconst x = 1;" },
    {
      name: "preserves tool directives",
      code: "// eslint-disable-next-line\n// =====\n// @ts-expect-error -- fixture\n// biome-ignore lint: fixture\n// c8 ignore next\nconst x = 1;",
    },

    { code: "// the entrypoint\nimport x from 'y';" },

    { code: "// 0=Monday … 6=Sunday — matches Python's WeekDay IntEnum\nexport const days = 1;" },
    { code: "// if x === y the cache is warm\nconst x = 1;" },
    { code: "// returns true => proceed\nconst ok = true;" },

    { code: "// count = number of items in the cart\nconst total = 1;" },
    { code: "// const count = number of items in the cart\nconst total = 1;" },
    { code: "// delta = new value minus old value\nconst d = 1;" },
    {
      name: "preserves prose assignments with explanatory parentheticals",
      code: "// baseline = the least valuable allowed use (what the land yields untouched)\nconst baseline = chooseBaseline();",
    },
    {
      name: "preserves request-response contracts containing assignments and arrows",
      code: "export const runtime = 'nodejs';\n// POST /api/concierge { message, reset? }\n//\n// reset=true -> POST {base}/session/reset/{id} -> {ok:true}\n// otherwise -> POST {base}/chat/{id} -> {text, cards}\nexport async function POST() {}",
    },

    {
      code: "// Copyright 2023 Acme, Inc.\n// Licensed under the Apache License 2.0.\n// You may not use this file except in compliance.\n// See the License for details.\nimport x from 'y';",
    },

    {
      code: "/*---------------------------------------------------------------------------------------------\n *  Copyright (c) Microsoft Corporation. All rights reserved.\n *  Licensed under the MIT License. See License.txt in the project root for license information.\n *--------------------------------------------------------------------------------------------*/\nimport x from 'y';",
    },

    {
      code: "// For example:\n// var o = {…};\nconst x = 1;",
    },
    {
      name: "preserves call-shape labels with multiplier pseudocode",
      code: "// app.use(path, handler x5)\nnew Hono().use(path, a, b, c, d, e);",
    },
    {
      name: "preserves the unnumbered first case in a test call matrix",
      filename: "router.test.ts",
      code: "// app.use(path, handler)\nnew Hono().use(path, a);\n// app.use(path, handler x2)\nnew Hono().use(path, a, b);",
    },
    {
      name: "preserves assertion examples with an illustration lead-in",
      code: "// For example:\n// expectTypeOf(result).toEqualTypeOf<{ callback: () => void }>();\nconst x = run();",
    },

    {
      code: "const x = 1;\n// obj.value = %sent%;\nconst y = 2;",
    },

    {
      code: '/// <reference types="node" />\nimport x from "y";',
    },

    { code: "// firstName is required by the upstream API\nconst x = 1;" },
    { code: "// now-deprecated path kept for back-compat\nconst x = 1;" },

    {
      code: "// This module wires the thing.\n// It is old.\n// Be careful.\n// Ask first.\nimport x from 'y';",
    },
    {
      code: "// Idempotency substrate: every write derives a deterministic key.\n// The key is a UUIDv5 over (tenant, resource, epoch).\n// See RFC 9562 section 5.7 for the namespace derivation.\n// No state is kept here; a replay recomputes the same key.\nexport const x = 1;",
    },


    {
      code: "// generated with @7nohe/openapi-react-query-codegen\n// ---- Queries ----\nexport const x = 1;",
      filename: "/repo/src/openapi-gen/queries.ts",
    },


    { code: NO_COMMENT_CRUFT_DOCUMENTATION.examples[0].files[0].source },
    { code: "// guard the race described in PLT-812\nlocked = true;" },

    {
      code: "// retry because the upstream rate-limits us at 10 rps\nconst result = retry(fn);",
    },

    { code: "// counter tracks retries\ncounter += 1;" },


    {
      code: "// validate coordinates\nconst points = extractPoints(feature.geometry.coordinates);",
    },

    { code: "// merge all enrichments\nconst combined = {\n  a: 1,\n  b: 2,\n};" },

    { code: "// create the session\n\nconst session = createSession();" },

    { code: "// count tiles\nlet tileCount = 0;" },

    { code: "// create the model\nfunction createModel() { return 1; }" },

    { code: "// initialize\ninitialize();" },

    {
      code: "const x = 1;\n//   req1------------------>res1        (current one)\n//        req2---------------->res2\nconst y = 2;",
    },
    { code: "const x = 1;\n//   mutate-------...---------->\nconst y = 2;" },

    {
      code: "// 1. get all tags sorted by creation date\n// 2. get all commits between current and last tag\n// 3. check if commit is a PR and get the number\n// 4. comment on PRs with the release version\nimport semver from 'semver';",
    },

    {
      code: "// First, make sure to install dependencies and build React Router. From the root of\n// the project, run this:\n//\n//    pnpm install\nconst x = 1;",
    },
    {
      code: "// createElement on it.  Patching here as a quick fix and hoping it's no longer\n// an issue in Vite.\nconst x = 1;",
    },

    {
      code: "// Needed for now since router.fetch is not async until v7\nawait wait(10);",
    },

    {
      code: "// Example:\n//\n// <Routes>\n//   <Route path=\"blog\" element={<Blog />} />\n// </Routes>\n//\n// function Blog() {\n//   return null;\n// }\nconst x = 1;",
    },


    {
      code: "function useBreakpoint() {\n  const handleChange = () => {};\n  // Set initial value\n  handleChange();\n}",
    },
    {
      code: "// Get access token\nconst urlParams = new URLSearchParams({\n  grant_type: 'authorization_code',\n});",
    },

    {
      code: "// First, warm the cache so we do not pay the cold read twice\nwarm();",
    },
    {
      code: "const a = 1;\n\n// we only cache default group pages for now so we need to invalidate them\nconst paths = [];",
    },

    {
      code: "export interface HandlerInterface {\n  // app.get(path, handler x5)\n  <P extends string>(path: P, handler: H): void;\n}",
    },
    { code: "type Router = {\n  // app.use(middleware)\n  use(m: M): void;\n};" },



    {
      code: "class C {\n  /**\n   * HANDLERS\n   * Kept in one table so the router stays readable.\n   */\n  a() { return 1; }\n}",
    },

    { code: "class C {\n  /** DOES NOT RETRY */\n  a() { return 1; }\n}" },


    { code: "interface T {\n  /** UTC */\n  at: string;\n}" },
    {
      name: "preserves protected JSDoc warnings",
      code: "class C {\n  /** DEPRECATED PUBLIC API */\n  a() { return 1; }\n}",
    },
    {
      name: "preserves a JSDoc todo linked to an issue",
      code: "/** @todo Replace this after PLT-812. */\nfunction charge() {}",
    },
    {
      name: "preserves numbered standards in JSDoc",
      code: "interface T {\n  /** ISO 8601 */\n  at: string;\n}",
    },

    { code: "class C {\n  /** ALWAYS RUN THIS BEFORE THE SEED STEP */\n  a() { return 1; }\n}" },

    { code: "const a = 1; /** HELPERS */" },


    { code: "interface T {\n  /** the retry budget */\n  retries: number;\n}" },

    { code: "/**\n *\n */\nconst x = 1;" },


    {
      code: "// our svg icons break if we use data urls, so disable inline assets for now\nconst assetsInlineLimit = 0;",
    },
    {
      code: "// skipping utils for now, as it has independent release process\nconst PACKAGES = ['common'];",
    },
    {
      code: "// We only expose the jest compatible API for now\nexport interface Assertion { a: string }",
    },
    {
      code: "// Intentionally disable package cache for now as consumers do not need it\nconst opts = { packageCache: undefined };",
    },
    {
      code: "// Hero only for now; the release feed lands below it as its port arrives.\nexport function ReleasesPage() { return null; }",
    },
    {
      name: "preserves for-now notes with three content words",
      code: "// track release panels for now\nconst tracked = panels;",
    },

    {
      code: "function build() {\n  // Fetch all users into the users collection\n  const users = fetchUsers();\n  const valid = validateUsers(users);\n  const sorted = sortUsers(valid);\n  // Return the sorted users from this operation\n  return sorted;\n}",
    },

    {
      code: "function build() {\n  // Fetch all users into the users collection\n  const users = fetchUsers();\n  // Keep validation here because upstream accepts partial rows\n  const valid = validateUsers(users);\n  // Sort all valid users into the sorted users collection\n  const sorted = sortUsers(valid);\n  // Preserve this order so retries remain idempotent\n  return sorted;\n}",
    },
    {
      name: "requires comments on at least sixty percent of a wall span",
      code: "function build() {\n  // Fetch all users into the users collection\n  const users = fetchUsers();\n  const untouched = 1;\n  // Validate source users into valid users staging collection\n  const validUsers = validateUsers(users);\n  const alsoUntouched = 2;\n  // Sort valid users into sorted users queue archive\n  const sortedUsers = sortUsers(validUsers);\n  const finalUntouched = 3;\n  // Return sorted users from operation archive\n  return sortedUsers;\n}",
    },
    {
      name: "requires three quarters of attached comments to be weak",
      code: "function build() {\n  // Fetch all users into the users collection\n  const users = fetchUsers();\n  // Keep validation here because upstream accepts partial rows\n  const validUsers = validateUsers(users);\n  // Sort valid users into sorted users\n  const sortedUsers = sortUsers(validUsers);\n  // Preserve this order so retries remain idempotent\n  return sortedUsers;\n}",
    },
  ],
  invalid: [
    ...["\n", "\r\n"].map(ending => ({
      name: "shared guarded deletion retains normal terminators " + JSON.stringify(ending),
      code: "const value = 1;\n// =================\n// -----------------\nconst next = 2;".replaceAll("\n", ending),
      output: "const value = 1;\n\n\nconst next = 2;".replaceAll("\n", ending),
      errors: [{ messageId: "sectionBanner" as const }],
    })),
    { name: "removes a punctuation-only banner run in one pass", code: "const value = 1;\n// =================\n// -----------------\nconst next = 2;", output: "const value = 1;\n\n\nconst next = 2;", errors: [{ messageId: "sectionBanner" }] },

    {
      code: "class C {\n  /**\n   * REMOVE METHODS\n   */\n  remove() { return 1; }\n}",
      errors: [{ messageId: "sectionBanner" }],
    },
    {
      code: "const x = 1;\n/** Helpers */\nfunction help() { return 1; }",
      errors: [{ messageId: "sectionBanner" }],
    },
    {
      code: "const x = 1;\n/**\n * ----------------\n */\nconst y = 2;", output: "const x = 1;\n\n\n\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },
    {
      code: "const x = 1;\n/** CART START */\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },

    {
      code: "const x = 1;\n// region helpers\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },
    {
      name: "flags region titles containing five words",
      code: "const x = 1;\n// region one two three four five\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },
    {
      code: "const x = 1;\n// endregion\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },

    {
      code: "const x = 1;\n// \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },

    {
      code: "const x = 1;\n// Types\ntype Foo = { a: number };",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "const x = 1;\n// Helpers\nfunction h() { return 1; }",
      errors: [{ messageId: "redundantNarration" }],
    },

    {
      code: "const x = 1;\n// Helper function to check if a path is active\nfunction isActive(p) { return p; }",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "const x = 1;\n// Helper component for header with tooltip\nfunction Header() { return null; }",
      errors: [{ messageId: "redundantNarration" }],
    },

    {
      code: "const x = 1;\n// Let's not await the promise\nvoid run();",
      errors: [{ messageId: "redundantNarration" }],
    },

    {
      code: "const x = 1;\n// 1. Load the config\nconst c = load();",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "const x = 1;\n// Phase 2: reconcile\nreconcile();",
      errors: [{ messageId: "redundantNarration" }],
    },

    {
      code: "const x = 1;\n/* const a = 1; */\nconst y = 2;",
      errors: [{ messageId: "commentedOutCode" }],
    },
    {
      code: "const x = 1;\n/* ================= */\nconst y = 2;", output: "const x = 1;\n\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },
    {
      name: "flags decorative JSX comments while preserving ordinary JSX labels",
      code: "const el = <div>\n  {/* ============= B. Money on the table ============= */}\n  <Panel />\n</div>;",
      filename: "panel.tsx",
      errors: [{ messageId: "sectionBanner" }],
    },


    {
      code: "const x = 1;\n// ---------- Checks ----------\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },


    {
      code: "// 1.\n// 2.\n// 3.\n// 4.\nimport x from 'y';",
      errors: [{ messageId: "fileHeaderPreamble" }],
    },


    {
      code: "const a = 1;\n\n// quick fix for now\nconst limit = 10;",
      errors: [{ messageId: "redundantNarration" }],
    },

    {
      code: "const x = 1;\n\n// const a = 1;\nconst y = 2;",
      errors: [{ messageId: "commentedOutCode" }],
    },
    {
      name: "flags a semicolonless commented-out declaration",
      code: "const x = 1;\n// const stale = cachedValue\nconst y = 2;",
      errors: [{ messageId: "commentedOutCode" }],
    },
    {
      name: "flags an untracked JSDoc todo tag",
      code: "/** @todo Replace this later. */\nfunction charge() {}",
      errors: [{ messageId: "untrackedTodo" }],
    },
    {
      name: "flags an untracked JSDoc fixme line",
      code: "/**\n * Charge the account.\n * @fixme Replace this later.\n */\nfunction charge() {}",
      errors: [{ messageId: "untrackedTodo" }],
    },


    {
      code: "// why we do this\n// increment the counter\ncounter += 1;",
      errors: [{ messageId: "redundantNarration" }],
    },

    {
      code: "// First, fetch the user\nconst u = api.getUser();",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "// Then, we map over the results\nconst r = xs.map(f);",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "// Step 2: validate the payload\nvalidate(payload);",
      errors: [{ messageId: "redundantNarration" }],
    },

    {
      code: "// this is a temporary hack that only works when x\nconst y = 1;",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "// hardcoded for now\nconst limit = 10;",
      errors: [{ messageId: "redundantNarration" }],
    },

    {
      code: "// Empty for now.\nconst cfg = {};",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "// Not needed for now\nconst handler = null;",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "// login manually for now\nconst session = null;",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      name: "flags for-now notes with two content words",
      code: "// track panels for now\nconst tracked = panels;",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "// not sure if this is the right approach\nfoo();",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "const x = 1;\n// return x + 1;\nconst y = 2;",
      errors: [{ messageId: "commentedOutCode" }],
    },
    {
      name: "flags a disabled chained assertion",
      code: "test('result', () => {\n  run();\n  // expect(response.body.data).toContain('ready');\n});",
      errors: [{ messageId: "commentedOutCode" }],
    },
    {
      name: "flags a disabled assert call",
      code: "test('result', () => {\n  run();\n  // assert.equal(response.status, 200);\n});",
      errors: [{ messageId: "commentedOutCode" }],
    },
    {
      name: "flags a disabled generic type assertion",
      code: "test('result', () => {\n  // expectTypeOf(result).toEqualTypeOf<{ ok: true }>();\n});",
      errors: [{ messageId: "commentedOutCode" }],
    },
    {
      name: "flags disabled generic assertions containing function signatures",
      code: "test('result', () => {\n  // expectTypeOf(result).toEqualTypeOf<{ callback: (value: string) => Promise<void> }>();\n});",
      errors: [{ messageId: "commentedOutCode" }],
    },
    {
      name: "flags disabled generic assertions containing call signatures",
      code: "test('result', () => {\n  // expectTypeOf(result).toEqualTypeOf<{ (value: string): boolean; readonly kind: 'predicate' }>();\n});",
      errors: [{ messageId: "commentedOutCode" }],
    },
    {
      name: "flags a long disabled assertion without regex backtracking",
      code: `test('result', () => {\n  // expect(value)${".matcher<Zero>".repeat(2_000)}();\n});`,
      errors: [{ messageId: "commentedOutCode" }],
    },
    {
      code: "// import { foo } from './bar';\nexport const x = 1;",
      errors: [{ messageId: "commentedOutCode" }],
    },

    {
      code: "const x = 1;\n// config.value = getValue();\nconst y = 2;",
      errors: [{ messageId: "commentedOutCode" }],
    },
    {
      code: "const x = 1;\n// =====================\nconst y = 2;", output: "const x = 1;\n\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },
    {
      code: "const x = 1;\n// #region helpers\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },

    {
      code: "// helpers\n// utils\n// misc\n// stuff\nimport x from 'y';",
      errors: [{ messageId: "fileHeaderPreamble" }],
    },

    {
      code: "const x = 1;\n// const a = 1;\n// const b = 2;\nconst y = 2;",
      errors: [{ messageId: "commentedOutCode" }],
    },
    {
      name: "coalesces the borders of one line-comment banner",
      code: "const x = 1;\n// ----------------\n// HANDLERS\n// ----------------\nconst y = 2;", output: "const x = 1;\n\n// HANDLERS\n\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },
    {
      name: "coalesces a contiguous disabled implementation",
      code: "async function call() {\n  // const response = await fetch(url, {\n  //   method: 'POST',\n  // });\n  // if (!response.ok) {\n  //   throw new Error(await response.text());\n  // }\n}",
      errors: [{ messageId: "commentedOutCode" }],
    },

    {
      code: "const x = 1;\n// ==== SECTION ====\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },

    {
      code: NO_COMMENT_CRUFT_DOCUMENTATION.examples[1].files[0].source,
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "function f(user) {\n  // return the user\n  return user;\n}",
      errors: [{ messageId: "redundantNarration" }],
    },

    {
      code: "// get the case\nconst caseData = getCase(caseId);",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "// save to localStorage\nlocalStorage.setItem('app-theme', theme);",
      errors: [{ messageId: "redundantNarration" }],
    },

    {
      code: "// count tiles\nconst tileCount = tiles.length;",
      errors: [{ messageId: "redundantNarration" }],
    },

    {
      code: "// create new room\nroomId = makeRoomId(sessionId);",
      errors: [{ messageId: "redundantNarration" }],
    },

    {
      code: "// TODO: fix this later\nconst x = 1;",
      errors: [{ messageId: "untrackedTodo" }],
    },
    {
      code: "// fixme: broken\nconst y = 2;",
      errors: [{ messageId: "untrackedTodo" }],
    },

    {
      code: "// increment i\ni += 1;",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "// return the response\nreturn response;",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "// implementation omitted\nreturn fallback;",
      errors: [{ messageId: "placeholderImplementation" }],
    },
    {
      code: "// existing code here\nreturn fallback;",
      errors: [{ messageId: "placeholderImplementation" }],
    },
    {
      code: "// placeholder implementation\nreturn fallback;",
      errors: [{ messageId: "placeholderImplementation" }],
    },
    {
      code: "/* implementation omitted */\nreturn fallback;",
      errors: [{ messageId: "placeholderImplementation" }],
    },
    {
      code: "// in a real implementation this would call the API\nreturn true;",
      errors: [{ messageId: "placeholderImplementation" }],
    },
    {
      code: "// Generated by Claude\n// DO NOT EDIT\n\n// implementation omitted\nreturn true;",
      errors: [{ messageId: "placeholderImplementation" }],
    },

    {
      code: "// Set mobile viewport\nawait page.setViewportSize(MOBILE_VIEWPORT);",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "function digest(hmac) {\n  // Return hex digest\n  return hmac.digest('hex');\n}",
      errors: [{ messageId: "redundantNarration" }],
    },


    {
      code: "// First, verify the key exists\nverifyKey(keyId);",
      errors: [{ messageId: "redundantNarration" }],
    },


    {
      code: "export interface Routes {\n  // const a = 1;\n  get(path: string): void;\n}",
      errors: [{ messageId: "commentedOutCode" }],
    },


    {
      code: "namespace N {\n  // drop(table);\n  export const x = 1;\n}",
      errors: [{ messageId: "commentedOutCode" }],
    },


    {
      code: "function build() {\n  // Fetch users\n  const users = fetchUsers();\n  // Validate users\n  const validUsers = validateUsers(users);\n  // Sort valid users\n  const sortedUsers = sortUsers(validUsers);\n  // Return sorted users\n  return sortedUsers;\n}",
      errors: [{ messageId: "commentWall", data: { count: "4" } }],
    },
    {
      code: "function build() {\n  const untouched = 1;\n  const alsoUntouched = 2;\n  // Step 1: Fetches users\n  const users = fetchUsers(\n    source,\n  );\n  // Step 2: Validates users\n  const validUsers = validateUsers(\n    users,\n  );\n  // Step 3: Sorts valid users\n  const sortedUsers = sortUsers(\n    validUsers,\n  );\n  // Step 4: Returns sorted users\n  return (\n    sortedUsers\n  );\n  void untouched;\n  void alsoUntouched;\n}",
      errors: [{ messageId: "commentWall", data: { count: "4" } }],
    },
    {
      name: "flags three weak comments covering sixty percent of five statements",
      code: "function build() {\n  // Fetch all users into the users collection\n  const users = fetchUsers();\n  const untouched = 1;\n  // Validate users into valid users\n  const validUsers = validateUsers(users);\n  const alsoUntouched = 2;\n  // Return valid users from operation\n  return validUsers;\n}",
      errors: [{ messageId: "commentWall", data: { count: "3" } }],
    },
    {
      name: "flags walls with exactly three quarters weak comments",
      code: "function build() {\n  // Fetch all users into the users collection\n  const users = fetchUsers();\n  // Validate users into valid users\n  const validUsers = validateUsers(users);\n  // Sort valid users into sorted users\n  const sortedUsers = sortUsers(validUsers);\n  // Preserve this order because retries must be stable\n  return sortedUsers;\n}",
      errors: [{ messageId: "commentWall", data: { count: "3" } }],
    },
  ],
});
