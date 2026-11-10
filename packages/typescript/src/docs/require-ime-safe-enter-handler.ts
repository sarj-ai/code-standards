import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_IME_SAFE_ENTER_HANDLER_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Preserve IME composition before Enter submits or blurs a native text control.",
  rationale:
    "The Enter key confirms Japanese, Chinese and Korean composition as well as triggering custom actions. An unguarded native form submission or blur interrupts composing text.",
  remediation:
    "Check the native keyboard event composition state before the action. Retain the Safari keyCode 229 or composition-timestamp fallback required by the browser policy; offer a native submit button.",
  category: "correctness",
  requiresTypeInformation: false,
  limitations: [
    "Only inline editable input/textarea keydown handlers with direct Enter equality (optionally combined with !shiftKey) and currentTarget.blur() or currentTarget.form.requestSubmit() are checked. Unknown guards and rebound event parameters remain unproven. Referenced handlers, custom components, arbitrary submission helpers, logical/conditional branches and DOM listeners need review.",
    "The presence of a composition/keyCode/modifier check or composition listener suppresses the warning conservatively; this does not prove the guard dominates the action or implements the correct Safari fallback.",
  ],
  references: [
    "https://github.com/GoogleChrome/modern-web-guidance/blob/4dd968349e54ca45a05dd5c818fb035c9054b022/skills/modern-web-guidance/guides/forms/ime-safe-enter-submit.md",
  ],
  examples: [
    {
      id: "guarded-composition",
      title: "guarded composition",
      outcome: "no-match",
      files: [
        {
          path: "src/input.tsx",
          source:
            '<textarea onKeyDown={e => { if (e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229) return; if (e.key === "Enter") { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} />',
        },
      ],
      focusPath: "src/input.tsx",
      expectedCount: 0,
      public: true,
    },
    {
      id: "interrupted-composition",
      title: "interrupted composition",
      outcome: "match",
      files: [
        {
          path: "src/input.tsx",
          source:
            '<textarea onKeyDown={e => { if (e.key === "Enter") e.currentTarget.form?.requestSubmit(); }} />',
        },
      ],
      focusPath: "src/input.tsx",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
