import * as parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import { describe, expect, it } from "vitest";

import plugin from "../src/index.js";

const POLICY_RULES = ["@sarj/prefer-logical-tailwind-utilities"] as const;
const SOURCE =
  'import { toast } from "sonner"; toast.success("Saved"); const view = <div className="ml-2" title="Greeting">Hello</div>;';

describe("localized UI policy activation", () => {
  it.each(["recommended", "strict"] as const)(
    "%s leaves English-only consumers unchanged until opt-in",
    (preset) => {
      const rules = Object.fromEntries(
        POLICY_RULES.map((name) => [name, plugin.configs[preset].rules[name]]),
      );
      const linter = new Linter();
      const config: Linter.Config = {
        files: ["**/*.tsx"],
        languageOptions: {
          parser,
          parserOptions: { ecmaFeatures: { jsx: true } },
        },
        plugins: { "@sarj": plugin },
        rules,
      };
      expect(
        linter.verify(SOURCE, config, { filename: "src/view.tsx" }),
      ).toEqual([]);
      const enabled: Linter.Config = {
        files: ["**/*.tsx"],
        rules: Object.fromEntries(
          POLICY_RULES.map((name) => [name, ["warn", { enabled: true }]]),
        ),
      };
      const messages = linter.verify(SOURCE, [config, enabled], {
        filename: "src/view.tsx",
      });
      expect(messages.map((message) => message.ruleId).toSorted()).toEqual(
        [...POLICY_RULES].toSorted(),
      );
      expect(messages.every((message) => message.severity === 1)).toBe(true);
    },
  );
});
