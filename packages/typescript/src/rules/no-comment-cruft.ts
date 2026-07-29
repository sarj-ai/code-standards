/**
 * @fileoverview Flag comment cruft — commented-out code, section banners,
 * leading file-header comment preambles, and redundant narration. Code carries
 * the *what*; comments are reserved for the *why*. JSDoc (`/** ... *\/`) is
 * never flagged, and directive comments (`eslint-`, `@ts-`, `prettier-`,
 * `biome-`, `c8`, `<reference`, `TODO`, `FIXME`) are ignored.
 *
 * `redundantNarration` covers three shapes: step markers ("First, …", "Step 2:"),
 * self-admitted meta-commentary ("for now", "temporary hack"), and a comment
 * that restates the statement directly below it (`// increment the counter`
 * above `counter += 1`). The third shape is heavily guarded — see
 * `restatesNextLine` — because the first attempt at it (PR #98) corroborated by
 * substring and produced 933 hits at a ~60% false-positive rate. Measured on
 * 7,159 local TS/TSX files: 42 hits, 2 of them wrong (a comment heading a block
 * whose first statement happened to carry every word), and ZERO hits in the
 * maintained repos — it is a preventive ratchet with no migration cost.
 *
 * `fileHeaderPreamble` requires the preamble to contain NO prose sentence. The
 * original "4+ consecutive `//` lines before the first code" test penalised
 * syntax rather than content: on a real 42k-LOC codebase, 11 of 15 hits were the
 * repo's BEST documentation — module headers explaining a stateless idempotency
 * substrate, one citing RFC 9562 §5.7 — which is precisely the "brief doc
 * comment for the why" this rule's own message asks for. Exactly one hit was
 * genuine (an ASCII banner, already covered by `sectionBanner`). What survives
 * is the content-free preamble: a stack of bare labels/fragments with nothing
 * explained. A prose header should be a JSDoc block for tooling reasons, but
 * that is a formatting preference, not cruft, and this rule does not litigate it.
 *
 * A 2026-07 sweep of 2,186 real TypeScript files (zod, TanStack Query,
 * react-router, swr, zustand) produced 821 hits and turned up four false-positive
 * classes, each now guarded at the point that produced it — see
 * `DIAGRAM_ARROW_RE` (ASCII timelines read as banners), `ENUMERATED_ITEM_RE` (a
 * numbered walkthrough read as a content-free preamble), `isInsideCommentRun` (a
 * phrase inside a prose paragraph read as a one-line narration label), and
 * `hasIllustrationLeadInAbove` (a code sample read as commented-out code because
 * its `Example:` heading was more than one line up). The bulk of the remaining
 * hits are real: zod alone carries hundreds of lines of genuinely commented-out
 * code (e.g. zod/packages/zod/src/v4/core/checks.ts:1231-1244, a whole disabled
 * `$ZodCheckTrim` implementation), and those still fire.
 *
 * A 2026-07 corpus run of the SHIPPED rule turned up two live false positives,
 * both fixed here: `REGION_RE` matched the bare word `region`, so prose opening
 * with it read as a folding marker (six sites, e.g. `// Region centroids for
 * map_pan.`), and `for now` fired on a ticket-bearing scoping note — a comment
 * naming where the decision is recorded is doing the one thing code cannot, so
 * protected-class signal S1 now exempts narration at RUN granularity. The same
 * pass added `sarj-noqa` to `DIRECTIVE_RE` (this repo's own suppression syntax
 * was missing, so a suppression comment could itself be flagged) and four
 * detectors that are all ZERO-hit on bulbul, the repo that runs this rule at
 * `error`: bare section labels, the `Helper function to …` opener, `Let's
 * <verb>`, Unicode box-drawing banners, and an ISOLATED numbered/`Phase N:`
 * marker. JSX-expression comments stay categorically exempt: `{/* Step 1:
 * Select Patient *\/}` mirrors the literal step labels a wizard renders.
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { hasExternalReference, restatableStatementBelow, restatesStatementHead } from "./_comments.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds =
  | "commentedOutCode"
  | "sectionBanner"
  | "fileHeaderPreamble"
  | "redundantNarration"
  | "untrackedTodo";
type Options = readonly [];

const LEADING_PREAMBLE_MIN = 4;

// Step-narration lead-ins ("First, …", "Then, …", "Finally, …", "Step 2:"). A
// trailing comma/colon is required so English adverbs ("finally the invariant
// holds") aren't mistaken for an enumeration marker.
const STEP_NARRATION_RE =
  /^(?:first(?:ly)?|second(?:ly)?|third(?:ly)?|then|next|after(?:wards| that)?|finally|lastly|now)\s*[,:]\s*\S/i;

// Self-admitted meta-commentary — the "why later", not the why. `TODO`/`FIXME`/
// `HACK`/`XXX` are handled as directives (kept, with an owner, per convention).
const META_COMMENTARY_RE =
  /\b(?:for now|keeping (?:it|this) simple|could be (?:refactored|improved|cleaned up|simplified)|refactor(?:ed|ing)? (?:later|this)|not sure (?:if|whether|why|how)|quick[- ](?:and[- ]dirty|fix)|(?:a |bit of a )?hacky|is a hack|temporary (?:solution|workaround|fix|hack)|revisit (?:this|later|below)|clean (?:this|it) up|not ideal|placeholder for now)\b/i;


// `sarj-noqa` is this repo's own suppression syntax (see `rule_base.py`). It was
// missing here, so `// sarj-noqa: … — <reason>` on its own line was read as
// prose and could itself be flagged.
const DIRECTIVE_RE =
  /^(eslint\b|eslint-|sarj-noqa\b|@ts-|prettier-ignore|prettier\b|biome-|c8\b|v8\b|istanbul\b|@type\b|@vite|webpack|<reference|<amd|global\b|noinspection|hack\b|xxx\b)/i;

const LICENSE_RE =
  /copyright|licen[cs]ed?|spdx|permission is hereby granted|all rights reserved/i;

// An enumerated step in a numbered/bulleted plan: `1. get all tags`, `- read the
// manifest`. A stack of these is an algorithm walkthrough — the "why/how" the
// rule's own message asks for — even though no item ends in a full stop, which
// is why `isProse` misses it.
const ENUMERATED_ITEM_RE = /^(?:\d+[.):]|[-*•])\s+\S/;
const ENUMERATED_ITEM_MIN_WORDS = 3;
const ENUMERATED_PREAMBLE_MIN_ITEMS = 2;

const BANNER_FULL_RE = /^[\s\-=*#~_+.]{4,}$/;
// `={4,}` not `={3,}`: `===` is TS strict-equality and appears in prose comments.
// `[\u2500-\u257f]` is the Unicode box-drawing block — `────────` is the same
// section separator as `--------`, and 34 of them were sitting in the corpus
// under a check that only knew ASCII.
const BANNER_RUN_RE = /={4,}|-{4,}|#{4,}|\*{4,}|~{4,}|[\u2500-\u257f]{4,}/;

// A VS Code / Visual Studio folding marker: `//#region`, `// region helpers`,
// `// endregion`. The title must be short and unpunctuated. Matching the bare
// word alone flagged running prose that merely opens with it — six sites across
// the corpus, the clearest being
// demo-gateway/demos/momah-furas-anas/pipeline/matching.py:159 ("region, sector
// AND facility_type are HARD constraints when the investor names them — …") and
// its five TypeScript siblings. A marker *names* a region; a sentence discusses
// one, and a sentence has punctuation (a full stop included — `// Region
// centroids for map_pan.` is prose) and more than a handful of words.
const REGION_MARKER_RE = /^#?(?:end)?region\b(.*)$/i;
const REGION_TITLE_RE = /^[\s:\-\u2013\u2014]*\w[\w \-/&+]*$/;
const REGION_TITLE_MAX_WORDS = 5;

function isRegionMarker(text: string): boolean {
  const match = REGION_MARKER_RE.exec(text);
  if (match === null) return false;
  const title = (match[1] ?? "").trim();
  if (title.length === 0) return true;
  if (!REGION_TITLE_RE.test(title)) return false;
  return title.split(/\s+/).length <= REGION_TITLE_MAX_WORDS;
}

// A bare one-word signpost naming a region of the file (`// Types`, `// Main`,
// `// Helpers`). It is a table of contents for a file that should have been
// split, and it goes stale silently. 22 corpus hits, 12 of 12 sampled were true
// positives. Closed vocabulary on purpose: a one-word comment outside this list
// is far more likely to be a genuine label for a value.
const SECTION_LABEL_WORDS: ReadonlySet<string> = new Set([
  "actions", "components", "config", "configuration", "constant", "constants",
  "enums", "exports", "fixtures", "getters", "globals", "handler", "handlers",
  "helper", "helpers", "hook", "hooks", "imports", "interfaces", "main",
  "mocks", "models", "mutations", "props", "queries", "reducers", "routes",
  "schemas", "selectors", "setters", "setup", "state", "styles", "teardown",
  "type", "types", "util", "utilities", "utils",
]);
const SECTION_LABEL_RE = /^([A-Za-z]+)\s*:?\s*$/;

function isSectionLabel(text: string): boolean {
  const match = SECTION_LABEL_RE.exec(text);
  return match !== null && SECTION_LABEL_WORDS.has((match[1] ?? "").toLowerCase());
}

// "Helper function to check if a path is active" — the opener announces the
// *category* of the thing below (which its declaration already states) and then
// restates its name. 6 corpus hits, 6 true positives.
const HELPER_OPENER_RE = /^(?:a\s+)?helper\s+(?:function|method|component|hook|class|type|util(?:ity)?)\b/i;

// "Let's not await the promise" — the first-person-plural walkthrough voice.
// Gated on the narration verb list because the third-person `lets` is a
// different word doing real work: "lets a same-day re-run find the message it
// already posted" explains a mechanism and must not be touched.
const LETS_RE =
  /^let'?s\s+(?:not\s+|just\s+|now\s+|first\s+)?(?:add|append|assign|await|build|calculate|call|check|clear|close|compute|convert|copy|count|create|declare|decrement|define|delete|extract|fetch|filter|find|format|generate|get|handle|increment|init|initialise|initialize|insert|iterate|join|load|log|loop|map|merge|open|parse|print|process|push|read|remove|render|reset|return|save|send|set|setup|sort|split|start|stop|store|update|validate|wrap|write)(?:s|es|ed|ing)?\b/i;

// Enumeration markers that narrate a sequence: `// 1. Load the config`,
// `// Phase 2: reconcile`. Flagged only when the file carries exactly one — a
// *run* of them is a documented algorithm walkthrough, which is the kind of
// comment this rule exists to protect. JSX-expression comments are exempt
// wholesale (see `isStandalone`): `{/* Step 1: Select Patient */}` mirrors the
// literal step labels of a UI wizard.
const ENUMERATION_RE = /^(?:\d+[.)]\s+\S|(?:phase|step)\s+\d+\b)/i;

// Dummy translational comments: ultra-short comments that just restate the code.
const DUMMY_TRANSLATION_RE = /^(?:increment|return|returns|get|gets|set\b(?! up\b)|sets\b(?! up\b)|function to|method to)\b/i;

// An ASCII sequence-diagram arrow. A long rule of dashes that ENDS IN AN ARROW
// HEAD is drawing a timeline, not separating sections: `req------->res` is the
// clearest documentation of a race condition anyone has written, and deleting it
// loses information no function extraction can recover. Measured on 2,186 real
// TypeScript files (zod / TanStack Query / react-router / swr / zustand): 8 of
// the 83 section-banner hits were one such diagram, swr/src/index/use-swr.ts:524
// through :549, explaining request/mutation interleaving. A real banner
// (`// ---------- Checks ----------`,
// react-router/scripts/pr.ts:157) has no arrow head and still fires.
const DIAGRAM_ARROW_RE = /[-=~]{2,}>|<[-=~]{2,}/;

