import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-comment-cruft.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester();

ruleTester.run("no-comment-cruft", rule, {
  valid: [
    // Preserve prose that happens to open with "region".
    {
      code: "const x = 1;\n// region, sector AND facility_type are HARD constraints when the investor names them\nconst y = 2;",
    },
    { code: "const x = 1;\n// region is derived from the caller's IP, which the CDN rewrites\nconst y = 2;" },
    { code: "const x = 1;\n// regions are resolved lazily\nconst y = 2;" },
    {
      name: "preserves region titles longer than five words",
      code: "const x = 1;\n// region one two three four five six\nconst y = 2;",
    },
    // Sentence punctuation distinguishes prose from a region title.
    { code: "const x = 1;\n// Region centroids for map_pan.\nconst y = 2;" },
    // --- a ticket/URL turns a scoping note into an owned decision ---
    { code: "// EN-only for now; add an AR variant once AR audio exists (PROJ-249)\nconst langs = ['en'];" },
    { code: "// hacky — mirrors https://example.com/api/quirk until they fix it\nconst x = 1;" },
    // A reference on any line protects the whole contiguous run.
    {
      code: "// Stripe returns a stale timestamp, so the sink writes a field to advance it.\n// EN-only for now (PROJ-249).\nconst config = load();",
    },
    // A one-word label inside an expression groups the elements beneath it —
    // the TS twin of `# config` inside pydantic's `__all__`.
    { code: "export const names = [\n  'a',\n  // config\n  'b',\n];" },
    // --- one-word comments outside the section-label vocabulary ---
    { code: "const city = 1;\n// Riyadh\nconst y = 2;" },
    { code: "const x = 1;\n// idempotent\nconst y = 2;" },
    // Third-person `lets` is a different word doing real work.
    { code: "const x = 1;\n// lets a same-day re-run find the message it already posted\nconst y = 2;" },
    { code: "const x = 1;\n// Lets describeAppointmentWithUser skip the extra round-trip\nconst y = 2;" },
    // A RUN of enumeration markers is an algorithm walkthrough, not narration.
    {
      code: "// 1. Load the config\nconst c = load();\n// 2. Reconcile the rows\nconst r = reconcile(c);\n// 3. Emit\nemit(r);",
    },
    // `sarj-noqa` is a directive, not prose.
    { code: "const x = 1;\n// sarj-noqa: SARJ016 — deliberate\nconst y = 2;" },
    // JSX-expression comments are categorically exempt: `{/* Step 1: Select
    // Patient */}` mirrors the literal step labels a wizard renders.
    {
      code: "const el = <div>\n  {/* Step 1: Select Patient */}\n  <Picker />\n</div>;",
      filename: "wizard.tsx",
    },
    // Prose "why" comment is the legitimate use.
    { code: "// retry because the upstream API is flaky\nconst x = retry();" },
    // Trailing explanatory comment.
    { code: "const x = compute(); // cached when warm" },
    // JSDoc / @fileoverview headers are never flagged.
    {
      code: "/**\n * @fileoverview does a thing\n * with detail\n * across lines\n * and more\n */\nexport const x = 1;",
    },
    // Directive comments are ignored (TODO/FIXME carry an owner elsewhere).
    { code: "// TODO@nmaswood(JIRA-1234): return cachedValue();\nconst x = 1;" },
    { code: "// prettier-ignore\nconst x = 1;" },
    {
      name: "preserves tool directives",
      code: "// eslint-disable-next-line\n// =====\n// @ts-expect-error -- fixture\n// biome-ignore lint: fixture\n// c8 ignore next\nconst x = 1;",
    },
    // A short leading comment block (< 4 lines) is fine.
    { code: "// the entrypoint\nimport x from 'y';" },
    // Prose with `key=value` / comparisons is not commented-out code.
    { code: "// 0=Monday … 6=Sunday — matches Python's WeekDay IntEnum\nexport const days = 1;" },
    { code: "// if x === y the cache is warm\nconst x = 1;" },
    { code: "// returns true => proceed\nconst ok = true;" },
    // Prose `word = phrase` with no code-tail is not commented-out code.
    { code: "// count = number of items in the cart\nconst total = 1;" },
    { code: "// delta = new value minus old value\nconst d = 1;" },
    // License header preamble is exempt.
    {
      code: "// Copyright 2023 Acme, Inc.\n// Licensed under the Apache License 2.0.\n// You may not use this file except in compliance.\n// See the License for details.\nimport x from 'y';",
    },
    // Block-comment MIT license banner (dashed rule) is exempt.
    {
      code: "/*---------------------------------------------------------------------------------------------\n *  Copyright (c) Microsoft Corporation. All rights reserved.\n *  Licensed under the MIT License. See License.txt in the project root for license information.\n *--------------------------------------------------------------------------------------------*/\nimport x from 'y';",
    },
    // Code-shaped line under a prose lead-in is an illustration, not dead code.
    {
      code: "// For example:\n// var o = {…};\nconst x = 1;",
    },
    // Pseudo-code placeholder line is not commented-out code.
    {
      code: "const x = 1;\n// obj.value = %sent%;\nconst y = 2;",
    },
    // Triple-slash TS reference directive is a directive, not a preamble.
    {
      code: '/// <reference types="node" />\nimport x from "y";',
    },
    // A genuine why-comment that happens to mention a narration word is fine.
    { code: "// firstName is required by the upstream API\nconst x = 1;" },
    { code: "// now-deprecated path kept for back-compat\nconst x = 1;" },
    // A leading block containing prose is documentation, not a bare preamble.
    {
      code: "// This module wires the thing.\n// It is old.\n// Be careful.\n// Ask first.\nimport x from 'y';",
    },
    {
      code: "// Idempotency substrate: every write derives a deterministic key.\n// The key is a UUIDv5 over (tenant, resource, epoch).\n// See RFC 9562 section 5.7 for the namespace derivation.\n// No state is kept here; a replay recomputes the same key.\nexport const x = 1;",
    },
    // Generated files are template output; style/comment rules have no useful
    // author action there.
    {
      code: "// generated with @7nohe/openapi-react-query-codegen\n// ---- Queries ----\nexport const x = 1;",
      filename: "/repo/src/openapi-gen/queries.ts",
    },
    // --- "restates the next line": the guards that keep it conservative. ---
    // One unmatched word means the comment carries something the code does not.
    { code: "// increment the counter for PLT-812\ncounter += 1;" },
    { code: "// guard the race described in PLT-812\nlocked = true;" },
    // A why-comment is longer than narration and does not corroborate anyway.
    {
      code: "// retry because the upstream rate-limits us at 10 rps\nconst result = retry(fn);",
    },
    // The opener must be a narration verb, not a noun that shares its spelling.
    { code: "// counter tracks retries\ncounter += 1;" },
    // Overlap that lives only in an argument is coincidental — the statement
    // extracts points, the validation the comment names happens further down.
    {
      code: "// validate coordinates\nconst points = extractPoints(feature.geometry.coordinates);",
    },
    // A comment above a multi-line statement labels a region, not one line.
    { code: "// merge all enrichments\nconst combined = {\n  a: 1,\n  b: 2,\n};" },
    // A blank line means the comment heads a block, not the statement below.
    { code: "// create the session\n\nconst session = createSession();" },
    // A zero/empty seed computes nothing for the comment to restate.
    { code: "// count tiles\nlet tileCount = 0;" },
    // A declaration is documented by a comment, not narrated by it.
    { code: "// create the model\nfunction createModel() { return 1; }" },
    // Nothing left to corroborate once the opening verb is removed.
    { code: "// initialize\ninitialize();" },
    // An arrowhead distinguishes a sequence diagram from a banner.
    {
      code: "const x = 1;\n//   req1------------------>res1        (current one)\n//        req2---------------->res2\nconst y = 2;",
    },
    { code: "const x = 1;\n//   mutate-------...---------->\nconst y = 2;" },
    // Multiple numbered explanations form a walkthrough.
    {
      code: "// 1. get all tags sorted by creation date\n// 2. get all commits between current and last tag\n// 3. check if commit is a PR and get the number\n// 4. comment on PRs with the release version\nimport semver from 'semver';",
    },
    // A phrase inside a prose paragraph is not a standalone narration label.
    {
      code: "// First, make sure to install dependencies and build React Router. From the root of\n// the project, run this:\n//\n//    pnpm install\nconst x = 1;",
    },
    {
      code: "// createElement on it.  Patching here as a quick fix and hoping it's no longer\n// an issue in Vite.\nconst x = 1;",
    },
    // A `for now` note with a stated reason is useful rationale.
    {
      code: "// Needed for now since router.fetch is not async until v7\nawait wait(10);",
    },
    // An illustration lead-in protects the entire contiguous example.
    {
      code: "// Example:\n//\n// <Routes>\n//   <Route path=\"blog\" element={<Blog />} />\n// </Routes>\n//\n// function Blog() {\n//   return null;\n// }\nconst x = 1;",
    },

    // A short translation must be corroborated by the statement below.
    {
      code: "function useBreakpoint() {\n  const handleChange = () => {};\n  // Set initial value\n  handleChange();\n}",
    },
    {
      code: "// Get access token\nconst urlParams = new URLSearchParams({\n  grant_type: 'authorization_code',\n});",
    },
    // A step marker with a reason remains documentation.
    {
      code: "// First, warm the cache so we do not pay the cold read twice\nwarm();",
    },
    {
      code: "const a = 1;\n\n// we only cache default group pages for now so we need to invalidate them\nconst paths = [];",
    },
    // A call-shaped type-member label cannot be commented-out executable code.
    {
      code: "export interface HandlerInterface {\n  // app.get(path, handler x5)\n  <P extends string>(path: P, handler: H): void;\n}",
    },
    { code: "type Router = {\n  // app.use(middleware)\n  use(m: M): void;\n};" },
    // --- a JSDoc block is still where the "why" lives ---
    // One shouted line does not make the block a signpost; the prose beneath it
    // is what the reader came for.
    {
      code: "class C {\n  /**\n   * HANDLERS\n   * Kept in one table so the router stays readable.\n   */\n  a() { return 1; }\n}",
    },
    // A shouted WARNING is protected-class prose, not a section title.
    { code: "class C {\n  /** DOES NOT RETRY */\n  a() { return 1; }\n}" },
    // One shouted word is an acronym carrying a fact the name cannot: a unit, a
    // timezone, an encoding.
    { code: "interface T {\n  /** UTC */\n  at: string;\n}" },
    {
      name: "preserves protected JSDoc warnings",
      code: "class C {\n  /** DEPRECATED PUBLIC API */\n  a() { return 1; }\n}",
    },
    {
      name: "preserves numbered standards in JSDoc",
      code: "interface T {\n  /** ISO 8601 */\n  at: string;\n}",
    },
    // A shouted SENTENCE is prose someone chose to shout.
    { code: "class C {\n  /** ALWAYS RUN THIS BEFORE THE SEED STEP */\n  a() { return 1; }\n}" },
    // Trailing, so it annotates the code beside it rather than heading a region.
    { code: "const a = 1; /** HELPERS */" },
    // A short lowercase phrase is a description of the member, not a signpost —
    // shouting is what separates the two.
    { code: "interface T {\n  /** the retry budget */\n  retries: number;\n}" },
    // An empty block says nothing, so it is not saying a section title either.
    { code: "/**\n *\n */\nconst x = 1;" },

    // `for now` is allowed when the rest of the comment carries substance.
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
    // A few annotations do not become a wall unless they cover most of a block.
    {
      code: "function build() {\n  // Fetch all users into the users collection\n  const users = fetchUsers();\n  const valid = validateUsers(users);\n  const sorted = sortUsers(valid);\n  // Return the sorted users from this operation\n  return sorted;\n}",
    },
    // Rationale and constraints are documentation, even in a heavily commented block.
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
    // Section signposts fire in every standalone comment syntax.
    {
      code: "class C {\n  /**\n   * REMOVE METHODS\n   */\n  remove() { return 1; }\n}",
      errors: [{ messageId: "sectionBanner" }],
    },
    {
      code: "const x = 1;\n/** Helpers */\nfunction help() { return 1; }",
      errors: [{ messageId: "sectionBanner" }],
    },
    {
      code: "const x = 1;\n/**\n * ----------------\n */\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },
    {
      code: "const x = 1;\n/** CART START */\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },
    // --- region marker shapes still fire ---
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
    // --- Unicode box-drawing rules are banners too ---
    {
      code: "const x = 1;\n// \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },
    // --- bare section labels ---
    {
      code: "const x = 1;\n// Types\ntype Foo = { a: number };",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "const x = 1;\n// Helpers\nfunction h() { return 1; }",
      errors: [{ messageId: "redundantNarration" }],
    },
    // --- "Helper function to …" openers ---
    {
      code: "const x = 1;\n// Helper function to check if a path is active\nfunction isActive(p) { return p; }",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "const x = 1;\n// Helper component for header with tooltip\nfunction Header() { return null; }",
      errors: [{ messageId: "redundantNarration" }],
    },
    // --- first-person-plural walkthrough voice ---
    {
      code: "const x = 1;\n// Let's not await the promise\nvoid run();",
      errors: [{ messageId: "redundantNarration" }],
    },
    // --- an ISOLATED enumeration marker is narration ---
    {
      code: "const x = 1;\n// 1. Load the config\nconst c = load();",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "const x = 1;\n// Phase 2: reconcile\nreconcile();",
      errors: [{ messageId: "redundantNarration" }],
    },
    // --- a standalone non-JSX block comment gets the banner / dead-code checks ---
    {
      code: "const x = 1;\n/* const a = 1; */\nconst y = 2;",
      errors: [{ messageId: "commentedOutCode" }],
    },
    {
      code: "const x = 1;\n/* ================= */\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },
    // --- The four guards must not become escape hatches ---------------------
    // A separator rule with no arrow head is still a banner (contrast the
    // `req---->res` diagram in `valid`).
    {
      code: "const x = 1;\n// ---------- Checks ----------\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },
    // A stack of bare labels is still a content-free preamble even though the
    // numbered-walkthrough guard exists: these carry no explanation.
    {
      code: "// 1.\n// 2.\n// 3.\n// 4.\nimport x from 'y';",
      errors: [{ messageId: "fileHeaderPreamble" }],
    },
    // A standalone one-line meta note with no rationale still fires (contrast
    // `// Needed for now since …` in `valid`).
    {
      code: "const a = 1;\n\n// quick fix for now\nconst limit = 10;",
      errors: [{ messageId: "redundantNarration" }],
    },
    // Commented-out code with no illustration lead-in above it still fires.
    {
      code: "const x = 1;\n\n// const a = 1;\nconst y = 2;",
      errors: [{ messageId: "commentedOutCode" }],
    },
    // A restatement is corroborated against the code, so it fires even inside a
    // comment block — only the phrase-matching shapes need a standalone comment.
    {
      code: "// why we do this\n// increment the counter\ncounter += 1;",
      errors: [{ messageId: "redundantNarration" }],
    },
    // Step narration — the comment walks through the code line-by-line.
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
    // Self-admitted meta-commentary — the "why later", not the why.
    {
      code: "// this is a temporary hack that only works when x\nconst y = 1;",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "// hardcoded for now\nconst limit = 10;",
      errors: [{ messageId: "redundantNarration" }],
    },
    // Content-free `for now` deferrals remain narration.
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
      code: "// import { foo } from './bar';\nexport const x = 1;",
      errors: [{ messageId: "commentedOutCode" }],
    },
    // Assignment WITH a code-tail is still commented-out code.
    {
      code: "const x = 1;\n// config.value = getValue();\nconst y = 2;",
      errors: [{ messageId: "commentedOutCode" }],
    },
    {
      code: "const x = 1;\n// =====================\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },
    {
      code: "const x = 1;\n// #region helpers\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },
    // A content-free preamble — bare labels, no sentence, nothing explained.
    {
      code: "// helpers\n// utils\n// misc\n// stuff\nimport x from 'y';",
      errors: [{ messageId: "fileHeaderPreamble" }],
    },
    // A genuine multi-line commented-out block still fires on every line.
    {
      code: "const x = 1;\n// const a = 1;\n// const b = 2;\nconst y = 2;",
      errors: [
        { messageId: "commentedOutCode" },
        { messageId: "commentedOutCode" },
      ],
    },
    // A real section banner that is NOT a license header still fires.
    {
      code: "const x = 1;\n// ==== SECTION ====\nconst y = 2;",
      errors: [{ messageId: "sectionBanner" }],
    },
    // --- "restates the next line" — the canonical redundant comment. ---
    {
      code: "// increment the counter\ncounter += 1;",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "function f(user) {\n  // return the user\n  return user;\n}",
      errors: [{ messageId: "redundantNarration" }],
    },
    // Every content word is in the statement head: target and callee.
    {
      code: "// get the case\nconst caseData = getCase(caseId);",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "// save to localStorage\nlocalStorage.setItem('app-theme', theme);",
      errors: [{ messageId: "redundantNarration" }],
    },
    // Plural folds to singular so `// count tiles` matches `tileCount`.
    {
      code: "// count tiles\nconst tileCount = tiles.length;",
      errors: [{ messageId: "redundantNarration" }],
    },
    // A bare assignment statement, not a declaration.
    {
      code: "// create new room\nroomId = makeRoomId(sessionId);",
      errors: [{ messageId: "redundantNarration" }],
    },
    // Untracked TODO/FIXME markers
    {
      code: "// TODO: fix this later\nconst x = 1;",
      errors: [{ messageId: "untrackedTodo" }],
    },
    {
      code: "// fixme: broken\nconst y = 2;",
      errors: [{ messageId: "untrackedTodo" }],
    },
    // Translation comments require full corroboration from the statement.
    {
      code: "// increment i\ni += 1;",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "// return the response\nreturn response;",
      errors: [{ messageId: "redundantNarration" }],
    },
    // Short get/set/return comments may be corroborated by call arguments.
    {
      code: "// Set mobile viewport\nawait page.setViewportSize(MOBILE_VIEWPORT);",
      errors: [{ messageId: "redundantNarration" }],
    },
    {
      code: "function digest(hmac) {\n  // Return hex digest\n  return hmac.digest('hex');\n}",
      errors: [{ messageId: "redundantNarration" }],
    },
    // Class 2: the justification escape needs a stated reason, not the mere
    // presence of the word "so" or a trailing noun phrase.
    {
      code: "// First, verify the key exists\nverifyKey(keyId);",
      errors: [{ messageId: "redundantNarration" }],
    },
    // Class 3: the suppression is scoped to the CALL branch inside a type
    // container. A commented-out declaration there is still dead code.
    {
      code: "export interface Routes {\n  // const a = 1;\n  get(path: string): void;\n}",
      errors: [{ messageId: "commentedOutCode" }],
    },
    // And a call-shaped comment in a STATEMENT position is untouched — including
    // inside a namespace body, where a statement is legal.
    {
      code: "namespace N {\n  // drop(table);\n  export const x = 1;\n}",
      errors: [{ messageId: "commentedOutCode" }],
    },
    // Repetitive AI-style walkthroughs are one block-level finding, not four
    // nearly identical line diagnostics.
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
