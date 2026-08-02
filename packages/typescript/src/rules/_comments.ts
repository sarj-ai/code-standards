/**
 * @fileoverview _comments — shared comment analysis for the comment-hygiene rules, kept signal-for-signal identical to Python's `_comments.py`.
 *
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

// S1 — external reference: URL, ticket key, RFC/PEP/CVE, bare issue number, or
// an email/handle domain. Ticket keys allow letters after the first digit
// (`PLATFORM-1YC`) and exclude the encoding acronyms sharing the shape.
const REF_RE =
  /https?:\/\/|\bRFC[- ]?\d+|\bPEP[- ]?\d+|\bCVE-\d{4}|\b(?!UTF-|SHA-|ISO-|AES-|CRC-|MD-|PCM-|EOF-|API-|BASE-)[A-Z][A-Z0-9]{1,9}-\d[A-Z0-9]{0,5}\b|(?<![&\w])#\d{2,6}\b|@[a-z][\w.-]*\.(?:us|com|ai|io|net|org|dev)\b/;

// S2 — version pin or comparison.
const VERSION_RE =
  /(?:>=|<=|==|<|>)\s*v?\d+\.\d+|\bv\d+\.\d+|\b(?:since|until|as of)\s+(?:v?\d+\.\d+|Python\s*\d)/i;

// S3 — a number carrying a unit, or an HTTP status code.
const UNITS_RE =
  /[~<>]?\d+(?:\.\d+)?\s?(?:ms|s\b|sec\b|seconds?\b|min\b|minutes?\b|hours?\b|days?\b|KB|MB|MiB|GiB|kHz|Hz|bytes?\b|bit\b|-bit\b|%|px\b|rps\b|qps\b)|\b[1-5]xx\b|\b(?:301|302|304|307|308|400|401|403|404|405|409|410|412|422|425|429|500|501|502|503|504)\b/;

// S4 — a causal connective tying behaviour to a consequence.
const CAUSAL_RE =
  /\b(?:because|otherwise|so that|or else|would (?:break|fail|race|deadlock|leak|clobber|loop|crash|page|stall)|breaks?\b|so we don'?t|to avoid\b|caused\b|causes\b|gets? clobbered|keeps? (?:us|it|them) from|doesn'?t\b.{0,24}\b(?:page|fire|break|leak|loop)|eat into|would otherwise|trade-?offs?\b)\b/i;

// S5 — negation of the obvious, or a flagged deliberate deviation.
const NEGATION_RE =
  /\b(?:must not|must never|do(?:es)? not\b|don'?t\b.{0,30}\b(?:leak|log|cache|retry|block|steal|wipe)|never\b|deliberately|intentionally|counterintuitiv|NOT\b)|(?<!based )\bon purpose\b|\(not\s|\binstead of\b|\brather than\b/;

// S6 — upstream/vendor quirk, workaround provenance, or an external contract.
const UPSTREAM_RE =
  /\b(?:upstream|workaround|quirk|backport|vendored|regression|fixed upstream|requires?\b|convention\b|rate.?limit|deprecat|opts? in(?:to)?\b|raises?\b.{0,60}\b(?:when|if|unless)\b)/i;

// S7 — concurrency, ordering, or invariant vocabulary.
const INVARIANT_RE =
  /\b(?:invariant|idempotent|race\b|deadlock|re-?entran|atomic|thread-?safe|signal-?safe|lexicographic(?:al(?:ly)?)?|monotonic|must (?:run|be|happen|come|stay|hit|converge|configure)|before any\b|lost the (?:claim )?race)\b/i;

// S8 — security reasoning.
const SECURITY_RE =
  /\b(?:timing attack|constant-?time|replay|PII\b|redact|secret|injection|spoof|fail-?closed|fail-?open|auth bypass|early-?exit timing)\b/i;

const VENDOR_RE =
  /\b(?:GitHub|Slack|Twilio|LiveKit|Kamailio|Groq|OpenAI|Anthropic|Cloudflare|FastAPI|Starlette|Sentry|Zoho|Salla|Ashby|Linear|BigQuery|Postgres|Neon|Drizzle|Vertex|Gemini|Firestore|Stripe|Next\.js|React Compiler|pydantic|ruff|loguru|Lexical|Farasa|Orpheus|Whisper|schemathesis)(?:'s\b|\s+(?:requires?|returns?|expects?|allows?|rejects?|accepts?|sends?|caps?|limits?|wraps?|silently|outputs?|stores?|treats?|doesn'?t|does not|won'?t|can'?t|only|models)\b)/;

const PROTECTED_SIGNALS: readonly RegExp[] = [
  REF_RE,
  VERSION_RE,
  UNITS_RE,
  CAUSAL_RE,
  NEGATION_RE,
  UPSTREAM_RE,
  INVARIANT_RE,
  SECURITY_RE,
  VENDOR_RE,
];

/**
 * True when a comment carries any of the nine protected-class signals.
 *
 * EXEMPTION FLOOR ONLY — a false result is not evidence the comment is worthless.
 */
