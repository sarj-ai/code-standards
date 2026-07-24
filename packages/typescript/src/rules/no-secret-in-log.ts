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
 * `passwordEnabled`), so metadata *about* a secret is not mistaken for the
 * secret itself. Redaction markers (prefix/mask/hash/redact/tag) are exempt.
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

type MessageIds = "noSecretInLog";
type Options = readonly [LoggingOptions?];

const SECRET_WORDS: ReadonlySet<string> = new Set([
  "token",
  "secret",
  "password",
  "passwd",
  "jwt",
  "secrets",
  "passwords",
  "credential",
  "credentials",
  "authorization",
  "signature",
  "hmac",
  "digest",
  "hash",
  "apikey",
]);

const INNOCUOUS_WORDS: ReadonlySet<string> = new Set([
  "count",
  "counts",
  "budget",
  "limit",
  "limits",
  "id",
  "ids",
  "enabled",
  "disabled",
  "flag",
  "flags",
  "present",
  "set",
  "unset",
  "configured",
  "missing",
  "required",
  "valid",
  "invalid",
  "exists",
  "type",
  "types",
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

const CAMEL_RE = /[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+/g;
const SEGMENT_RE = /[^A-Za-z0-9]+/;

/**
 * Ordered lowercase tokens from snake_case + camelCase decomposition. Also
 * yields each whole snake/kebab segment lowercased, so a pathological mixed-case
 * word still surfaces its intended form.
 */
function tokenize(identifier: string): string[] {
  const tokens: string[] = [];
  for (const segment of identifier.split(SEGMENT_RE)) {
    if (!segment) {
      continue;
    }
    tokens.push(segment.toLowerCase());
    for (const part of segment.match(CAMEL_RE) ?? []) {
      tokens.push(part.toLowerCase());
    }
  }
  return tokens;
}

/** True if `api` is immediately followed by `key` (the split form of `api_key`). */
function hasApiKey(tokens: readonly string[]): boolean {
  for (let i = 0; i + 1 < tokens.length; i++) {
    if (tokens[i] === "api" && tokens[i + 1] === "key") {
      return true;
    }
  }
  return false;
}

/** True if `identifier` names raw secret material (a credential, not metadata). */
function isSecretName(identifier: string): boolean {
  const tokens = tokenize(identifier);
  const last = tokens.at(-1);
  if (last !== undefined && INNOCUOUS_WORDS.has(last)) {
    return false;
  }
  if (tokens.some((tok) => SECRET_WORDS.has(tok))) {
    return true;
  }
  return hasApiKey(tokens);
}

/** True if the name names a raw secret and is not a redacted derivative. */
function isSecretKeyword(name: string): boolean {
  if (REDACTION_RE.test(name)) {
    return false;
  }
  if (tokenize(name).some((tok) => WHOLE_TOKEN_REDACTION_MARKERS.has(tok))) {
    return false;
  }
  return isSecretName(name);
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
        "Disallow passing a secret-named value to a logging call; it leaks to log sinks. Redact or omit it.",
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
    },
  },
  defaultOptions: [{}],
  create(context, [loggingOptions]) {
    const matcher = createLogMatcher(loggingOptions);

    return {
      CallExpression(node: TSESTree.CallExpression): void {
        if (!matcher.isLoggingCall(node)) {
          return;
        }

        for (const arg of node.arguments) {
          if (arg.type === "Identifier") {
            if (isSecretKeyword(arg.name)) {
              context.report({
                node: arg,
                messageId: "noSecretInLog",
                data: { name: arg.name },
              });
            }
            continue;
          }
          if (arg.type === "MemberExpression") {
            if (
              !arg.computed &&
              arg.property.type === "Identifier" &&
              isSecretKeyword(arg.property.name)
            ) {
              context.report({
                node: arg,
                messageId: "noSecretInLog",
                data: { name: arg.property.name },
              });
            }
            continue;
          }
          if (arg.type === "ObjectExpression") {
            for (const prop of arg.properties) {
              if (prop.type !== "Property") {
                continue;
              }
              const keyName = propertyKeyName(prop);
              if (keyName !== null && isSecretKeyword(keyName) && isRawSecretValue(prop)) {
                context.report({
                  node: prop,
                  messageId: "noSecretInLog",
                  data: { name: keyName },
                });
              }
            }
          }
        }
      },
    };
  },
});
