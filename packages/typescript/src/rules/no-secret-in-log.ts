/**
 * @fileoverview TS port of SARJ012 (`no-secret-in-log`). Passing a secret value
 * (token, password, api key, jwt, credential, signature, ...) to a logging call
 * leaks it into log sinks — files, stdout, log aggregators — where it persists
 * far beyond its intended lifetime and is readable by anyone with log access.
 * Prefer redaction (`tokenPrefix: token.slice(0, 6)`) or omission.
 *
 * We fire on a logging call (`logger.info(...)`, `log.error(...)`, loguru/bind
 * builder chains, etc.) that passes a secret-named value either as a property of
 * an object argument (`logger.error("msg", { token, apiKey })`) or as a bare
 * secret-named positional identifier (`logger.info("x", password)`).
 *
 * Log recognition is shared with the catch rules via `_logging`, so the
 * `logFunctions` option applies here too. That matters: a structured logger is
 * usually a free function with no logger receiver, and `logEvent("slack.auth",
 * { botToken })` was previously never even examined by this rule. Declaring the
 * project's logger closes that hole.
 *
 * The secret-name predicate matches a secret word only as a WHOLE token (after
 * snake_case / camelCase splitting) and disqualifies identifiers whose trailing
 * token is a counter / row-id / flag marker (`tokenCount`, `apiKeyId`,
 * `passwordEnabled`) or whose LEADING word is a boolean predicate (`hasSecret`,
 * `is_token`), so metadata *about* a secret is not mistaken for the secret
 * itself. Both guards live in the shared `_secret_names` predicate. Redaction
 * markers (prefix/mask/hash/redact/tag) are exempt on top of that.
 *
 * ## The raw-blob arm (`noRawBodyInLog`)
 *
 * A second, separately-messaged arm covers what the name-based arm structurally
 * cannot: a whole request/response **blob** — `logEvent("ashby.response",
 * { status, body })`, `console.log(res.body)`. No property of that object is
 * secret-*named*; the object itself is the leak. Bodies are candidate PII and
 * routinely echo credentials back (an auth response containing the token it just
 * minted, a webhook payload carrying its own signing header), and a log sink has
 * no retention policy for either. The advice differs from the secret arm's —
 * "redact or omit the blob", not "this named field is a credential" — so it gets
 * its own messageId.
 *
 * This arm is deliberately name-driven and narrow. **Only these words, matched as
 * the identifier's TRAILING camel/snake word, count as a raw blob**: `body`,
 * `bodies`, `payload`, `payloads`, `params` (so `rawBody`, `requestBody`,
 * `responsePayload`, `webhookPayload`, `searchParams` all qualify), plus the
 * single whole identifier `formData` (whose camel split ends in the far too
 * generic `data`). Generic containers — `data`, `input`, `args`, `event`,
 * `result`, `record`, `req`, `res` — are NOT blob words: they name everything, so
 * firing on them would make the rule noise and get it switched off.
 *
 * A leak is reported only when the logged VALUE is the blob verbatim: a shorthand
 * property (`{ body }`), a bare identifier (`{ meta: body }`, `logEvent("x",
 * payload)`), or a non-computed member access whose PROPERTY is blob-named
 * (`{ body: res.body }`, `console.log(res.body)`). Judging the value rather than
 * the key is what keeps `{ payload: body.id }` silent.
 *
 * Deliberately NOT reported:
 * - **A narrowed field** — `{ id: body.id }`, `{ bodyLength: body.length }`. The
 *   member property, not the object, decides; picking a field is the fix.
 * - **Anything passed through a call** — `redact(body)`, `sanitize(payload)`,
 *   `pick(body, ["id"])`, `JSON.stringify(body).slice(0, 200)`,
 *   `summarizeIssues(body)`. Summarising is the behaviour we want, and no name
 *   list can enumerate every project's summariser, so the *shape* is the exemption.
 * - **A string literal or template** — `{ body: "ok" }`, `` { body: `n=${n}` } ``.
 *   Already a rendered, author-chosen string.
 * - **Redaction / derivation markers in the name** — `redactedBody`,
 *   `sanitizedPayload`, `truncatedBody`, `bodyHash`, `bodyPreview`, `safeBody`.
 * - **Boolean flags** — `hasBody`, `isPayload`: a leading predicate word.
 * - **Object spread** — `{ ...body }`. Real, but no observed instances; left out
 *   rather than shipped unmeasured.
 * - **Test files** (`_paths.isTestFile`) — a body there is a fixture the author
 *   wrote, not production PII. The secret arm is deliberately NOT exempted this
 *   way: its behaviour is unchanged by this port.
 *
 * Both arms sit behind the same `_logging` gate, so `logFunctions` /
 * `loggerNames` govern the blob arm identically — `logEvent("x", { body })` is
 * invisible until the project declares `logEvent`, exactly like `{ botToken }`.
 *
 * References:
 * - https://owasp.org/www-community/vulnerabilities/Information_exposure_through_log_files
 */

