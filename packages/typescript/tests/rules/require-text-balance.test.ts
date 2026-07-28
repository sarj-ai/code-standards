import { RuleTester } from '@typescript-eslint/rule-tester';
import { requireTextBalance } from '../../src/rules/require-text-balance';
import { afterAll, describe, it } from 'vitest';
import * as tsParser from '@typescript-eslint/parser';

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: {
      ecmaFeatures: { jsx: true },
    },
  },
});

ruleTester.run('require-text-balance', requireTextBalance, {
  valid: [
    { code: '<h1 className="text-balance">Title</h1>' },
    { code: '<h2 className="text-balance font-bold">Subtitle</h2>' },
    { code: '<p className="text-pretty">Paragraph</p>' },
    { code: '<p className="text-sm text-pretty text-gray-500">Paragraph</p>' },
    { code: '<div>Container</div>' },
    { code: '<span className="text-bold">Span</span>' },
    { code: '<h3 className={"text-balance"}>Heading</h3>' },
    { code: '<p className={`text-pretty ${otherClass}`}>Dynamic</p>' },
  ],
  invalid: [
    {
      code: '<h1>Title</h1>',
      errors: [{ messageId: 'missingTextBalance' }],
      output: '<h1 className="text-balance">Title</h1>',
    },
    {
      code: '<h2 className="font-bold">Subtitle</h2>',
      errors: [{ messageId: 'missingTextBalance' }],
      output: '<h2 className="font-bold text-balance">Subtitle</h2>',
    },
    {
      code: '<p>Paragraph</p>',
      errors: [{ messageId: 'missingTextPretty' }],
      output: '<p className="text-pretty">Paragraph</p>',
    },
    {
      code: '<p className="text-sm text-gray-500">Paragraph</p>',
      errors: [{ messageId: 'missingTextPretty' }],
      output: '<p className="text-sm text-gray-500 text-pretty">Paragraph</p>',
    },
    {
      code: '<h4 className={`font-bold`}>Heading 4</h4>',
      errors: [{ messageId: 'missingTextBalance' }],
    },
  ],
});