const CODE_KEYWORD_RE =
  /^(import |export |const |let |var |function\b|class |interface |type \w|enum |return\b|throw |await |async |if\s*\(|for\s*\(|while\s*\(|switch\s*\(|new |console\.)/;
const CODE_TAIL_RE = /[;{}()]\s*$|=>\s*$|,\s*$/;
// LHS must be a real identifier (not a number literal — `0=Monday` in prose is
// not an assignment) and `=` must not be `==`/`===`/`=>` (comparison/arrow).
// The assignment branch additionally requires a code-tail — the line must end
// with `;`, `)`, `}` or `]` — so plain prose like `count = number of items`
// (which has no code-tail) is not mistaken for commented-out code.
const CALL_OR_ASSIGN_RE =
  /^[A-Za-z_$][\w.$[\]]*\s*(?:=(?![=>])|\+=|-=|\*=)\s*\S.*[;)}\]]\s*$|^[A-Za-z_$][\w.$]*\([^)]*\)\s*;?\s*$/;

// Placeholders that only appear in grammar productions / desugaring examples,
// never in real code: `%sent%`, `[opt]`, a standalone `<FunctionBody>`, `…` / `...`.
const PSEUDOCODE_RE = /%\w+%|\[opt\]|(?:^|\s)<[A-Za-z]\w*>|…|\.\.\./;

