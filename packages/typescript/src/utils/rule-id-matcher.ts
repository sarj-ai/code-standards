/**
 * @fileoverview rule-id-matcher — match rule IDs against gitignore-style patterns.
 *
 * `@eslint-community/eslint-comments/no-restricted-disable` matches rule IDs
 * with the `ignore` package, so its options are gitignore patterns over rule
 * IDs read as paths: `foo/*` matches every rule of plugin `foo`, a pattern
 * without a slash matches the last segment at any depth (`no-console` also
 * matches `eslint/no-console`), `!` re-allows, and the last matching pattern
 * wins. As in gitignore, a pattern that matches a plugin prefix matches its
 * rules, and a later `!` pattern cannot re-allow a rule under that prefix.
 */

interface Pattern {
  readonly negated: boolean;
  /** A trailing `/` makes the pattern match only plugin prefixes. */
  readonly prefixOnly: boolean;
  readonly regex: RegExp;
}

/** A predicate that is true for the rule IDs `patterns` match. */
export function ruleIdMatcher(patterns: readonly string[]): (ruleId: string) => boolean {
  const compiled = patterns.flatMap(compile);
  const matches = (path: string, isPrefix: boolean): boolean => {
    let matched = false;
    for (const pattern of compiled) {
      if ((isPrefix || !pattern.prefixOnly) && pattern.regex.test(path)) matched = !pattern.negated;
    }
    return matched;
  };
  return (ruleId) => {
    const segments = ruleId.split("/");
    for (let end = 1; end < segments.length; end++) {
      if (matches(segments.slice(0, end).join("/"), true)) return true;
    }
    return matches(ruleId, false);
  };
}

function compile(source: string): Pattern[] {
  let text = source.replace(/(?<!\\)\s+$/u, "");
  if (text === "" || text.startsWith("#")) return [];
  const negated = text.startsWith("!");
  if (negated) text = text.slice(1);
  text = text.replace(/^\\(?=[!#])/u, "");
  const prefixOnly = text.endsWith("/");
  if (prefixOnly) text = text.slice(0, -1);
  // A slash at the start or in the middle anchors the pattern at the first segment.
  const anchored = text.includes("/");
  text = text.replace(/^\//u, "");
  const body = translate(text);
  return [{ negated, prefixOnly, regex: new RegExp(`^${anchored ? "" : "(?:.*/)?"}${body}$`, "u") }];
}

/** Translate gitignore glob syntax: `**` spans segments, `*` and `?` stay inside one, `[...]` is a class. */
function translate(glob: string): string {
  const out: string[] = [];
  for (let index = 0; index < glob.length; index++) {
    const char = glob.charAt(index);
    if (glob.startsWith("**/", index) && (index === 0 || glob[index - 1] === "/")) {
      out.push("(?:.*/)?");
      index += 2;
    } else if (glob.startsWith("**", index) && index + 2 === glob.length && (index === 0 || glob[index - 1] === "/")) {
      out.push(".*");
      index += 1;
    } else if (char === "*") {
      out.push("[^/]*");
    } else if (char === "?") {
      out.push("[^/]");
    } else if (char === "\\" && index + 1 < glob.length) {
      index += 1;
      out.push(escapeChar(glob.charAt(index)));
    } else if (char === "[" && glob.indexOf("]", index + 2) !== -1) {
      const close = glob.indexOf("]", index + 2);
      const members = glob.slice(index + 1, close);
      out.push(`[${members.startsWith("!") ? `^${members.slice(1)}` : members}]`);
      index = close;
    } else {
      out.push(escapeChar(char));
    }
  }
  return out.join("");
}

function escapeChar(char: string): string {
  return /[$()*+.?[\\\]^{|}/]/u.test(char) ? `\\${char}` : char;
}
