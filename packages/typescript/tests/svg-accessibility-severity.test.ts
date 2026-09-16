import * as parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import { describe, expect, it } from "vitest";

import plugin from "../src/index.js";

describe("SVG accessibility enforcement", () => {
  it.each(["recommended", "strict"] as const)(
    "%s rejects unnamed SVGs",
    (preset) => {
      const config: Linter.Config = {
        files: ["**/*.tsx"],
        languageOptions: {
          parser,
          parserOptions: { ecmaFeatures: { jsx: true } },
        },
        plugins: { "@sarj": plugin },
        rules: {
          "@sarj/require-svg-accessible-name":
            plugin.configs[preset].rules["@sarj/require-svg-accessible-name"],
        },
      };
      const linter = new Linter();
      const messages = linter.verify("<svg><path /></svg>", config, {
        filename: "src/view.tsx",
      });
      expect(
        messages.map(({ ruleId, severity }) => ({ ruleId, severity })),
      ).toEqual([{ ruleId: "@sarj/require-svg-accessible-name", severity: 2 }]);
      expect(
        linter.verify('<svg aria-hidden="true"><path /></svg>', config, {
          filename: "src/view.tsx",
        }),
      ).toEqual([]);
      expect(
        linter.verify("<svg><title>Revenue</title><path /></svg>", config, {
          filename: "src/view.tsx",
        }),
      ).toEqual([]);
    },
  );
});
