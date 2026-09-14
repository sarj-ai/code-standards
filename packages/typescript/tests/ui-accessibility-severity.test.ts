import * as parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import { describe, expect, it } from "vitest";

import plugin from "../src/index.js";

const SOURCE =
  'import { X } from "lucide-react"; const view = <><button><X /></button><Button><X /></Button></>;';

describe("accessibility enforcement", () => {
  it.each(["recommended", "strict"] as const)(
    "%s rejects unnamed button and Button controls",
    (preset) => {
      const config: Linter.Config = {
        files: ["**/*.tsx"],
        languageOptions: {
          parser,
          parserOptions: { ecmaFeatures: { jsx: true } },
        },
        plugins: { "@sarj": plugin },
        rules: {
          "@sarj/require-button-accessible-name":
            plugin.configs[preset].rules[
              "@sarj/require-button-accessible-name"
            ],
        },
      };
      const linter = new Linter();
      const messages = linter.verify(SOURCE, config, {
        filename: "src/view.tsx",
      });
      expect(
        messages.map(({ ruleId, severity }) => ({ ruleId, severity })),
      ).toEqual([
        { ruleId: "@sarj/require-button-accessible-name", severity: 2 },
        { ruleId: "@sarj/require-button-accessible-name", severity: 2 },
      ]);
      const named = SOURCE.replaceAll(
        "<button>",
        '<button aria-label="Close">',
      ).replaceAll("<Button>", '<Button aria-label="Close">');
      expect(
        linter.verify(named, config, { filename: "src/view.tsx" }),
      ).toEqual([]);
    },
  );
});