export function isProtected(body: string): boolean {
  return PROTECTED_SIGNALS.some((signal) => signal.test(body));
}

/**
 * True when a comment cites a ticket, URL, RFC/PEP/CVE or issue number (signal
 * S1 alone). Naming where a decision is recorded is the one thing code cannot
 * do, and it separates an owned scoping note from an unowned admission.
 */
export function hasExternalReference(body: string): boolean {
  return REF_RE.test(body);
}

/**
 * Words that say nothing about *which* code a comment describes. Kept in step
 * with `_comments.py`: shrinking the list costs recall, growing it costs
 * precision by discounting a genuinely novel word.
 */
export const STOPWORDS: ReadonlySet<string> = new Set(
  `a an the this that these those it its their his her our your my
   is are was were be been being am do does did done doing has have had having
   will would shall should can could may might must
   and or but nor so yet not no none
   to of for in on at by with from into onto out up down over under about
   as if then than when where which who whom whose what how why while
   we you they i he she them him us me
   also just only even still already again there here
   all any each every some
   via per etc eg ie vs
   need needs needed want wants make makes making let lets
   please note see above below`.split(/\s+/),
);

const CAMEL_PART_RE = /[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+/g;
const WORD_RE = /[A-Za-z_$][\w$]*|\d+/g;

/** Split `snake_case` / `camelCase` / `SCREAMING_CASE` into lowercase parts. */
export function splitIdentifier(token: string): string[] {
  const parts: string[] = [];
  for (const chunk of token.split(/[_$]/)) {
    for (const match of chunk.match(CAMEL_PART_RE) ?? []) {
      parts.push(match.toLowerCase());
    }
  }
  return parts;
}

/**
 * Fold the common English inflections so `updates` / `updating` match `update`.
 *
 * The trailing-`e` strip is what makes the fold *symmetric*: without it
 * `creates` / `creating` reduce to `creat` while `create` stays `create`, and
 * the two never match — the shape that most often made a restatement look
 * novel. Deliberately crude otherwise; every extra conflation is a chance to
 * call a novel word a restatement.
 */
export function stem(word: string): string {
  let base = word;
  for (const suffix of ["ing", "ied", "ies", "ers", "er", "ed", "es", "s"]) {
    if (word.endsWith(suffix) && word.length - suffix.length >= 3) {
      base = word.slice(0, word.length - suffix.length);
      if (suffix === "ied" || suffix === "ies") return `${base}y`;
      break;
    }
  }
  return base.endsWith("e") && base.length - 1 >= 3 ? base.slice(0, -1) : base;
}

/** Split prose into lowercase content words, dropping stopwords. */
export function contentTokens(text: string): string[] {
  const tokens: string[] = [];
  for (const match of text.match(WORD_RE) ?? []) {
    tokens.push(...splitIdentifier(match));
  }
  return tokens.filter((token) => !STOPWORDS.has(token));
}

/** Every identifier part appearing in a slice of source. */
export function codeTokens(text: string): Set<string> {
  const tokens = new Set<string>();
  for (const match of text.match(WORD_RE) ?? []) {
    for (const part of splitIdentifier(match)) tokens.add(part);
  }
  return tokens;
}

/** True when every content token of a comment already appears in the code. */
export function restates(commentTokens: readonly string[], code: ReadonlySet<string>): boolean {
  const stems = new Set<string>();
  for (const token of code) stems.add(stem(token));
  return commentTokens.every((token) => code.has(token) || stems.has(stem(token)));
}

const NARRATION_MAX_WORDS = 6;
const NARRATION_MIN_CONTENT = 1;
const TOKEN_PLURAL_MIN = 4;

// Statements that compute something a comment could be restating. A block, a
// class/function/type declaration, an `if`, a `for` — anything whose body the
// comment could be labelling instead — is deliberately absent.
const RESTATABLE_STATEMENTS: ReadonlySet<string> = new Set([
  AST_NODE_TYPES.ExpressionStatement,
  AST_NODE_TYPES.ReturnStatement,
  AST_NODE_TYPES.ThrowStatement,
  AST_NODE_TYPES.VariableDeclaration,
]);

// Verbs that describe the mechanics of the next statement. A comment opening
// with anything else (a noun, "because", "we", a ticket id) is not narration.
const NARRATION_VERB_RE =
  /^(?:add|append|assign|build|calculate|call|check|clear|close|compute|convert|copy|count|create|declare|decrement|define|delete|extract|fetch|filter|find|format|generate|get|handle|increment|init|initialise|initialize|insert|iterate|join|load|log|loop|make|map|merge|open|parse|print|process|push|read|remove|render|reset|return|save|send|set|setup|sort|split|start|stop|store|update|validate|wrap|write)(?:s|es|d|ed|ing)?$/i;

// Words that carry no information about *which* code the comment describes, so
// they are not required to appear in the line below.
const NARRATION_STOPWORDS: ReadonlySet<string> = new Set([
  "a", "all", "an", "and", "any", "are", "as", "at", "back", "be", "both", "by",
  "each", "for", "from", "here", "if", "in", "into", "is", "it", "its", "just",
  "new", "of", "on", "one", "onto", "or", "our", "out", "over", "so", "that",
  "the", "then", "this", "to", "up", "us", "we", "when", "with",
]);

/** Lowercase, with a single plural `s` folded away so `users` matches `user`. */
export function normalizeToken(word: string): string {
  const lower = word.toLowerCase();
  return lower.length > TOKEN_PLURAL_MIN && lower.endsWith("s") && !lower.endsWith("ss")
    ? lower.slice(0, -1)
    : lower;
}

/** Every identifier in a slice of source, plus its parts, with plurals folded. */
function headTokens(source: string): ReadonlySet<string> {
  const tokens = new Set<string>();
  for (const identifier of source.match(/[A-Za-z_$][\w$]*/g) ?? []) {
    tokens.add(normalizeToken(identifier));
    for (const part of identifier.split(/[_$]+|(?<=[a-z0-9])(?=[A-Z])/)) {
      if (part.length > 0) tokens.add(normalizeToken(part));
    }
  }
  return tokens;
}

/** The slice of ESLint's `SourceCode` these shapes read. */
export interface StatementReader {
  getTokenAfter: (
    node: TSESTree.Comment,
    options: { includeComments: boolean },
  ) => TSESTree.Token | null;
  getNodeByRangeIndex: (index: number) => TSESTree.Node | null;
  getText: (node: TSESTree.Node) => string;
}

/** A declaration with nothing but a zero/empty seed computes nothing to restate. */
function isTrivialInitializer(node: TSESTree.VariableDeclaration): boolean {
  return node.declarations.every((declarator) => {
    const init = declarator.init;
    if (init == null || init.type === AST_NODE_TYPES.Literal) return true;
    return (
      (init.type === AST_NODE_TYPES.ArrayExpression && init.elements.length === 0) ||
      (init.type === AST_NODE_TYPES.ObjectExpression && init.properties.length === 0)
    );
  });
}

/**
 * The source of the single-line statement a comment sits directly above, or null
 * when what follows is a block, a declaration, a type member or anything else
 * the comment could be *labelling* rather than restating.
 */
export function restatableStatementBelow(comment: TSESTree.Comment, sourceCode: StatementReader): string | null {
  const token = sourceCode.getTokenAfter(comment, { includeComments: false });
  if (token === null || token.loc.start.line !== comment.loc.end.line + 1) return null;
  for (
    let node: TSESTree.Node | undefined | null = sourceCode.getNodeByRangeIndex(token.range[0]);
    node != null && node.type !== AST_NODE_TYPES.Program;
    node = node.parent
  ) {
    if (!RESTATABLE_STATEMENTS.has(node.type)) continue;
    if (node.loc.start.line !== token.loc.start.line || node.loc.end.line !== node.loc.start.line) {
      return null;
    }
    if (node.type === AST_NODE_TYPES.VariableDeclaration && isTrivialInitializer(node)) {
      return null;
    }
    return sourceCode.getText(node);
  }
  return null;
}

/**
 * True when a short verb-led comment adds nothing to the statement beneath it:
 * every content word after the opening verb already appears in that statement's
 * head — its assignment target or its callee.
 *
 * Corroboration is TOTAL: one unmatched word means the comment carries
 * something the code does not, so it stays. Only the head counts — everything
 * up to the first `(` — so the comment must restate what the statement
 * *computes*, not something it merely passes as an argument.
 */
export function restatesStatementHead(body: string, statement: string | null): boolean {
  if (statement === null) return false;
  const words = body.match(/[A-Za-z][\w$]*/g) ?? [];
  const opener = words[0];
  if (opener === undefined || words.length > NARRATION_MAX_WORDS) return false;
  if (!NARRATION_VERB_RE.test(opener)) return false;
  const content = words
    .slice(1)
    .map(normalizeToken)
    .filter((word) => !NARRATION_STOPWORDS.has(word));
  if (content.length < NARRATION_MIN_CONTENT) return false;
  const head = statement.split("(")[0] ?? statement;
  const code = headTokens(head);
  return content.every((word) => code.has(word));
}
