import stylelint, { type Rule } from "stylelint";
import type { Declaration } from "postcss";
import { parse, walk } from "@eslint/css-tree";

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

function restores(property: string, later: string): boolean {
  return (
    later === property || (property.startsWith("animation-range-") && later === "animation-range")
  );
}

function resetBy(
  longhand: Declaration,
  shorthand: Declaration,
  declarations: readonly Declaration[],
): boolean {
  if (longhand.important && !shorthand.important) return false;
  const index = declarations.indexOf(shorthand);
  if (index < declarations.indexOf(longhand)) return false;
  const value = shorthand.value.trim().toLowerCase();
  if (
    value === "none" ||
    INITIAL.has(longhand.value.trim().toLowerCase()) ||
    hasUnknownValue(value) ||
    hasUnknownValue(longhand.value)
  )
    return false;
  if (
    declarations
      .slice(index + 1)
      .some(
        (declaration) =>
          restores(longhand.prop.toLowerCase(), declaration.prop.toLowerCase()) &&
          (!shorthand.important || declaration.important),
      )
  )
    return false;
  if (
    longhand.prop.toLowerCase() === "animation-range" &&
    ["animation-range-start", "animation-range-end"].every((property) =>
      declarations
        .slice(index + 1)
        .some(
          (declaration) =>
            declaration.prop.toLowerCase() === property &&
            (!shorthand.important || declaration.important),
        ),
    )
  )
    return false;
  let discrete = false;
  if (shorthand.prop.toLowerCase() === "transition") {
    walk(parse(value, { context: "value" }), (node) => {
      if (node.type === "Identifier" && node.name.toLowerCase() === "allow-discrete")
        discrete = true;
    });
  }
  return !discrete;
}

function hasUnknownValue(value: string): boolean {
  let unknown = UNKNOWN.has(value);
  try {
    walk(parse(value, { context: "value" }), (node) => {
      if (node.type === "Function" && ["var", "env"].includes(node.name.toLowerCase()))
        unknown = true;
    });
  } catch {
    unknown = true;
  }
  return unknown;
}

const rule: Rule = (enabled) => (root, result) => {
  if (!stylelint.utils.validateOptions(result, NAME, { actual: enabled })) return;
  root.walkRules((block) => {
    const declarations = block.nodes.filter((node) => node.type === "decl");
    const effective = new Map<string, (typeof declarations)[number]>();
    for (const declaration of declarations) {
      const property = declaration.prop.toLowerCase();
      const previous = effective.get(property);
      if (!previous?.important || declaration.important) effective.set(property, declaration);
    }
    const reported = new Set<Declaration>();
    for (const [property, longhand] of effective) {
      const shorthand = SHORTHANDS.get(property);
      const reset = shorthand === undefined ? undefined : effective.get(shorthand);
      if (reset === undefined || reported.has(reset) || !resetBy(longhand, reset, declarations))
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
