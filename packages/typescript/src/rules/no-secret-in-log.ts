/**
 * @fileoverview no-secret-in-log — a secret passed to a logging call persists in log sinks far beyond its intended lifetime.
 *
 * Port of the 18.x `no-secret-in-log` rule. Same algorithm; options and
 * the test-file gate are read per file in `before()`.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { createLogMatcher, LOGGING_OPTION_PROPERTIES, type LoggingOptions, type LogMatcher } from "../utils/logging.js";
import { isTestFile } from "../utils/paths.js";
import { FLAG_PREFIXES, INNOCUOUS_WORDS, isSecretName, leadingWord, tokenize } from "../utils/secret-names.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";

const NAME = "no-secret-in-log";

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

const SECRET_REDACTION_TOKENS: ReadonlySet<string> = new Set([
  "prefix", "suffix", "redact", "redacted", "mask", "masked", "hash", "hashed", "hint", "len", "length", "tag",
]);

/** True if the name names a raw secret and is not a redacted derivative. */
function isSecretKeyword(name: string): boolean {
  return !hasRedactionMarker(name) && isSecretName(name, LOG_INNOCUOUS_WORDS);
}

function hasRedactionMarker(name: string): boolean {
  return tokenize(name).some((token) => SECRET_REDACTION_TOKENS.has(token));
}

function valueName(node: Node): string | null {
  if (node.type === "Identifier") return node.name;
  return node.type === "MemberExpression" ? getPropertyName(node) : null;
}

