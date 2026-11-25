import stylelint, { type Rule } from "stylelint";
import type { Declaration } from "postcss";
import { ident, parse, walk, type Value } from "@eslint/css-tree";

const NAME = "@sarj/no-modern-shorthand-reset";
const INITIAL: ReadonlySet<string> = new Set([
  "auto",
  "normal",
  "normal normal",
  "initial",
  "unset",
]);
const UNKNOWN: ReadonlySet<string> = new Set(["inherit", "revert", "revert-layer", "revert-rule"]);
const SHORTHANDS: ReadonlyMap<string, string> = new Map([
  ["transition-behavior", "transition"],
  ["animation-timeline", "animation"],
  ["animation-range", "animation"],
  ["animation-range-start", "animation"],
  ["animation-range-end", "animation"],
]);

function keyword(name: string): string {
  return (name.includes("\\") ? ident.decode(name) : name).toLowerCase();
}

function restores(property: string, later: string): boolean {
  return (
    later === property || (property.startsWith("animation-range-") && later === "animation-range")
  );
}

function resetBy(
  property: string,
  longhand: Declaration,
  shorthand: Declaration,
  declarations: readonly Declaration[],
): boolean {
  if (longhand.important && !shorthand.important) return false;
  const index = declarations.indexOf(shorthand);
  if (index < declarations.indexOf(longhand)) return false;
  if (keyword(shorthand.value.trim()) === "none" || INITIAL.has(keyword(longhand.value.trim())))
    return false;
  const shortValue = knownValue(shorthand.value);
  const longValue = knownValue(longhand.value);
  if (!shortValue || !longValue) return false;
  if (
    property === "transition-behavior"
      ? !losesDiscreteBehavior(longValue, shortValue)
      : initialList(property, longValue)
  )
    return false;
  const later = declarations.slice(index + 1);
  if (
    later.some(
      (declaration) =>
        restores(property, keyword(declaration.prop)) &&
        (!shorthand.important || declaration.important),
    )
  )
    return false;
  if (
    property === "animation-range" &&
    ["animation-range-start", "animation-range-end"].every((endpoint) =>
      later.some(
        (declaration) =>
          keyword(declaration.prop) === endpoint && (!shorthand.important || declaration.important),
      ),
    )
  )
    return false;
  return true;
}

function losesDiscreteBehavior(longhand: Value, shorthand: Value): boolean {
  const previous = discreteBehaviors(longhand);
  if (!previous.includes(true)) return false;
  let index = 0;
  let discrete = false;
  for (const node of shorthand.children) {
    if (node.type === "Operator" && node.value === ",") {
      if (previous[index] && !discrete) return true;
      index = (index + 1) % previous.length;
      discrete = false;
    } else if (node.type === "Identifier" && keyword(node.name) === "allow-discrete") {
      discrete = true;
    }
  }
  return previous[index] === true && !discrete;
}

function discreteBehaviors(longhand: Value): boolean[] {
  const behaviors: boolean[] = [];
  let expectBehavior = true;
  for (const node of longhand.children) {
    if (expectBehavior) {
      if (node.type !== "Identifier") return [];
      const behavior = keyword(node.name);
      if (behavior !== "normal" && behavior !== "allow-discrete") return [];
      behaviors.push(behavior === "allow-discrete");
    } else if (node.type !== "Operator" || node.value !== ",") {
      return [];
    }
    expectBehavior = !expectBehavior;
  }
  return expectBehavior ? [] : behaviors;
}

function initialList(property: string, value: Value): boolean {
  const initial = property === "animation-timeline" ? "auto" : "normal";
  const limit = property === "animation-range" ? 2 : 1;
  let components = 0;
  for (const node of value.children) {
    if (node.type === "Operator" && node.value === "," && components > 0) {
      components = 0;
    } else if (node.type === "Identifier" && keyword(node.name) === initial && components < limit) {
      components += 1;
    } else {
      return false;
    }
  }
  return components > 0;
}

function knownValue(value: string): Value | undefined {
  if (UNKNOWN.has(keyword(value.trim()))) return undefined;
  try {
    const parsed = parse(value, { context: "value" });
    if (parsed.type !== "Value") return undefined;
    let substituted = false;
    walk(parsed, (node) => {
      if (node.type === "Function" && ["var", "env"].includes(keyword(node.name)))
        substituted = true;
    });
    return substituted ? undefined : parsed;
  } catch {
    return undefined;
  }
}

const rule: Rule = (enabled) => (root, result) => {
  if (!stylelint.utils.validateOptions(result, NAME, { actual: enabled })) return;
  root.walkRules((block) => {
    const declarations = block.nodes.filter((node) => node.type === "decl");
    const effective = new Map<string, (typeof declarations)[number]>();
    for (const declaration of declarations) {
      const property = keyword(declaration.prop);
      const previous = effective.get(property);
      if (!previous?.important || declaration.important) effective.set(property, declaration);
    }
    const reported = new Set<Declaration>();
    for (const [property, longhand] of effective) {
      const shorthand = SHORTHANDS.get(property);
      const reset = shorthand === undefined ? undefined : effective.get(shorthand);
      if (
        reset === undefined ||
        reported.has(reset) ||
        !resetBy(property, longhand, reset, declarations)
      )
        continue;
      reported.add(reset);
      stylelint.utils.report({
        ruleName: NAME,
        result,
        node: reset,
        word: reset.prop,
        message: `${reset.prop} resets ${longhand.prop}. Put the intended longhand after the shorthand.`,
      });
    }
  });
};
rule.ruleName = NAME;
rule.messages = { reset: "A later shorthand resets a modern longhand." };
rule.meta = {
  url: "https://github.com/sarj-ai/code-standards/tree/main/plugins/sarj-skills/skills/lint-rule-generator/references/modern-web-guidance.md",
};

export default stylelint.createPlugin(NAME, rule);