// A triple-slash `///` directive keeps its third `/` after ESLint strips the
// leading `//`, so strip 1–2 leading slashes (not exactly two) for `<reference`.
function stripCommentMarker(line: string): string {
  return line.replace(/^\s*\/{1,2}/, "").replace(/^\s*\*+/, "").trim();
}

function isDirective(text: string): boolean {
  return DIRECTIVE_RE.test(text.trim());
}

function isBanner(text: string): boolean {
  const t = text.trim();
  if (!t) return false;
  if (BANNER_FULL_RE.test(t) || isRegionMarker(t)) return true;
  return BANNER_RUN_RE.test(t) && !DIAGRAM_ARROW_RE.test(t);
}

function looksLikeCode(text: string): boolean {
  const t = text.trim();
  if (!t) return false;
  if (CODE_KEYWORD_RE.test(t) && CODE_TAIL_RE.test(t)) return true;
  return CALL_OR_ASSIGN_RE.test(t);
}

function hasPseudocode(text: string): boolean {
  return PSEUDOCODE_RE.test(text);
}

/** An explanatory item of a numbered/bulleted walkthrough. */
function isEnumeratedProseItem(text: string): boolean {
  const t = text.trim();
  return ENUMERATED_ITEM_RE.test(t) && t.split(/\s+/).length >= ENUMERATED_ITEM_MIN_WORDS;
}

