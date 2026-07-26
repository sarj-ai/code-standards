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
    // --- region markers vs prose that opens with the word "region" ---
    // demo-gateway/demos/momah-furas-anas/pipeline/matching.py:159 and five TS
    // siblings: a prose comment whose first word happens to be "region".
    {
      code: "const x = 1;\n// region, sector AND facility_type are HARD constraints when the investor names them\nconst y = 2;",
    },
    { code: "const x = 1;\n// region is derived from the caller's IP, which the CDN rewrites\nconst y = 2;" },
    { code: "const x = 1;\n// regions are resolved lazily\nconst y = 2;" },
    // A short noun phrase that would pass the title shape if a sentence-final
    // period were allowed (demo-gateway/.../voice/action/route.ts:1187).
    { code: "const x = 1;\n// Region centroids for map_pan.\nconst y = 2;" },
    // --- a ticket/URL turns a scoping note into an owned decision ---
    { code: "// EN-only for now; add an AR variant once AR audio exists (PROD-249)\nconst langs = ['en'];" },
    { code: "// hacky — mirrors https://example.com/api/quirk until they fix it\nconst x = 1;" },
    // The reference may sit on any line of the run (bulbul's Zoho canary puts it
    // last), so the whole run is exempt.
    {
      code: "// Zoho freshness canary: the sink writes Description so Modified_Time advances.\n// EN-only for now (PROD-249).\nconst config = load();",
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
    { code: "// TODO@nmaswood: return cachedValue();\nconst x = 1;" },
    { code: "// prettier-ignore\nconst x = 1;" },
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
    // C-2 regression: a long `//` module header carrying PROSE is documentation —
    // the "why" this rule's own message asks for — not cruft. On the adoption
    // codebase 11 of 15 `fileHeaderPreamble` hits were headers exactly like this.
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
    // --- ASCII sequence diagrams are documentation, not banners --------------
    // Real corpus: swr/src/index/use-swr.ts:524-549, explaining request /
    // mutation interleaving. A dash run ENDING IN AN ARROW HEAD draws a
    // timeline; it is not a section rule.
    {
      code: "const x = 1;\n//   req1------------------>res1        (current one)\n//        req2---------------->res2\nconst y = 2;",
    },
    { code: "const x = 1;\n//   mutate-------...---------->\nconst y = 2;" },
    // --- A numbered walkthrough is a file header, not a label stack ----------
    // Real corpus: react-router/scripts/release-comments.ts:1.
    {
      code: "// 1. get all tags sorted by creation date\n// 2. get all commits between current and last tag\n// 3. check if commit is a PR and get the number\n// 4. comment on PRs with the release version\nimport semver from 'semver';",
    },
    // --- A phrase inside a prose paragraph is not a narration label ----------
    // Real corpus: react-router/integration/bug-report-test.ts:26 — a six-line
    // contributor instruction whose first clause opens with "First,".
    {
      code: "// First, make sure to install dependencies and build React Router. From the root of\n// the project, run this:\n//\n//    pnpm install\nconst x = 1;",
    },
    // Real corpus:
    // react-router/packages/react-router/lib/dom/ssr/routes.tsx:663.
    {
      code: "// createElement on it.  Patching here as a quick fix and hoping it's no longer\n// an issue in Vite.\nconst x = 1;",
    },
    // --- "for now" attached to a stated reason is the why, not an excuse -----
    // Real corpus:
    // react-router/packages/react-router/__tests__/router/lazy-discovery-test.ts:2412.
    {
      code: "// Needed for now since router.fetch is not async until v7\nawait wait(10);",
    },
    // --- A code sample under its own heading is an illustration --------------
    // Real corpus: react-router/packages/react-router/lib/hooks.tsx:791, where
    // `// function Blog() {` sits nine lines below its `// Example:` heading.
    {
      code: "// Example:\n//\n// <Routes>\n//   <Route path=\"blog\" element={<Blog />} />\n// </Routes>\n//\n// function Blog() {\n//   return null;\n// }\nconst x = 1;",
    },
  ],
  invalid: [
    // --- region marker shapes still fire ---
    {
      code: "const x = 1;\n// region helpers\nconst y = 2;",
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
  ],
});
