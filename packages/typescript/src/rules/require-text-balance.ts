import { TSESLint, TSESTree } from '@typescript-eslint/utils';

const requireTextBalance: TSESLint.RuleModule<
  'missingTextBalance' | 'missingTextPretty',
  []
> = {
  meta: {
    type: 'suggestion',
    docs: {
      description: 'Enforce text-balance on headings and text-pretty on paragraphs',
    },
    fixable: 'code',
    schema: [],
    messages: {
      missingTextBalance: 'Heading tags (h1-h6) should include the Tailwind class "text-balance".',
      missingTextPretty: 'Paragraph tags (<p>) should include the Tailwind class "text-pretty".',
    },
  },
  defaultOptions: [],
  create(context) {
    return {
      JSXOpeningElement(node: TSESTree.JSXOpeningElement) {
        if (node.name.type !== 'JSXIdentifier') {
          return;
        }

        const tagName = node.name.name;
        const isHeading = /^h[1-6]$/.test(tagName);
        const isParagraph = tagName === 'p';

        if (!isHeading && !isParagraph) {
          return;
        }

        const classNameAttribute = node.attributes.find(
          (attr): attr is TSESTree.JSXAttribute =>
            attr.type === 'JSXAttribute' &&
            attr.name.type === 'JSXIdentifier' &&
            attr.name.name === 'className'
        );

        const requiredClass = isHeading ? 'text-balance' : 'text-pretty';
        const messageId = isHeading ? 'missingTextBalance' : 'missingTextPretty';

        if (!classNameAttribute) {
          context.report({
            node,
            messageId,
            fix(fixer) {
              return fixer.insertTextAfter(node.name, ` className="${requiredClass}"`);
            },
          });
          return;
        }

        if (!classNameAttribute.value) {
          context.report({
            node: classNameAttribute,
            messageId,
          });
          return;
        }

        if (classNameAttribute.value.type === 'Literal' && typeof classNameAttribute.value.value === 'string') {
          const classNames = classNameAttribute.value.value.split(' ');
          if (!classNames.includes(requiredClass)) {
            context.report({
              node: classNameAttribute,
              messageId,
              fix(fixer) {
                const val = classNameAttribute.value as TSESTree.Literal;
                const raw = val.raw;
                if (raw) {
                  return fixer.replaceText(val, raw.slice(0, -1) + ` ${requiredClass}` + raw.slice(-1));
                }
                return null;
              }
            });
          }
        } else if (classNameAttribute.value.type === 'JSXExpressionContainer') {
          const sourceCode = context.sourceCode;
          const expressionText = sourceCode.getText(classNameAttribute.value);
          if (!expressionText.includes(requiredClass)) {
            context.report({
              node: classNameAttribute,
              messageId,
            });
          }
        }
      },
    };
  },
};

export default requireTextBalance;