import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import {
  createLogMatcher,
  LOGGING_OPTION_PROPERTIES,
  type LoggingOptions,
} from "./_logging.js";
import { isTestFile } from "./_paths.js";
import {
  FLAG_PREFIXES,
  INNOCUOUS_WORDS,
  isSecretName,
  leadingWord,
  tokenize,
} from "./_secret_names.js";

type MessageIds = "noSecretInLog" | "noRawBodyInLog";
type Options = readonly [LoggingOptions?];

/**
 * The shared metadata set plus the log-specific extras. Logging a secret's
 * label, expiry, ARN, URL, scope, or the DI component that holds it is metadata
 * ABOUT the credential, never the credential bytes, so it must not fire here —
 * `prefer-constant-time-secret-compare` uses the narrower shared set.
 */
const LOG_INNOCUOUS_WORDS: ReadonlySet<string> = new Set([
  ...INNOCUOUS_WORDS,
  "name",
  "names",
  "label",
  "labels",
  "title",
  "expiry",
  "expiration",
  "expires",
  "ttl",
  "version",
  "versions",
  "policy",
  "rotation",
  "arn",
  "path",
  "paths",
  "issuer",
  "audience",
  "strength",
  "manager",
  "service",
  "services",
  "repository",
  "provider",
  "providers",
  "store",
  "factory",
  "handler",
  "controller",
  "bucket",
  "url",
  "uri",
  "endpoint",
  "endpoints",
  "scope",
  "scopes",
  "event",
  "events",
  "format",
  "at",
  "len",
  "length",
]);

const REDACTION_RE = /prefix|suffix|redact|mask|hash|hint|_len|length/i;
const WHOLE_TOKEN_REDACTION_MARKERS: ReadonlySet<string> = new Set(["tag"]);

/** True if the name names a raw secret and is not a redacted derivative. */
function isSecretKeyword(name: string): boolean {
  if (REDACTION_RE.test(name)) {
    return false;
  }
  if (tokenize(name).some((tok) => WHOLE_TOKEN_REDACTION_MARKERS.has(tok))) {
    return false;
  }
  return isSecretName(name, LOG_INNOCUOUS_WORDS);
}

/**
 * True if `prop`'s value is the raw secret rather than a redacted/derived form.
 * Shorthand (`{ token }`), a bare identifier (`{ apiKey: theKey }`), or a plain
 * member access (`{ apiKey: config.apiKey }`) all carry the secret verbatim. A
 * call (`token.slice(0, 6)`, `mask(token)`), template literal, ternary, concat,
 * or literal placeholder (`"***"`) is already redacted — logging it is safe.
 */
function isRawSecretValue(prop: TSESTree.Property): boolean {
  if (prop.shorthand) {
    return true;
  }
  return prop.value.type === "Identifier" || prop.value.type === "MemberExpression";
}

/**
 * Trailing camel/snake words that name an un-redacted request/response blob. Kept
 * to an enumerated five: these are the containers whose *whole point* is "the
 * bytes the client sent / the server returned". Generic container words (`data`,
 * `input`, `args`, `event`, `result`, `payloadless` domain objects) are excluded
 * on purpose — see the `@fileoverview`.
 */
const RAW_BLOB_WORDS: ReadonlySet<string> = new Set([
  "body",
  "bodies",
  "payload",
  "payloads",
  "params",
]);

/**
 * Whole identifiers whose camelCase split ends in a word too generic to enumerate
 * (`formData` -> `data`) but which name a blob unambiguously on their own.
 */
const RAW_BLOB_IDENTIFIERS: ReadonlySet<string> = new Set(["formdata"]);

/**
 * Substrings that mark a blob name as an already-derived, safe-to-log form:
 * `redactedBody`, `sanitizedPayload`, `truncatedBody`, `bodyPreview`.
 */
const BLOB_REDACTION_RE = /redact|sanit|scrub|mask|truncat|anonym|filtered|preview|summar/i;

/**
 * Derivation markers that are only safe when matched as a WHOLE token — `safe` as
 * a substring would wrongly exempt `unsafeBody`.
 */
const BLOB_REDACTION_TOKENS: ReadonlySet<string> = new Set([
  "safe",
  "clean",
  "shape",
  "keys",
  "public",
]);

