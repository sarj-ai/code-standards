// vitest: shared-module-graph
import rule from "../../src/rules/prefer-logical-tailwind-utilities.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester({ lang: "tsx" });

RULE_TESTER.run("prefer-logical-tailwind-utilities", rule, {
  valid: [
    '<div className="constructor toString __proto__ hasOwnProperty" />',
    '<div className="ms-2 pe-4 text-start border-e rounded-ss-lg" />',
    '<div className="left-(--coordinate) right-0" />',
    '<div title="ml-2" />',
    "<div className={classes} />",
    '<div className="rtl:ml-2 ltr:mr-4" />',
    '<div className="bg-[url(https://example.com/ml-2)]" />',
    { code: '<div className="ml-2" />', options: [{ enabled: false }] },
    {
      code: '<div className="ml-2" />',
      options: [{ allowUtilities: ["ml-2"] }],
    },
    {
      code: '<div className="ml-2" />',
      filename: "/repo/src/generated/layout.tsx",
    },
    '<div className="ml-2" {...props} />',
    '<div className="ml-2" className="ms-2" />',
  ],
  invalid: [
    {
      code: '<div className="ml-2" />',
      errors: [
        {
          messageId: "physicalUtility",
          data: { utility: "ml-2", replacement: "ms-2" },
          suggestions: [{ messageId: "replaceWithLogical", output: '<div className="ms-2" />' }],
        },
      ],
    },
    {
      code: '<div className="hover:!mr-2" />',
      errors: [
        {
          messageId: "physicalUtility",
          data: { utility: "hover:!mr-2", replacement: "hover:!me-2" },
          suggestions: [{ messageId: "replaceWithLogical", output: '<div className="hover:!me-2" />' }],
        },
      ],
    },
    {
      code: '<div className="md:-ml-2!" />',
      errors: [
        {
          messageId: "physicalUtility",
          data: { utility: "md:-ml-2!", replacement: "md:-ms-2!" },
          suggestions: [{ messageId: "replaceWithLogical", output: '<div className="md:-ms-2!" />' }],
        },
      ],
    },
    {
      code: '<div className="[&:hover]:border-l-2" />',
      errors: [
        {
          messageId: "physicalUtility",
          data: {
            utility: "[&:hover]:border-l-2",
            replacement: "[&:hover]:border-s-2",
          },
          suggestions: [{ messageId: "replaceWithLogical", output: '<div className="[&:hover]:border-s-2" />' }],
        },
      ],
    },
    {
      code: '<div className="rounded-tl-lg text-right" />',
      errors: [
        {
          messageId: "physicalUtility",
          data: {
            utility: "rounded-tl-lg text-right",
            replacement: "rounded-ss-lg text-end",
          },
          suggestions: [{ messageId: "replaceWithLogical", output: '<div className="rounded-ss-lg text-end" />' }],
        },
      ],
    },
    {
      code: '<div className="left-0" />',
      options: [{ checkInsets: true }],
      errors: [{ messageId: "physicalUtility", suggestions: [{ messageId: "replaceWithLogical", output: '<div className="start-0" />' }] }],
    },
    {
      code: '<div {...props} className={"pl-2"} />',
      errors: [{ messageId: "physicalUtility", suggestions: [{ messageId: "replaceWithLogical", output: '<div {...props} className={"ps-2"} />' }] }],
    },
    {
      code: "<div className={`mr-2`} />",
      errors: [{ messageId: "physicalUtility", suggestions: [{ messageId: "replaceWithLogical", output: "<div className={`me-2`} />" }] }],
    },
    {
      name: "preserves whitespace, duplicate utilities, and explicit allow entries",
      code: '<div className=" ml-2  ml-2 text-right\tpr-4 " />',
      options: [{ allowUtilities: ["text-right"] }],
      errors: [{ messageId: "physicalUtility", suggestions: [{ messageId: "replaceWithLogical", output: '<div className=" ms-2  ms-2 text-right\tpe-4 " />' }] }],
    },
    {
      name: "preserves JSX entity spellings without guessing raw offsets",
      code: '<div className="ml-2&#32;mr-4" />',
      errors: [{ messageId: "physicalUtility", suggestions: [] }],
    },
    {
      name: "preserves JavaScript escape spellings without guessing raw offsets",
      code: '<div className={"ml-2\\tpr-4"} />',
      errors: [{ messageId: "physicalUtility", suggestions: [] }],
    },
  ],
});