function isRawSecretValue(prop: ESTree.ObjectProperty): boolean {
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
 * Whole words that mark a blob name as an already-derived form:
 * `redactedBody`, `sanitizedPayload`, `truncatedBody`, `bodyPreview`.
 */
const BLOB_TRANSFORM_TOKENS: ReadonlySet<string> = new Set([
  "redact", "redacted", "sanitize", "sanitized", "scrub", "scrubbed", "mask", "masked",
  "truncate", "truncated", "anonymize", "anonymized", "filter", "filtered", "preview",
  "summarize", "summarized", "summary",
]);

/**
 * Derivation markers that are only safe when matched as a WHOLE token — `safe` as
 * a substring would wrongly exempt `unsafeBody`.
 */
const BLOB_SAFE_TOKENS: ReadonlySet<string> = new Set([
  "safe",
  "clean",
  "shape",
  "keys",
  "public",
]);

const RESPONSE_NAME_RE = /^(?:res|response|\w+Response)$/;

function rawBlobValueName(value: Node): string | null {
  if (value.type === "AwaitExpression") return rawBlobValueName(value.argument);
  if (value.type === "ChainExpression") return rawBlobValueName(value.expression);
  if (value.type === "Identifier") {
    return isRawBlobName(value.name) ? value.name : null;
  }
  if (value.type === "MemberExpression") {
    const name = getPropertyName(value);
    return name !== null && isRawBlobName(name) ? name : null;
  }
  if (value.type !== "CallExpression" || value.arguments.length !== 0) return null;
  const callee = unwrapExpression(value.callee);
  if (callee.type !== "MemberExpression" || callee.object.type !== "Identifier" ||
    !RESPONSE_NAME_RE.test(callee.object.name)) return null;
  const name = getPropertyName(callee);
  return name === "json" || name === "text" ? `${callee.object.name}.${name}()` : null;
}

/** True if the name names a raw request/response blob and is not a derived form. */
function isRawBlobName(name: string): boolean {
  const tokens = tokenize(name);
  if (tokens.some((tok) => SECRET_REDACTION_TOKENS.has(tok) || BLOB_TRANSFORM_TOKENS.has(tok) || BLOB_SAFE_TOKENS.has(tok))) {
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
function propertyKeyName(prop: ESTree.ObjectProperty): string | null {
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

export default defineRule({
  meta: {
    defaultOptions: [{}],
    type: "problem",
    docs: {
      description:
        "Disallow passing a secret-named value or a raw request/response blob to a logging call; both leak to log sinks. Redact or omit.",
      url: docsUrl(NAME),
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
  createOnce(context) {
    let matcher: LogMatcher;
    // Options arrive per file; rebuild the matcher only when they change.
    let matcherOptions: unknown;
    let blobArmApplies = false;

    function resolvesToGlobal(identifier: Node & { name: string }): boolean {
      const variable = findVariable(context.sourceCode.getScope(identifier), identifier.name);
      return variable === null || variable.defs.length === 0;
    }

    function inspectLoggedValue(value: Node): void {
      value = unwrapExpression(value);
      const input = transparentCallInput(value);
      if (input !== undefined) {
        if (input !== null) inspectLoggedValue(input);
        return;
      }
      if (value.type === "ObjectExpression") {
        inspectLoggedObject(value);
        return;
      }
      if (value.type === "ArrayExpression") {
        for (const element of value.elements) {
          if (element !== null && element.type !== "SpreadElement") inspectLoggedValue(element);
        }
        return;
      }
      if (value.type === "TemplateLiteral") {
        for (const expression of value.expressions) inspectLoggedValue(expression);
        return;
      }
      if (value.type === "BinaryExpression" && value.operator === "+") {
        inspectLoggedValue(value.left);
        inspectLoggedValue(value.right);
        return;
      }
      if (!reportSecretArgument(value)) reportRawBlob(value, value);
    }

    /** Undefined means opaque; null means a transparent call with no logged bytes. */
    function transparentCallInput(value: Node): Node | null | undefined {
      if (value.type !== "CallExpression") return undefined;
      const callee = unwrapExpression(value.callee);
      if (callee.type !== "MemberExpression" || value.arguments.some((arg) => arg.type === "SpreadElement")) return undefined;
      const object = unwrapExpression(callee.object);
      const method = getPropertyName(callee);
      if (method === "stringify" && isGlobalJson(object) && hasNoReplacer(value.arguments[1])) return value.arguments[0] ?? null;
      if (method === "slice" || method === "substring" || method === "substr") {
        return isEmptyTruncation(method, value.arguments) ? null : object;
      }
      return undefined;
    }

    function isGlobalJson(node: Node): boolean {
      return node.type === "Identifier" && node.name === "JSON" && resolvesToGlobal(node);
    }

    function hasNoReplacer(replacer: Node | undefined): boolean {
      return replacer === undefined ||
        (replacer.type === "Literal" && replacer.value === null) ||
        (replacer.type === "Identifier" && replacer.name === "undefined" && resolvesToGlobal(replacer)) ||
        (replacer.type === "UnaryExpression" && replacer.operator === "void");
    }

    function isEmptyTruncation(method: string, args: Node[]): boolean {
      const [start, end] = args;
      if (end?.type !== "Literal" || typeof end.value !== "number" || !Number.isFinite(end.value)) return false;
      if (method === "substr") return end.value <= 0;
      return start?.type === "Literal" && typeof start.value === "number" && start.value === end.value;
    }

    function inspectLoggedObject(value: ESTree.ObjectExpression): void {
      for (const property of literalProperties(value)) {
        if (reportSecretProperty(property) || reportRawBlob(property, property.value)) continue;
        inspectLoggedValue(property.value);
      }
    }

    function literalProperties(value: ESTree.ObjectExpression): ESTree.ObjectProperty[] {
      const effective = new Map<string, ESTree.ObjectProperty>();
      for (const entry of value.properties) {
        if (entry.type === "SpreadElement") {
          if (entry.argument.type !== "ObjectExpression") {
            effective.clear();
            continue;
          }
          for (const property of literalProperties(entry.argument)) {
            const key = propertyKeyName(property);
            if (key !== null) effective.set(key, property);
          }
          continue;
        }
        const key = propertyKeyName(entry);
        if (key === null) {
          effective.clear();
          continue;
        }
        effective.set(key, entry);
      }
      return [...effective.values()];
    }

    /** Reports `node` when `value` carries an un-redacted request/response blob. */
    function reportRawBlob(node: Node, value: Node): boolean {
      if (!blobArmApplies) {
        return false;
      }
      const name = rawBlobValueName(value);
      if (name !== null) {
        context.report({ node, messageId: "noRawBodyInLog", data: { name } });
        return true;
      }
      return false;
    }

    function reportSecretProperty(prop: ESTree.ObjectProperty): boolean {
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

    function reportSecretArgument(arg: Node): boolean {
      const name = valueName(arg);
      if (name === null || !isSecretKeyword(name)) {
        return false;
      }
      context.report({ node: arg, messageId: "noSecretInLog", data: { name } });
      return true;
    }

    return {
      before(): void {
        const [loggingOptions] = context.options as unknown as readonly [LoggingOptions?];
        if (matcher === undefined || loggingOptions !== matcherOptions) {
          matcher = createLogMatcher(loggingOptions);
          matcherOptions = loggingOptions;
        }
        // Bodies in a test file are fixtures the author wrote, not production PII.
        blobArmApplies = !isTestFile({ filename: context.filename, cwd: context.cwd });
      },
      CallExpression(node: ESTree.CallExpression): void {
        if (!matcher.isLoggingCall(node)) {
          return;
        }

        for (const arg of node.arguments) {
          if (arg.type !== "SpreadElement") inspectLoggedValue(arg);
        }
      },
    };
  },
});
