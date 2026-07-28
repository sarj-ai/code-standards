import { ESLint } from "eslint";
import * as path from "path";
import * as url from "url";
import * as fs from "fs";
import * as tsParser from "@typescript-eslint/parser";

const __dirname = path.dirname(url.fileURLToPath(import.meta.url));
import plugin from "./dist/index.js";

async function run() {
  const repoPath = process.argv[2];
  if (!repoPath) {
    console.error("Please provide a repo path");
    process.exit(1);
  }

  console.log(`Running analysis on ${repoPath}...`);

  const eslint = new ESLint({
    cwd: repoPath,
    overrideConfigFile: true,
    overrideConfig: [{
      files: ["**/*.{ts,tsx,jsx}"],
      plugins: { "@sarj": plugin },
      languageOptions: {
        parser: tsParser,
        parserOptions: {
          ecmaFeatures: { jsx: true },
        },
      },
      rules: {
        "@sarj/no-monolithic-components": "error",
        "@sarj/require-empty-state-prop": "error",
        "@sarj/require-interactive-states": "error",
        "@sarj/require-text-balance": "error",
        "@sarj/theme-no-raw-colors": "error",
      },
    }],
    ignore: false,
    errorOnUnmatchedPattern: false,
  });

  const target = path.join(repoPath, "**/*.{ts,tsx,jsx}");
  
  try {
    const results = await eslint.lintFiles([target]);
    
    const ruleCounts = {
      "@sarj/no-monolithic-components": 0,
      "@sarj/require-empty-state-prop": 0,
      "@sarj/require-interactive-states": 0,
      "@sarj/require-text-balance": 0,
      "@sarj/theme-no-raw-colors": 0,
    };

    let totalFiles = 0;
    for (const result of results) {
      if (result.messages.length > 0) totalFiles++;
      for (const msg of result.messages) {
        if (msg.ruleId && ruleCounts[msg.ruleId] !== undefined) {
          ruleCounts[msg.ruleId]++;
        }
      }
    }

    console.log(JSON.stringify(ruleCounts, null, 2));
  } catch (err) {
    console.error("Error linting:", err);
  }
}

run();