// A prose lead-in preceding a code-shaped line marks that line as an
// illustration (`// For example:`, a grammar production `FunctionExpression:`),
// not commented-out code.
function isProse(text: string): boolean {
  const t = text.trim();
  if (!t) return false;
  if (t.endsWith(":")) return true;
  if (
    /[.!?]$/.test(t) &&
    /\s/.test(t) &&
    /[a-z]/.test(t) &&
    !looksLikeCode(t) &&
    t.split(/\s+/).length >= 3
  ) {
    return true;
  }
  return false;
}

// --- "restates the next line" ---------------------------------------------
// A comment that opens with a narration verb and whose every remaining content
// word already names what the statement below it computes says nothing the code
// does not (`// increment the counter` / `counter += 1`). Three guards keep the
// inference sound, because *coincidental* token overlap is the failure mode that
// sank the first attempt at this shape (PR #98: `service` matching
// `locationService` gave a ~60% false-positive rate):
//
//  1. Total corroboration — one unmatched word (`// guard the race from
//     PLT-812`) means the comment carries something the code does not, so it
//     stays.
//  2. The comment must sit on top of a single-line, value-producing *statement*.
//     A comment above a block, a declaration, a type member or an object-literal
//     entry (`// store state` above `interface SessionState {`) labels a region
//     of code; the words it shares with the first line of that region are
//     incidental.
//  3. Only the head of the statement counts — everything up to the first `(` —
//     so the comment must restate what the statement *computes* (its target and
//     its callee), not merely something it passes as an argument.