/** True if the name names a raw request/response blob and is not a derived form. */
function isRawBlobName(name: string): boolean {
  if (REDACTION_RE.test(name) || BLOB_REDACTION_RE.test(name)) {
    return false;
  }
  const tokens = tokenize(name);
  if (tokens.some((tok) => BLOB_REDACTION_TOKENS.has(tok))) {
    return false;
  }
  // Same leading boolean-predicate words the secret arm uses: `hasBody` answers
  // "is there one?", it is not the blob.
  const first = leadingWord(name);
  if (first !== undefined && FLAG_PREFIXES.has(first)) {
    return false;
  }
  if (RAW_BLOB_IDENTIFIERS.has(name.toLowerCase())) {
    return true;
  }
  const last = tokens.at(-1);
  return last !== undefined && RAW_BLOB_WORDS.has(last);
}

/**
 * The blob name a logged value carries VERBATIM, or null when it does not carry
 * one. A bare identifier is the whole object; a non-computed member access is
 * judged by its PROPERTY, so `res.body` is the blob but `body.id` is a picked
 * field. Every other shape — call, template, literal, ternary, spread — has
 * already been through the author's hands and is left alone.
 */
function rawBlobValueName(value: TSESTree.Node): string | null {
  if (value.type === "Identifier") {
    return isRawBlobName(value.name) ? value.name : null;
  }
  if (
    value.type === "MemberExpression" &&
    !value.computed &&
    value.property.type === "Identifier"
  ) {
    return isRawBlobName(value.property.name) ? value.property.name : null;
  }
  return null;
}

/** The static string name of an object-property key, or null when not statically named. */
function propertyKeyName(prop: TSESTree.Property): string | null {
  if (prop.computed) {
    return null;
  }
  if (prop.key.type === "Identifier") {
    return prop.key.name;
  }
  if (prop.key.type === "Literal" && typeof prop.key.value === "string") {
    return prop.key.value;
  }
  return null;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-secret-in-log",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow passing a secret-named value or a raw request/response blob to a logging call; both leak to log sinks. Redact or omit.",
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: { ...LOGGING_OPTION_PROPERTIES },
      },
    ],
    messages: {
      noSecretInLog:
        "Secret `{{name}}` passed to a logging call leaks it to log sinks. Redact (e.g. `{{name}}Prefix: {{name}}.slice(0, 6)`) or omit it.",
      noRawBodyInLog:
        "Raw `{{name}}` passed to a logging call. Request/response blobs carry PII and often echo credentials back, and log sinks have no retention policy. Log a derived value instead (a status, `{{name}}.id`, a length, a truncated issue list) or pass it through a redactor (`redact({{name}})`).",
    },
  },
  defaultOptions: [{}],
  create(context, [loggingOptions]) {
    const matcher = createLogMatcher(loggingOptions);
    // Bodies in a test file are fixtures the author wrote, not production PII.
    const blobArmApplies = !isTestFile(context.filename);

    /** Reports a bare positional argument that IS the secret. Did it fire? */
    function reportSecretArgument(arg: TSESTree.Node): boolean {
      const name =
        arg.type === "Identifier"
          ? arg.name
          : arg.type === "MemberExpression" &&
              !arg.computed &&
              arg.property.type === "Identifier"
            ? arg.property.name
            : null;
      if (name === null || !isSecretKeyword(name)) {
        return false;
      }
      context.report({ node: arg, messageId: "noSecretInLog", data: { name } });
      return true;
    }

    /** Reports a meta-object property whose key names a secret it carries raw. Did it fire? */
    function reportSecretProperty(prop: TSESTree.Property): boolean {
      const keyName = propertyKeyName(prop);
      if (keyName === null || !isSecretKeyword(keyName) || !isRawSecretValue(prop)) {
        return false;
      }
      context.report({ node: prop, messageId: "noSecretInLog", data: { name: keyName } });
      return true;
    }

    /** Reports `node` when `value` carries an un-redacted request/response blob. */
    function reportRawBlob(node: TSESTree.Node, value: TSESTree.Node): void {
      if (!blobArmApplies) {
        return;
      }
      const name = rawBlobValueName(value);
      if (name !== null) {
        context.report({ node, messageId: "noRawBodyInLog", data: { name } });
      }
    }

    return {
      CallExpression(node: TSESTree.CallExpression): void {
        if (!matcher.isLoggingCall(node)) {
          return;
        }

        for (const arg of node.arguments) {
          if (arg.type === "ObjectExpression") {
            for (const prop of arg.properties) {
              if (prop.type !== "Property") {
                continue;
              }
              if (!reportSecretProperty(prop)) {
                reportRawBlob(prop, prop.value);
              }
            }
            continue;
          }
          if (!reportSecretArgument(arg)) {
            reportRawBlob(arg, arg);
          }
        }
      },
    };
  },
});
