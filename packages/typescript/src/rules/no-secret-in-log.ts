/**
 * @fileoverview no-secret-in-log — a secret passed to a logging call persists in log sinks far beyond its intended lifetime.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-secret-in-log.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import {
  createLogMatcher,
  LOGGING_OPTION_PROPERTIES,
  type LoggingOptions,
} from "./_logging.js";
import { createRule } from "./_docs.js";
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
