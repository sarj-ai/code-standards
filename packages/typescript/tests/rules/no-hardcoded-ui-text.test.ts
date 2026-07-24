import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-hardcoded-ui-text.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaFeatures: { jsx: true } },
  },
});

const TSX = "/repo/src/components/widget.tsx";

ruleTester.run("no-hardcoded-ui-text", rule, {
  valid: [
    // Translated text is the prescribed pattern.
    { code: "const x = <p>{t('welcome.title')}</p>;", filename: TSX },
    {
      code: "const x = <input placeholder={t('search.placeholder')} />;",
      filename: TSX,
    },
    // Arabic already inside an i18n callee (default: t, i18n.t).
    {
      code: "const x = t('key', { defaultValue: 'مرحبا بك' });",
      filename: TSX,
    },
    {
      code: "const label = i18n.t('مفتاح');",
      filename: TSX,
    },
    // Custom i18nCallees option.
    {
      code: "const label = translate('أهلا وسهلا');",
      filename: TSX,
      options: [{ i18nCallees: ["translate"] }],
    },
    // Single word in JSXText is below the 2-word threshold (brand names, "OK").
    { code: "const x = <span>Bulbul</span>;", filename: TSX },
    // Punctuation / whitespace-only JSXText.
    { code: "const x = <span> — </span>;", filename: TSX },
    // Non-copy attributes are skipped even with multi-word values.
    {
      code: 'const x = <div className="flex items-center gap-2" />;',
      filename: TSX,
    },
    {
      code: 'const x = <div data-testid="main panel" id="root node" />;',
      filename: TSX,
    },
    // Single-word attribute copy is below threshold.
    { code: 'const x = <img alt="logo" />;', filename: TSX },
    // Multi-word literals outside JSX attributes and without Arabic are out of
    // scope (log messages, error strings, keys).
    {
      code: "logger.info('call completed with status ok');",
      filename: TSX,
    },
    // Latin string literals in plain .ts files are out of scope.
    {
      code: "const message = 'welcome to the dashboard';",
      filename: "/repo/src/lib/messages.ts",
    },
    // Arabic detector only applies to JSX files.
    {
      code: "const s = 'مرحبا';",
      filename: "/repo/src/lib/vocab-test-fixtures.ts",
    },
    // Type positions are never copy.
    {
      code: "type Status = 'active' | 'inactive';",
      filename: TSX,
    },
    // Test and stories files are skipped wholesale.
    {
      code: "const x = <p>Sign in to continue</p>;",
      filename: "/repo/src/components/widget.test.tsx",
    },
    {
      code: "const x = <p>Sign in to continue</p>;",
      filename: "/repo/src/components/widget.stories.tsx",
    },
    {
      code: "const x = <p>Sign in to continue</p>;",
      filename: "/repo/src/components/__tests__/widget.tsx",
    },
  ],
  invalid: [
    // (a) Multi-word JSXText.
    {
      code: "const x = <p>Sign in to continue</p>;",
      filename: TSX,
      errors: [{ messageId: "hardcodedJsxText" }],
    },
    // (a) Arabic JSXText.
    {
      code: "const x = <p>مرحبا بك</p>;",
      filename: TSX,
      errors: [{ messageId: "hardcodedJsxText" }],
    },
    // (b) Arabic string literal anywhere in a .tsx file.
    {
      code: "const label = active ? 'نشط' : 'غير نشط';",
      filename: TSX,
      errors: [{ messageId: "arabicLiteral" }, { messageId: "arabicLiteral" }],
    },
    // (b) Arabic in a copy attribute reports the attribute (single word →
    // not the two-word attribute detector, but Arabic still fires).
    {
      code: "const x = <input placeholder=\"ابحث\" />;",
      filename: TSX,
      errors: [{ messageId: "arabicLiteral" }],
    },
    // (c) Multi-word copy attributes.
    {
      code: 'const x = <input placeholder="Search for calls" />;',
      filename: TSX,
      errors: [{ messageId: "hardcodedAttribute" }],
    },
    {
      code: "const x = <button aria-label={'Close the dialog'} />;",
      filename: TSX,
      errors: [{ messageId: "hardcodedAttribute" }],
    },
    {
      code: 'const x = <img alt="Company logo mark" title="Our logo" />;',
      filename: TSX,
      errors: [
        { messageId: "hardcodedAttribute" },
        { messageId: "hardcodedAttribute" },
      ],
    },
    // Arabic two-word value in a copy attribute reports as attribute copy.
    {
      code: 'const x = <input placeholder="ابحث عن مكالمة" />;',
      filename: TSX,
      errors: [{ messageId: "hardcodedAttribute" }],
    },
  ],
});
