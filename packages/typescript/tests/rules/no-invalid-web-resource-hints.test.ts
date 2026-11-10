// vitest: shared-module-graph
import rule from "../../src/rules/no-invalid-web-resource-hints.js";
import { ruleTester } from "./_tester.js";

ruleTester({ lang: "tsx" }).run("no-invalid-web-resource-hints", rule, {
  valid: [
    "<img importance={undefined} />",
    '<img importance="high" {...props} />',
    '<img fetchPriority="high" loading="eager" />',
    '<img loading="lazy" />',
    '<img fetchPriority={priority} loading="lazy" />',
    '<img loading="lazy" fetchPriority="high" {...props} />',
    '<img loading="lazy" {...props} fetchPriority="high" />',
    '<Image loading="lazy" fetchPriority="high" />',
    '<link rel="preload" as="font" crossOrigin="anonymous" />',
    '<link rel="preload" as="font" crossOrigin="" />',
    '<link rel="preload" as="font" crossOrigin={mode} />',
    '<link rel="preload" as="font" {...props} />',
    '<link {...props} rel="preload" as="font" crossOrigin="anonymous" />',
    '<link rel="modulepreload" />',
    "<link rel={relation} />",
    '<link rel="preload" as={destination} />',
    '<div importance="local-component-state" loading="auto" />',
    { filename: "generated/media.tsx", code: '<img loading="lazy" fetchPriority="high" />' },
    '// @generated\nconst image = <img loading="lazy" fetchPriority="high" />;',
    'const description = "<img loading=lazy fetchpriority=high>";',
    'let priority = "high"; priority = setting; <img loading="lazy" fetchPriority={priority} />;',
  ],
  invalid: [
    { code: '<img importance="high" />', errors: [{ messageId: "obsoleteImportance" }] },
    { code: '<script importance="low" />', errors: [{ messageId: "obsoleteImportance" }] },
    {
      code: '<img loading="lazy" fetchPriority="high" />',
      errors: [{ messageId: "criticalLazy" }],
    },
    {
      code: '<img loading={"lazy"} fetchpriority="high" />',
      errors: [{ messageId: "criticalLazy" }],
    },
    {
      code: 'const PRIORITY = "high"; <img loading="lazy" fetchPriority={PRIORITY} />;',
      errors: [{ messageId: "criticalLazy" }],
    },
    {
      code: '<img {...props} loading="lazy" fetchPriority="high" />',
      errors: [{ messageId: "criticalLazy" }],
    },
    { code: '<iframe loading="auto" />', errors: [{ messageId: "invalidLoading" }] },
    { code: '<link rel="preload" as="font" />', errors: [{ messageId: "fontCors" }] },
    {
      code: '<link rel="preload" as="font" crossOrigin="use-credentials" />',
      errors: [{ messageId: "fontCors" }],
    },
    { code: '<link rel="preload" href="/main.css" />', errors: [{ messageId: "preloadAs" }] },
    { code: '<link rel="preload" as="" />', errors: [{ messageId: "preloadAs" }] },
  ],
});