// A causal connective. `for now` inside a sentence that also states WHY is a
// justification, not an admission — `// Needed for now since router.fetch is not
// async until v7` (react-router/.../__tests__/router/lazy-discovery-test.ts:2412,
// and :2505) is the reason the sleep exists, which is exactly what the rule wants
// a comment to carry. A bare `// quick fix for now` still fires.
const JUSTIFICATION_RE =
  /\b(?:because|since|until|due to|so that|otherwise|which is why|in order to|to avoid|to work around|to prevent)\b/i;

/**
 * Whether a single-line comment merely narrates the code rather than explaining
 * the *why*. Three deterministic shapes: step narration ("First, …"), self-
 * admitted meta-commentary ("keeping it simple"), and a restatement of the very
 * next line (`// increment the counter` above `counter += 1`).
 *
 * `standalone` is false when the comment is one line of a contiguous `//` block.
 * The step and meta shapes are single-line tells; inside a paragraph they match a
 * clause of running prose rather than a label. Measured on 2,186 real TypeScript
 * files (zod / TanStack Query / react-router / swr / zustand), 9 of 42 narration
 * hits were exactly that — e.g. react-router/integration/bug-report-test.ts:26
 * ("First, make sure to install dependencies and build React Router. From the
 * root of / the project, run this:"), a six-line contributor instruction, and
 * react-router/packages/react-router/lib/dom/ssr/routes.tsx:663. A restatement of
 * the next line is still checked in a block, since it is corroborated against the
 * code rather than against a phrase.
 */
function isRedundantNarration(
  body: string,
  statementBelow: string | null,
  standalone: boolean,
  isolatedEnumeration: boolean,
  nested: boolean,
): boolean {
  const t = body.trim();
  if (!t || looksLikeCode(t) || hasPseudocode(t)) return false;
  if (standalone) {
    if (STEP_NARRATION_RE.test(t)) return true;
    if (META_COMMENTARY_RE.test(t) && !JUSTIFICATION_RE.test(t)) return true;
    if (HELPER_OPENER_RE.test(t) || LETS_RE.test(t)) return true;
    
    const words = t.split(/\s+/);
    if (words.length <= 4 && DUMMY_TRANSLATION_RE.test(t) && !/[():=]/.test(t)) {
      const lowerT = t.toLowerCase();
      const rationaleWords = ["when", "because", "if", "so that", "due to", "for", "instead of", "to prevent", "to avoid", "only"];
      if (!rationaleWords.some(w => lowerT.includes(w))) {
        if (words.length > 1) return true;
      }
    }

    if (!nested && isSectionLabel(t)) return true;
    if (isolatedEnumeration && ENUMERATION_RE.test(t)) return true;
  }
  return restatesStatementHead(t, statementBelow);
}

// Statement-position containers. A comment whose innermost enclosing node is
// anything else sits INSIDE an expression — an array, an object literal, a call
// argument list — where a one-word label groups the elements beneath it rather
// than signposting the file. `# config` inside pydantic's `__all__` is the
// Python twin of this; both readings produce the same comment and only the
// nesting tells them apart.
const STATEMENT_CONTAINERS: ReadonlySet<string> = new Set([
  AST_NODE_TYPES.Program,
  AST_NODE_TYPES.BlockStatement,
  AST_NODE_TYPES.ClassBody,
  AST_NODE_TYPES.StaticBlock,
  AST_NODE_TYPES.SwitchCase,
  AST_NODE_TYPES.TSModuleBlock,
  AST_NODE_TYPES.TSInterfaceBody,
]);

/**
 * True when the comment at `index` belongs to a contiguous `//` run in which
 * some line cites a ticket, URL, RFC or issue number (protected-class signal
 * S1, applied at run granularity).
 *
 * A scoping note puts its owner at the end — bulbul's Zoho-canary comment ends
 * "EN-only for now — add an AR variant once AR audio exists (PROD-249)" — so
 * judging the last line alone read "for now" as an unowned admission. A comment
 * that names where the decision is recorded is doing the one thing code cannot.
 */
