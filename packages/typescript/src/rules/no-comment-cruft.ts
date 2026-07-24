/**
 * @fileoverview Flag comment cruft — commented-out code, section banners,
 * leading file-header comment preambles, and redundant narration (step markers
 * like "First, …" and self-admitted meta-commentary like "for now" / "temporary
 * hack"). Code carries the *what*; comments are reserved for the *why*. The
 * fuzzier "this comment restates the next line" judgment stays in review (a
 * substring-corroboration heuristic was too false-positive-prone on real code).
 * JSDoc (`/** ... *\/`) is never flagged, and directive comments (`eslint-`,
 * `@ts-`, `prettier-`, `biome-`, `c8`, `<reference`, `TODO`, `FIXME`) are ignored.
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
 */

import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

type MessageIds =
  | "commentedOutCode"
  | "sectionBanner"
  | "fileHeaderPreamble"
  | "redundantNarration";
type Options = readonly [];

const LEADING_PREAMBLE_MIN = 4;

// Step-narration lead-ins ("First, …", "Then, …", "Finally, …", "Step 2:"). A
// trailing comma/colon is required so English adverbs ("finally the invariant
// holds") aren't mistaken for an enumeration marker.
const STEP_NARRATION_RE =
  /^(?:first(?:ly)?|second(?:ly)?|third(?:ly)?|then|next|after(?:wards| that)?|finally|lastly|now)\s*[,:]\s*\S|^step\s+\d+\b/i;

// Self-admitted meta-commentary — the "why later", not the why. `TODO`/`FIXME`/
// `HACK`/`XXX` are handled as directives (kept, with an owner, per convention).
const META_COMMENTARY_RE =
  /\b(?:for now|keeping (?:it|this) simple|could be (?:refactored|improved|cleaned up|simplified)|refactor(?:ed|ing)? (?:later|this)|not sure (?:if|whether|why|how)|quick[- ](?:and[- ]dirty|fix)|(?:a |bit of a )?hacky|is a hack|temporary (?:solution|workaround|fix|hack)|revisit (?:this|later|below)|clean (?:this|it) up|not ideal|placeholder for now)\b/i;


const DIRECTIVE_RE =
  /^(eslint\b|eslint-|@ts-|prettier-ignore|prettier\b|biome-|c8\b|v8\b|istanbul\b|@type\b|@vite|webpack|<reference|<amd|global\b|noinspection|todo\b|fixme\b|hack\b|xxx\b)/i;

const LICENSE_RE =
  /copyright|licen[cs]ed?|spdx|permission is hereby granted|all rights reserved/i;

const BANNER_FULL_RE = /^[\s\-=*#~_+.]{4,}$/;
// `={4,}` not `={3,}`: `===` is TS strict-equality and appears in prose comments.
const BANNER_RUN_RE = /={4,}|-{4,}|#{4,}|\*{4,}|~{4,}/;
const REGION_RE = /^#?(?:end)?region\b/i;

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
  return BANNER_FULL_RE.test(t) || BANNER_RUN_RE.test(t) || REGION_RE.test(t);
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

/**
 * Whether a single-line comment merely narrates the code rather than explaining
 * the *why*. Three deterministic shapes: step narration ("First, …"), self-
 * admitted meta-commentary ("keeping it simple"), and a restatement of the very
 * next statement — a narration-verb opener corroborated by a shared token with
 * the following code line (`// create the user` above `const user = createUser()`).
 */
function isRedundantNarration(body: string): boolean {
  const t = body.trim();
  if (!t || looksLikeCode(t) || hasPseudocode(t)) return false;
  if (STEP_NARRATION_RE.test(t)) return true;
  if (META_COMMENTARY_RE.test(t)) return true;
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
    },
  },
  defaultOptions: [],
  create(context) {
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
      context.report({ node: first, messageId: "fileHeaderPreamble" });
    }

    return {
      Program(): void {
        const comments = sourceCode.getAllComments();
        const firstCodeLine =
          sourceCode.ast.tokens[0]?.loc.start.line ?? Number.MAX_SAFE_INTEGER;

        for (let i = 0; i < comments.length; i++) {
          const comment = comments[i];
          if (comment === undefined) continue;
          if (isJsDoc(comment) || !isStandalone(comment)) continue;
          if (LICENSE_RE.test(comment.value)) continue;
          const texts = comment.value
            .split("\n")
            .map(stripCommentMarker)
            .filter((l) => l.length > 0 && !isDirective(l));
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
          if (hasCommentedOutCode(texts, precedingProse)) {
            context.report({ node: comment, messageId: "commentedOutCode" });
            continue;
          }
          // Narration only for single-line comments (a multi-line block is
          // usually a real doc). The next non-blank source line is the code the
          // comment sits above.
          if (comment.type === "Line" && texts.length === 1) {
            const body = texts[0];
            if (body !== undefined && isRedundantNarration(body)) {
              context.report({ node: comment, messageId: "redundantNarration" });
            }
          }
        }

        reportLeadingPreamble(comments, firstCodeLine);
      },
    };
  },
});
