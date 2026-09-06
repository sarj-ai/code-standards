/**
 * @fileoverview no-secret-in-log — a secret passed to a logging call persists in log sinks far beyond its intended lifetime.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-secret-in-log.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import {
  createLogMatcher,
  LOGGING_OPTION_PROPERTIES,
  type LoggingOptions,
} from "./_logging.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";
import {
  FLAG_PREFIXES,
  INNOCUOUS_WORDS,
  isSecretName,
  leadingWord,
  tokenize,
} from "./_secret-names.js";

type MessageIds = "noSecretInLog" | "noRawBodyInLog";
type Options = readonly [LoggingOptions?];

export const NO_SECRET_IN_LOG_DOCUMENTATION = {
  summary: "Disallow passing a secret-named value or a raw request/response blob to a logging call; both leak to log sinks. Redact or omit.",
  rationale: "Logs are widely retained and distributed, so credentials and raw bodies can become durable data leaks.",
  remediation: "Omit the value, log allowlisted non-sensitive context, or use an approved redactor; truncation alone is not a safety guarantee.",
  category: "security",
  limitations: ["Detection uses configurable logger names and statically recognizable secret names, raw-body names, and redaction markers. Name-based exemptions are policy heuristics, not proof that a value is safely redacted."],
  examples: [
    { id: "redacted-secret", title: "Log non-sensitive context instead of the secret", outcome: "no-match", files: [{ path: "src/auth.ts", source: "logger.info('auth', { requestId });" }], focusPath: "src/auth.ts", expectedCount: 0, public: true },
    { id: "logged-secret", title: "Do not send a secret to logs", outcome: "match", files: [{ path: "src/auth.ts", source: "logger.error('auth failed', { token });" }], focusPath: "src/auth.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

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
  return !hasRedactionMarker(name) && isSecretName(name, LOG_INNOCUOUS_WORDS);
}

function hasRedactionMarker(name: string): boolean {
  return REDACTION_RE.test(name) || tokenize(name).some((tok) => WHOLE_TOKEN_REDACTION_MARKERS.has(tok));
}

function valueName(node: TSESTree.Node): string | null {
  if (node.type === "Identifier") return node.name;
  return node.type === "MemberExpression" && !node.computed && node.property.type === "Identifier" ? node.property.name : null;
}

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

function rawBlobValueName(value: TSESTree.Node): string | null {
  if (value.type === "AwaitExpression") return rawBlobValueName(value.argument);
  if (value.type === "ChainExpression") return rawBlobValueName(value.expression);
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
  if (
    value.type === "CallExpression" &&
    value.arguments.length === 0 &&
    value.callee.type === "MemberExpression" &&
    !value.callee.computed &&
    value.callee.object.type === "Identifier" &&
    /^(?:res|response|\w+Response)$/.test(value.callee.object.name) &&
    value.callee.property.type === "Identifier" &&
    (value.callee.property.name === "json" || value.callee.property.name === "text")
  ) {
    return `${value.callee.object.name}.${value.callee.property.name}()`;
  }
  return null;
}

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

export default createRule<Options, MessageIds>({
  name: "no-secret-in-log",
  documentation: NO_SECRET_IN_LOG_DOCUMENTATION,
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
        "Secret-like `{{name}}` passed to a logging call. Omit it or use an approved redactor; a prefix can expose an entire short secret.",
      noRawBodyInLog:
        "Raw `{{name}}` passed to a logging call. Request/response bodies can contain personal data or credentials. Log allowlisted non-sensitive context or use an approved redactor.",
    },
  },
  defaultOptions: [{}],
  create(context, [loggingOptions]) {
    const matcher = createLogMatcher(loggingOptions);
    // Bodies in a test file are fixtures the author wrote, not production PII.
    const blobArmApplies = !isTestFile(context.filename);

    function reportSecretArgument(arg: TSESTree.Node): boolean {
      const name = valueName(arg);
      if (name === null || !isSecretKeyword(name)) {
        return false;
      }
      context.report({ node: arg, messageId: "noSecretInLog", data: { name } });
      return true;
    }

    function reportSecretProperty(prop: TSESTree.Property): boolean {
      const keyName = propertyKeyName(prop);
      const value = valueName(prop.value);
      if (value !== null && hasRedactionMarker(value)) return false;
      const name = value !== null && isSecretKeyword(value) ? value : keyName;
      if (name === null || !isSecretKeyword(name) || !isRawSecretValue(prop)) {
        return false;
      }
      context.report({ node: prop, messageId: "noSecretInLog", data: { name } });
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