function runCitesAReference(comments: readonly TSESTree.Comment[], index: number): boolean {
  for (let i = index; i >= 0; i--) {
    if (i < index && !areAdjacentLineComments(comments[i], comments[i + 1])) break;
    if (hasExternalReference(stripCommentMarker(comments[i]?.value ?? ""))) return true;
  }
  for (let i = index + 1; i < comments.length; i++) {
    if (!areAdjacentLineComments(comments[i - 1], comments[i])) break;
    if (hasExternalReference(stripCommentMarker(comments[i]?.value ?? ""))) return true;
  }
  return false;
}

/** True when `a` and `b` are `//` comments on consecutive lines. */
function areAdjacentLineComments(
  a: TSESTree.Comment | undefined,
  b: TSESTree.Comment | undefined,
): boolean {
  return (
    a !== undefined &&
    b !== undefined &&
    a.type === "Line" &&
    b.type === "Line" &&
    b.loc.start.line === a.loc.end.line + 1
  );
}

/**
 * True when the comment at `index` is one line of a contiguous `//` block rather
 * than a lone annotation.
 */
function isInsideCommentRun(comments: readonly TSESTree.Comment[], index: number): boolean {
  const comment = comments[index];
  return (
    areAdjacentLineComments(comments[index - 1], comment) ||
    areAdjacentLineComments(comment, comments[index + 1])
  );
}

/** How far back the illustration lead-in scan walks within one `//` block. */
const LEAD_IN_SCAN_LIMIT = 24;

/**
 * True when a prose lead-in (`// Example:`, `// For example:`, a grammar
 * production head) appears earlier in the SAME contiguous `//` block. The
 * existing check only looked at the immediately preceding comment, so a code
 * illustration more than one line below its own heading was read as
 * commented-out code — measured at
 * react-router/packages/react-router/lib/hooks.tsx:791, where `// function
 * Blog() {` sits nine lines under its `// Example:` heading inside one 17-line
 * block (2 hits there of the 695 commented-out-code hits over 2,186 files).
 */
function hasIllustrationLeadInAbove(
  comments: readonly TSESTree.Comment[],
  index: number,
): boolean {
  for (let i = index - 1; i >= 0 && index - i <= LEAD_IN_SCAN_LIMIT; i--) {
    if (!areAdjacentLineComments(comments[i], comments[i + 1])) return false;
    const body = stripCommentMarker(comments[i]?.value ?? "");
    if (body.length > 0 && body.endsWith(":")) return true;
  }
  return false;
}

