/** @fileoverview no-invalid-web-resource-hints — source-owned documentation and executable examples. */
import type { RuleDocumentation } from "../documentation.js";

export const NO_INVALID_WEB_RESOURCE_HINTS_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Keep native resource hints consistent with browser loading and preload request modes.",
  rationale:
    "Lazy loading delays even explicitly high-priority images until layout. Font preloads with incompatible credentials modes cannot satisfy the subsequent font request. The unsupported loading=auto value and obsolete importance attribute do not express supported native loading behavior. Oxlint 1.91 still accepts importance, so this advisory fills that verified upstream gap.",
  remediation:
    "Review whether the image is critical or offscreen, use the matching loading policy, specify the preload destination, and use anonymous CORS for font preloads. Do not change request behavior automatically.",
  category: "performance",
  requiresTypeInformation: false,
  limitations: [
    "Only intrinsic JSX img, iframe, video, audio, script and link attributes are inspected. Custom framework media components, HTML strings and DOM mutations are outside this rule.",
    "Stable local string bindings are resolved. Later unknown spreads and dynamic values remain unproven; explicit attributes after spreads can establish a finding.",
    "The rule does not infer which element is LCP, count page-wide priority hints, require image dimensions that may come from CSS, or require sizes when 100vw may be correct.",
  ],
  references: [
    "https://github.com/GoogleChrome/modern-web-guidance/blob/4dd968349e54ca45a05dd5c818fb035c9054b022/skills/modern-web-guidance/guides/performance/optimize-image-priority.md",
    "https://github.com/GoogleChrome/modern-web-guidance/blob/4dd968349e54ca45a05dd5c818fb035c9054b022/skills/modern-web-guidance/guides/performance/optimize-preload-priority.md",
    "https://github.com/GoogleChrome/modern-web-guidance/blob/4dd968349e54ca45a05dd5c818fb035c9054b022/skills/modern-web-guidance/guides/performance/optimize-script-priority.md",
  ],
  examples: [
    {
      id: "eager-critical-image",
      scenarioId: "image-loading",
      title: "Load a declared critical image eagerly",
      outcome: "no-match",
      files: [
        {
          path: "src/view.tsx",
          source: '<img loading="eager" fetchPriority="high" />',
        },
      ],
      focusPath: "src/view.tsx",
      expectedCount: 0,
      public: true,
    },
    {
      id: "lazy-critical-image",
      scenarioId: "image-loading",
      title: "Review conflicting image hints",
      outcome: "match",
      files: [
        {
          path: "src/view.tsx",
          source: '<img loading="lazy" fetchPriority="high" />',
        },
      ],
      focusPath: "src/view.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "anonymous-font-preload",
      scenarioId: "font-preload",
      title: "Match the font request mode",
      outcome: "no-match",
      files: [
        {
          path: "src/view.tsx",
          source: '<link rel="preload" as="font" href="/font.woff2" crossOrigin="anonymous" />',
        },
      ],
      focusPath: "src/view.tsx",
      expectedCount: 0,
      public: true,
    },
    {
      id: "font-preload-without-cors",
      scenarioId: "font-preload",
      title: "Review a non-reusable font preload",
      outcome: "match",
      files: [
        {
          path: "src/view.tsx",
          source: '<link rel="preload" as="font" href="/font.woff2" />',
        },
      ],
      focusPath: "src/view.tsx",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