function hasCommentedOutCode(
  texts: readonly string[],
  precedingProse: boolean,
): boolean {
  for (let i = 0; i < texts.length; i++) {
    const line = texts[i];
    if (line === undefined || !looksLikeCode(line) || hasPseudocode(line)) {
      continue;
    }
    const prev = i > 0 ? texts[i - 1] : undefined;
    if (prev !== undefined ? isProse(prev) : precedingProse) continue;
    return true;
  }
  return false;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-comment-cruft",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Flag commented-out code, section-banner comments, and leading file-header comment preambles.",
    },
    schema: [],
    messages: {
      commentedOutCode:
        "Commented-out code — delete it; git history remembers.",
      sectionBanner:
        "Section-banner / region comment — structure code with functions, not ASCII rules.",
      fileHeaderPreamble:
        "File-header comment preamble — use a brief doc comment for the why, not a block of `//` lines.",
      redundantNarration:
        "Comment narrates the code — delete it or say *why*, not *what*. Code is self-documenting.",
      untrackedTodo:
        "Untracked TODO/FIXME marker — add an issue ticket or context link.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }

    const sourceCode = context.sourceCode;

    function isStandalone(comment: TSESTree.Comment): boolean {
      const before = sourceCode.getTokenBefore(comment, {
        includeComments: false,
      });
      return !before || before.loc.end.line < comment.loc.start.line;
    }

    function isJsDoc(comment: TSESTree.Comment): boolean {
      return comment.type === "Block" && /^\*/.test(comment.value);
    }

    function reportLeadingPreamble(
      comments: readonly TSESTree.Comment[],
      firstCodeLine: number,
    ): void {
      const leading: TSESTree.Comment[] = [];
      let prevLine: number | null = null;
      for (const comment of comments) {
        if (comment.type !== "Line") break;
        if (comment.loc.start.line >= firstCodeLine) break;
        if (!isStandalone(comment)) break;
        const body = stripCommentMarker(comment.value);
        if (isDirective(body) || body.startsWith("!")) continue;
        if (prevLine !== null && comment.loc.start.line !== prevLine + 1) break;
        leading.push(comment);
        prevLine = comment.loc.start.line;
      }
      const first = leading[0];
      if (first === undefined || leading.length < LEADING_PREAMBLE_MIN) return;
      const bodies = leading.map((c) => stripCommentMarker(c.value));
      if (bodies.some((body) => LICENSE_RE.test(body))) return;
      // A preamble carrying at least one prose sentence is documentation — the
      // "why" the rule wants — regardless of which comment syntax carries it.
      if (bodies.some((body) => isProse(body))) return;
      // Same for a numbered/bulleted walkthrough. The single corpus hit for this
      // message across 2,186 real TypeScript files was
      // react-router/scripts/release-comments.ts:1, a six-step description of
      // what the script does ("1. get all tags sorted by creation date", …) —
      // documentation, not a stack of content-free labels.
      if (bodies.filter(isEnumeratedProseItem).length >= ENUMERATED_PREAMBLE_MIN_ITEMS) {
        return;
      }
      context.report({ node: first, messageId: "fileHeaderPreamble" });
    }

    return {
      Program(): void {
        const comments = sourceCode.getAllComments();
        const firstCodeLine =
          sourceCode.ast.tokens[0]?.loc.start.line ?? Number.MAX_SAFE_INTEGER;
        const enumerated = comments.filter(
          (c) => c.type === "Line" && ENUMERATION_RE.test(stripCommentMarker(c.value)),
        );

        for (let i = 0; i < comments.length; i++) {
          const comment = comments[i];
          if (comment === undefined) continue;
          if (isJsDoc(comment) || !isStandalone(comment)) continue;
          if (LICENSE_RE.test(comment.value)) continue;
          const texts = comment.value
            .split("\n")
            .map(stripCommentMarker)
            .filter((l) => l.length > 0 && !isDirective(l));

          const firstText = texts[0];
          if (firstText !== undefined && /^(?:todo|fixme)\b/i.test(firstText)) {
            if (!runCitesAReference(comments, i)) {
              context.report({
                node: comment,
                messageId: "untrackedTodo",
              });
            }
            continue;
          }

          if (texts.some(isBanner)) {
            context.report({ node: comment, messageId: "sectionBanner" });
            continue;
          }
          const prev = comments[i - 1];
          const precedingProse =
            prev !== undefined &&
            prev.type === "Line" &&
            prev.loc.end.line === comment.loc.start.line - 1 &&
            isProse(stripCommentMarker(prev.value));
          if (
            hasCommentedOutCode(texts, precedingProse) &&
            !hasIllustrationLeadInAbove(comments, i)
          ) {
            context.report({ node: comment, messageId: "commentedOutCode" });
            continue;
          }
          // Narration only for single-line comments (a multi-line block is
          // usually a real doc).
          if (comment.type === "Line" && texts.length === 1) {
            const body = texts[0];
            const statement = restatableStatementBelow(comment, sourceCode);
            const standalone = !isInsideCommentRun(comments, i);
            const container = sourceCode.getNodeByRangeIndex(comment.range[0]);
            const nested = container !== null && !STATEMENT_CONTAINERS.has(container.type);
            if (
              body !== undefined &&
              !runCitesAReference(comments, i) &&
              isRedundantNarration(body, statement, standalone, enumerated.length === 1, nested)
            ) {
              context.report({ node: comment, messageId: "redundantNarration" });
            }
          }
        }

        reportLeadingPreamble(comments, firstCodeLine);
      },
    };
  },
});
